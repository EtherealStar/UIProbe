"""Cross-stage failures exercised through real browser and application boundaries."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import test_session_lifecycle as lifecycle
from agent_support import PLAN, calls
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from test_session_input import case, config
from trace_fixtures import CapturingExporter

from uiprobe.__main__ import run_files
from uiprobe.agent import ExecutionAgent
from uiprobe.browser import Browser
from uiprobe.model_service import ModelServiceConfig
from uiprobe.observability import run_trace
from uiprobe.recording import Recorder, SessionRecord
from uiprobe.session import Session
from uiprobe.verification import Verification


def response(messages, info):
    if info.output_tools:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "results": [
                            {
                                "assertion_id": "home",
                                "status": "passed",
                                "reason": "Home visible",
                            }
                        ]
                    },
                )
            ]
        )
    return ModelResponse(parts=[TextPart("Done")])


class CombinedFailureTests(unittest.IsolatedAsyncioTestCase):
    url: str
    asyncSetUp = lifecycle.LifecycleTests.asyncSetUp
    asyncTearDown = lifecycle.LifecycleTests.asyncTearDown

    async def test_dispatch_failure_survives_log_history_cleanup_and_final_save_failures(
        self,
    ):
        class BrokenBrowser(Browser):
            async def click(self, screenshot_id, x, y, deadline_at, before_dispatch):
                before_dispatch()
                raise RuntimeError("original dispatch failure")

            async def close(self):
                await super().close()
                raise RuntimeError("cleanup failure")

        class BrokenRecord(SessionRecord):
            broken = False

            def append(self, event):
                if event.get("status") == "error":
                    self.broken = True
                    raise OSError("failure log unavailable")
                super().append(event)

            def save_messages(self, role, messages, screenshot):
                if self.broken:
                    raise OSError("history unavailable")
                super().save_messages(role, messages, screenshot)

            def finish(self, result, history):
                raise OSError("result unavailable")

        class BrokenRecorder(Recorder):
            def begin(self, session_id, output_dir):
                record = super().begin(session_id, output_dir)
                return BrokenRecord(session_id, record.directory)

        steps = iter(
            [
                calls(PLAN),
                calls(("click", {"screenshot_id": "screen-1", "x": 10, "y": 10})),
            ]
        )
        verification = AsyncMock()
        browser = BrokenBrowser()
        with tempfile.TemporaryDirectory() as directory, run_trace(CapturingExporter()):
            cfg = config(directory)
            cfg["entry_url"] = self.url
            result = await Session(
                browser_factory=lambda: browser,
                recorder=BrokenRecorder(),
                agent=ExecutionAgent(FunctionModel(lambda m, i: next(steps))),
                verification=verification,
            ).run(json.dumps(case()), cfg)
            self.assertEqual(result.stop_reason, "execution_error")
            self.assertEqual(result.action_count, 1)
            self.assertEqual(result.last_screenshot_id, "screen-1")
            self.assertIsNone(result.submission)
            verification.evaluate.assert_not_awaited()
            assert browser.browser is not None
            self.assertFalse(browser.browser.is_connected())
            self.assertEqual(result.errors[0].operation, "click")
            run = Path(directory, result.session_id)
            diagnostics = [
                json.loads(p.read_text()) for p in (run / "diagnostics").glob("*.json")
            ]
            original = next(
                d for d in diagnostics if d["error_id"] == result.errors[0].error_id
            )
            self.assertIn("original dispatch failure", original["traceback"])
            self.assertTrue(
                {
                    "click",
                    "append_tool_failure",
                    "save_execution_history",
                    "close_browser",
                    "save_result",
                }
                <= {e.operation for e in result.errors}
            )
            self.assertTrue(all(Path(p).exists() for p in result.artifact_paths))
            self.assertFalse(
                any(p.endswith("result.json") for p in result.artifact_paths)
            )

    async def test_verification_failure_survives_diagnostic_and_history_save_failure(
        self,
    ):
        class BrokenRecord(SessionRecord):
            broken = False

            def save_diagnostic(self, diagnostic):
                self.broken = True
                raise OSError("diagnostics unavailable")

            def save_messages(self, role, messages, screenshot):
                if role == "verification" and self.broken:
                    raise OSError("verification history unavailable")
                super().save_messages(role, messages, screenshot)

        class BrokenRecorder(Recorder):
            def begin(self, session_id, output_dir):
                record = super().begin(session_id, output_dir)
                return BrokenRecord(session_id, record.directory)

        def invalid(messages, info):
            raise RuntimeError("verification transport failed")

        with tempfile.TemporaryDirectory() as directory:
            cfg = config(directory)
            cfg["entry_url"] = self.url
            result = await Session(
                recorder=BrokenRecorder(),
                agent=ExecutionAgent(FunctionModel(response)),
                verification=Verification(FunctionModel(invalid)),
            ).run(json.dumps(case()), cfg)
            self.assertIsNotNone(result.submission)
            self.assertEqual(result.status, "error")
            self.assertEqual(result.errors[0].phase, "verification")
            self.assertEqual(result.errors[0].code, "model_request_failed")
            self.assertTrue(any(e.phase == "recording" for e in result.errors))
            self.assertTrue(all(Path(p).exists() for p in result.artifact_paths))

    async def test_application_close_failure_keeps_verdict_and_updates_snapshot(self):
        for failure in ("exception", "timeout", "save"):
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as directory,
            ):
                cfg = config(directory)
                cfg["entry_url"] = self.url
                config_path = Path(directory, "config.json")
                config_path.write_text(json.dumps(cfg))
                case_path = Path(directory, "case.json")
                case_path.write_text(json.dumps(case()))
                service = AsyncMock()
                service.config = ModelServiceConfig(
                    "http://controlled/v1", "test", "controlled"
                )
                if failure == "timeout":

                    async def close():
                        await asyncio.sleep(60)

                    service.client.close.side_effect = close
                else:
                    service.client.close.side_effect = RuntimeError(
                        "client close failed"
                    )
                original_finish = SessionRecord.finish

                def finish(record, result, history):
                    if failure == "save" and any(
                        e.operation == "close_model_client" for e in result.errors
                    ):
                        raise OSError("application snapshot unavailable")
                    return original_finish(record, result, history)

                exporter = CapturingExporter()
                with (
                    patch(
                        "uiprobe.__main__.ModelServiceConfig.from_env",
                        return_value=service.config,
                    ),
                    patch("uiprobe.__main__.ModelService", return_value=service),
                    patch(
                        "uiprobe.__main__.model_from_client",
                        return_value=FunctionModel(response),
                    ),
                    patch.object(SessionRecord, "finish", finish),
                    run_trace(exporter),
                ):
                    result = await run_files(case_path, config_path)
                self.assertEqual(result.status, "error")
                self.assertEqual(result.stop_reason, "verification_completed")
                assert result.verdict is not None and result.submission is not None
                self.assertEqual(result.verdict.status, "passed")
                self.assertEqual(result.submission.text, "Done")
                self.assertEqual(result.action_count, 0)
                self.assertEqual(result.last_screenshot_id, "screen-1")
                error = next(
                    e for e in result.errors if e.operation == "close_model_client"
                )
                run = Path(directory, result.session_id)
                diagnostic = json.loads(
                    (run / "diagnostics" / f"{error.error_id}.json").read_text()
                )
                self.assertIn(
                    "TimeoutError" if failure == "timeout" else "client close failed",
                    diagnostic["traceback"],
                )
                snapshot = json.loads((run / "result.json").read_text())
                if failure == "save":
                    self.assertEqual(snapshot["status"], "passed")
                    self.assertNotIn(str(run / "result.json"), result.artifact_paths)
                else:
                    self.assertEqual(
                        snapshot["errors"], [e.__dict__ for e in result.errors]
                    )
                trace = json.loads((run / "trace.json").read_text())
                self.assertIn("model_client.close", {s["name"] for s in trace["spans"]})
                self.assertIn(error.error_id.encode(), b"".join(exporter.payloads))
                service.client.close.assert_awaited_once()

    async def test_deadline_and_cancel_do_not_start_verification(self):
        for cancel in (False, True):
            with (
                self.subTest(cancel=cancel),
                tempfile.TemporaryDirectory() as directory,
            ):
                entered = asyncio.Event()

                async def waiting(messages, info):
                    entered.set()
                    await asyncio.sleep(60)
                    return ModelResponse(parts=[TextPart("Too late")])

                cfg = config(directory)
                cfg["entry_url"] = self.url
                cfg["timeout_seconds"] = 60 if cancel else 1.5
                verification = AsyncMock()
                browser = Browser()
                task = asyncio.create_task(
                    Session(
                        browser_factory=lambda: browser,
                        agent=ExecutionAgent(FunctionModel(waiting)),
                        verification=verification,
                    ).run(json.dumps(case()), cfg)
                )
                await asyncio.wait_for(entered.wait(), 5)
                if cancel:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    result = json.loads(
                        next(Path(directory).glob("*/result.json")).read_text()
                    )
                    self.assertEqual(result["stop_reason"], "cancelled")
                else:
                    result = await task
                    self.assertEqual(result.errors[0].code, "deadline_exhausted")
                    self.assertIsNone(result.submission)
                assert browser.browser is not None
                self.assertFalse(browser.browser.is_connected())
                verification.evaluate.assert_not_awaited()

    async def test_passed_verdict_survives_final_verification_history_failure(self):
        class FinalHistoryFailure(SessionRecord):
            def save_messages(self, role, messages, screenshot):
                if role == "verification" and any(
                    getattr(m, "kind", None) == "response" for m in messages
                ):
                    # Fail only after the framework has produced a complete result.
                    self.verification_writes = (
                        getattr(self, "verification_writes", 0) + 1
                    )
                    if self.verification_writes > 1:
                        raise OSError("final verification history unavailable")
                super().save_messages(role, messages, screenshot)

        class FinalHistoryRecorder(Recorder):
            def begin(self, session_id, output_dir):
                record = super().begin(session_id, output_dir)
                return FinalHistoryFailure(session_id, record.directory)

        with tempfile.TemporaryDirectory() as directory:
            cfg = config(directory)
            cfg["entry_url"] = self.url
            model = FunctionModel(response)
            result = await Session(
                recorder=FinalHistoryRecorder(),
                agent=ExecutionAgent(model),
                verification=Verification(model),
            ).run(json.dumps(case()), cfg)
            self.assertEqual(result.status, "error")
            self.assertEqual(result.stop_reason, "verification_completed")
            assert result.verdict is not None
            self.assertEqual(result.verdict.status, "passed")
            self.assertEqual(result.errors[0].operation, "save_verification_history")

    async def test_application_cancellation_survives_client_close_failure(self):
        entered = asyncio.Event()

        async def waiting(messages, info):
            entered.set()
            await asyncio.sleep(60)
            return ModelResponse(parts=[TextPart("Too late")])

        with tempfile.TemporaryDirectory() as directory:
            cfg = config(directory)
            cfg["entry_url"] = self.url
            config_path = Path(directory, "config.json")
            config_path.write_text(json.dumps(cfg))
            case_path = Path(directory, "case.json")
            case_path.write_text(json.dumps(case()))
            service = AsyncMock()
            service.config = ModelServiceConfig(
                "http://controlled/v1", "test", "controlled"
            )
            service.client.close.side_effect = RuntimeError(
                "close during cancel failed"
            )
            exporter = CapturingExporter()
            with (
                patch(
                    "uiprobe.__main__.ModelServiceConfig.from_env",
                    return_value=service.config,
                ),
                patch("uiprobe.__main__.ModelService", return_value=service),
                patch(
                    "uiprobe.__main__.model_from_client",
                    return_value=FunctionModel(waiting),
                ),
                run_trace(exporter),
            ):
                task = asyncio.create_task(run_files(case_path, config_path))
                await asyncio.wait_for(entered.wait(), 5)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            service.client.close.assert_awaited_once()
            saved = json.loads(next(Path(directory).glob("*/result.json")).read_text())
            self.assertEqual(saved["stop_reason"], "cancelled")
            self.assertIsNone(saved["submission"])
            self.assertIn(b"close_model_client", b"".join(exporter.payloads))
            trace = json.loads(next(Path(directory).glob("*/trace.json")).read_text())
            self.assertIn("model_client.close", {s["name"] for s in trace["spans"]})
