import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from input_fixtures import case, config

from uiprobe.recording import SuiteRecord
from uiprobe.suite_runner import SuiteRunner


class SuiteFinalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_trace_save_reports_only_available_batch_artifacts(self):
        release = threading.Event()
        completed = threading.Event()
        original_save = SuiteRecord.save_trace

        def blocked_save(record, *args):
            try:
                release.wait(1)
                original_save(record, *args)
            finally:
                completed.set()

        with tempfile.TemporaryDirectory() as directory:
            browser = Mock()
            service_factory = Mock(
                side_effect=RuntimeError("model configuration failed")
            )
            try:
                with (
                    patch.object(SuiteRecord, "save_trace", blocked_save),
                    patch("uiprobe.suite_runner.FINALIZATION_SECONDS", 0.1),
                ):
                    result = await SuiteRunner(
                        service_factory, browser_factory=browser
                    ).run(json.dumps(case()), {"defaults": config(directory)})
                self.assertFalse(completed.is_set())
                self.assertEqual(result.status, "error")
                self.assertEqual(result.cases[0].status, "not_run")
                self.assertIsNone(result.cases[0].session_result)
                self.assertEqual(
                    [e.operation for e in result.errors],
                    ["configure_model", "save_trace"],
                )
                trace = Path(directory, result.suite_id, "trace.json")
                saved_result = trace.with_name("result.json")
                self.assertNotIn(str(trace), result.artifact_paths)
                self.assertIn(str(saved_result), result.artifact_paths)
                snapshot = saved_result.read_bytes()
                browser.assert_not_called()
            finally:
                release.set()
                self.assertTrue(await asyncio.to_thread(completed.wait, 2))

            self.assertEqual(snapshot, saved_result.read_bytes())
            self.assertNotIn(str(trace), result.artifact_paths)
            spans = json.loads(trace.read_text())["spans"]
            self.assertIn("prepare_suite", {span["name"] for span in spans})
            self.assertIn("model_client.create", {span["name"] for span in spans})

    async def test_export_failure_preserves_case_and_suite_results(self):
        from unittest.mock import AsyncMock

        from opentelemetry.sdk.trace.export import SpanExportResult
        from pydantic_ai.models.function import FunctionModel
        from test_combined_failures import response
        from trace_fixtures import CapturingExporter

        from uiprobe.model_service import ModelServiceConfig
        from uiprobe.observation import BrowserState, Screenshot

        class FailedExport(CapturingExporter):
            def export(self, spans):
                super().export(spans)
                return SpanExportResult.FAILURE

        service = AsyncMock()
        service.config = ModelServiceConfig(
            "http://controlled/v1", "test", "controlled"
        )
        browser = AsyncMock()
        browser.open.return_value = BrowserState(
            Screenshot("screen-1", b"png", 1, 1), 1, 1
        )
        exporter = FailedExport()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "uiprobe.suite_runner.model_from_client",
                return_value=FunctionModel(response),
            ),
        ):
            result = await SuiteRunner(
                lambda: service,
                browser_factory=lambda: browser,
                exporter=exporter,
            ).run(
                json.dumps({"cases": [case(), {**case(), "id": "later"}]}),
                {"defaults": config(directory)},
            )

            self.assertEqual(result.status, "passed")
            self.assertEqual(result.errors, [])
            self.assertEqual(
                [item.status for item in result.cases], ["passed", "passed"]
            )
            trace = json.loads(
                Path(directory, result.suite_id, "trace.json").read_text()
            )
            self.assertTrue(trace["observability_incomplete"])
            self.assertGreaterEqual(trace["export"]["batches_failed"], 1)
            self.assertEqual(trace["export"]["remote_delivery"], "unknown")
            self.assertTrue(exporter.payloads)
            service.close.assert_awaited_once()

    async def test_repeated_cancellation_during_suite_save_persists_cancelled_result(
        self,
    ):
        entered = threading.Event()
        release = threading.Event()
        original_save = SuiteRecord.save_result

        def blocked_save(record, result):
            entered.set()
            release.wait(2)
            return original_save(record, result)

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(SuiteRecord, "save_result", blocked_save),
        ):
            browser = Mock()
            factory = Mock(
                side_effect=RuntimeError("configuration failure before cancellation")
            )
            task = asyncio.create_task(
                SuiteRunner(factory, browser_factory=browser).run(
                    json.dumps(case()), {"defaults": config(directory)}
                )
            )
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                for _ in range(2):
                    task.cancel()
                    await asyncio.sleep(0)
                self.assertFalse(task.done())
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task

            path = next(Path(directory).glob("*/result.json"))
            snapshot = json.loads(path.read_text())
            self.assertEqual(snapshot["stop_reason"], "cancelled")
            self.assertEqual(snapshot["status"], "error")
            self.assertEqual(
                [error["operation"] for error in snapshot["errors"]],
                ["configure_model"],
            )
            self.assertEqual(snapshot["cases"][0]["status"], "not_run")
            self.assertEqual(
                len(snapshot["artifact_paths"]), len(set(snapshot["artifact_paths"]))
            )
            events = [
                json.loads(line)
                for line in path.with_name("events.jsonl").read_text().splitlines()
            ]
            self.assertEqual([e["type"] for e in events].count("suite_finished"), 1)
            self.assertEqual(events[-1]["type"], "suite_cancelled")
            browser.assert_not_called()

    def test_cli_exits_without_waiting_for_timed_out_file_write(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "case.json")
            source.write_text(json.dumps(case()))
            settings = Path(directory, "config.json")
            settings.write_text(json.dumps({"defaults": config(directory)}))
            script = """
import sys
from threading import Event
from unittest.mock import patch
from uiprobe.__main__ import main
from uiprobe.recording import SuiteRecord

def block_trace(*args):
    Event().wait()

with (
    patch.object(SuiteRecord, 'save_trace', block_trace),
    patch('uiprobe.suite_runner.FINALIZATION_SECONDS', 0.15),
    patch('uiprobe.__main__.ModelServiceConfig.from_env', side_effect=RuntimeError),
):
    raise SystemExit(main(['--case', sys.argv[1], '--config', sys.argv[2]]))
"""
            completed = subprocess.run(
                [sys.executable, "-c", script, str(source), str(settings)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(completed.returncode, 2, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(
                [error["operation"] for error in result["errors"]],
                ["configure_model", "save_trace"],
            )
            self.assertFalse(
                any(path.endswith("trace.json") for path in result["artifact_paths"])
            )
