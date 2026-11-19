"""Combine the CLI assembly, real Chromium, model transport, and batch records."""

import asyncio
import base64
import contextlib
import functools
import http.server
import io
import json
import tempfile
import threading
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import httpx2
from agent_support import PLAN
from checkpoint_fixtures import submit
from input_fixtures import config
from openai import AsyncOpenAI
from stream_fixtures import streamed_completion
from trace_fixtures import CapturingExporter

from uiprobe.__main__ import main, run_files
from uiprobe.browser import Browser
from uiprobe.model_service import ModelService, ModelServiceConfig
from uiprobe.recording import SubmissionRecord
from uiprobe.suite_runner import SuiteRunner


def browser_case(case_id, *checkpoints):
    return {
        "id": case_id,
        "name": case_id,
        "checkpoints": [
            {
                "id": identifier,
                "execution": {"goal": f"Goal for {identifier}", "instructions": []},
                "assertions": [
                    {"id": identifier, "expected": f"Evidence for {identifier}"}
                ],
            }
            for identifier in checkpoints
        ],
    }


def verdict(identifier, status):
    return (
        "final_result",
        {
            "results": [
                {"assertion_id": identifier, "status": status, "reason": "Observed"}
            ]
        },
    )


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


class SerialAsyncCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(directory)
        self.case_path = self.root / "cases.json"
        self.config_path = self.root / "config.json"
        self.runs = self.root / "runs"
        (self.root / "page.html").write_text(
            '<button style="position:absolute;left:10px;top:10px" '
            "onclick=\"this.textContent='Clicked'\">Click me</button>"
        )
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            functools.partial(
                http.server.SimpleHTTPRequestHandler, directory=directory
            ),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addAsyncCleanup(asyncio.to_thread, server.shutdown)
        self.defaults = {
            **config(str(self.runs)),
            "entry_url": f"http://127.0.0.1:{server.server_port}/page.html",
            "verification_concurrency": 2,
            "max_actions": 1,
            "timeout_seconds": 15,
        }
        self.exporter = CapturingExporter()
        self.headless: list[bool] = []
        self.request_count = 0

    async def configure(self, cases, execute, verify):
        self.case_path.write_text(json.dumps(cases))
        self.config_path.write_text(json.dumps({"defaults": self.defaults}))

        async def respond(request):
            self.request_count += 1
            number = self.request_count
            body = json.loads(request.content)
            self.assertIs(body["stream"], True)
            tools = {item["function"]["name"] for item in body.get("tools", [])}
            if "final_result" in tools:
                tool_calls = [await verify(body)]
            else:
                tool_calls = await execute(body, tools)

            message = {"role": "assistant", "content": "Execution complete"}
            if tool_calls:
                message = {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": f"call_{number}_{index}",
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }
                        for index, (name, args) in enumerate(tool_calls)
                    ],
                }
            return streamed_completion(
                {
                    "id": f"response_{number}",
                    "created": 1,
                    "model": "controlled",
                    "choices": [
                        {
                            "index": 0,
                            "message": message,
                            "finish_reason": "tool_calls" if tool_calls else "stop",
                        }
                    ],
                }
            )

        def browser_factory(*, headless):
            self.headless.append(headless)
            # Honor the application flag at the factory boundary. The regression
            # itself must run without a graphical display.
            return Browser()

        self.service = ModelService(
            ModelServiceConfig("http://controlled/v1", "test", "controlled")
        )
        self.addAsyncCleanup(self.service.close)

        await self.service.close()
        self.service.client = AsyncOpenAI(
            base_url=self.service.config.base_url,
            api_key="test",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
        )

        self.enterContext(
            patch(
                "uiprobe.__main__.SuiteRunner",
                functools.partial(SuiteRunner, exporter=self.exporter),
            )
        )
        self.enterContext(patch("uiprobe.__main__.Browser", browser_factory))
        self.factory = self.enterContext(
            patch("uiprobe.__main__.ModelService", return_value=self.service)
        )
        self.enterContext(
            patch(
                "uiprobe.__main__.ModelServiceConfig.from_env",
                return_value=self.service.config,
            )
        )

    async def test_mixed_batch_keeps_evidence_order_and_stops_on_recording_failure(
        self,
    ):
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        recording_execution_waiting = asyncio.Event()
        recording_execution_exited = asyncio.Event()
        third_finished = asyncio.Event()
        first_closed = asyncio.Event()
        completed = []
        saved_results_at_open = []
        first_completed_at_next_open = []
        active = set()
        evidence = {}
        click = ("click", {"screenshot_id": "screen-1", "x": 20, "y": 20})
        steps = iter(
            [
                [PLAN, submit("initial"), click],
                [click, submit("changed")],
                [submit("queued")],
                [],
                [submit("uncertain")],
                [],
                [submit("clean")],
                [],
                [submit("unrecordable")],
                [],
            ]
        )
        starts = Counter()
        outcomes = {
            "initial": "failed",
            "changed": "passed",
            "queued": "passed",
            "uncertain": "error",
            "clean": "passed",
            "unrecordable": "failed",
        }

        original_open = Browser.open

        async def open_browser(browser, *args, **kwargs):
            saved_results_at_open.append(len(list(self.runs.glob("*/result.json"))))
            if len(saved_results_at_open) == 2:
                first_completed_at_next_open.extend(completed)
            return await original_open(browser, *args, **kwargs)

        async def execute(body, tools):
            step = next(steps)
            if step and step[0] == PLAN:
                self.assertNotIn("Goal for changed", str(body))
                self.assertNotIn("Goal for queued", str(body))
            elif step and step[0] == click:
                await first_started.wait()
                self.assertNotIn("Goal for queued", str(body))
            elif step == [submit("queued")]:
                self.assertEqual(tools, {"submit_checkpoint"})
                self.assertIn("Goal for queued", str(body))
                await second_started.wait()
            if not step:
                self.assertEqual(tools, set())
                if "Goal for unrecordable" in str(body):
                    recording_execution_waiting.set()
                    try:
                        await asyncio.Future()
                    finally:
                        recording_execution_exited.set()
            return step

        async def verify(body):
            (identifier,) = [
                key for key in outcomes if f"Evidence for {key}" in str(body)
            ]
            starts[identifier] += 1
            active.add(identifier)
            self.assertLessEqual(len(active), 2)
            (image,) = [
                part["image_url"]["url"]
                for message in body["messages"]
                if isinstance(message.get("content"), list)
                for part in message["content"]
                if part["type"] == "image_url"
            ]
            evidence[identifier] = base64.b64decode(image.split(",", 1)[1])
            try:
                if identifier == "initial":
                    first_started.set()
                    await third_finished.wait()
                elif identifier == "changed":
                    second_started.set()
                    await first_closed.wait()
                elif identifier == "queued":
                    self.assertNotIn("changed", active)
                    self.assertIn("initial", active)
                elif identifier == "unrecordable":
                    await recording_execution_waiting.wait()
                return verdict(identifier, outcomes[identifier])
            finally:
                active.remove(identifier)

        original_close = Browser.close

        async def close(browser):
            await original_close(browser)
            if not first_closed.is_set():
                self.assertEqual(dict(starts), {"initial": 1, "changed": 1})
                self.assertEqual(completed, [])
                first_closed.set()

        original_append = SubmissionRecord.append

        def append(record, event):
            identifier = record.submission.checkpoint_id
            if (
                event["type"] == "verification_finished"
                and identifier == "unrecordable"
            ):
                raise OSError("controlled verification write failure")
            original_append(record, event)
            if event["type"] == "verification_finished":
                completed.append(identifier)
                if identifier == "queued":
                    third_finished.set()

        await self.configure(
            {
                "cases": [
                    browser_case("pipeline", "initial", "changed", "queued"),
                    {"id": "invalid"},
                    browser_case("ordinary-error", "uncertain"),
                    browser_case("ordinary-pass", "clean"),
                    browser_case("recording-error", "unrecordable"),
                    browser_case("not-started", "unreached"),
                ]
            },
            execute,
            verify,
        )
        with (
            patch.object(Browser, "open", open_browser),
            patch.object(Browser, "close", close),
            patch.object(SubmissionRecord, "append", append),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = await asyncio.to_thread(
                main,
                [
                    "--case",
                    str(self.case_path),
                    "--config",
                    str(self.config_path),
                    "--headed",
                ],
            )

        suite = json.loads(stdout.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(suite["status"], "error")
        self.assertEqual(suite["stop_reason"], "recording_error")
        self.assertEqual(
            [entry["status"] for entry in suite["cases"]],
            ["failed", "error", "error", "passed", "error", "not_run"],
        )
        self.assertEqual(
            [entry["source"]["case_index"] for entry in suite["cases"]], list(range(6))
        )
        self.assertEqual(self.headless, [False] * 4)
        self.assertEqual(saved_results_at_open, [0, 1, 2, 3])
        self.assertEqual(first_completed_at_next_open, ["changed", "queued", "initial"])
        self.factory.assert_called_once()
        self.assertTrue(self.service.client.is_closed())
        self.assertEqual(active, set())
        self.assertEqual(starts, Counter(outcomes.keys()))
        self.assertIsNone(next(steps, None))
        self.assertEqual(
            completed, ["changed", "queued", "initial", "uncertain", "clean"]
        )
        suite_dir = self.runs / suite["suite_id"]
        self.assertEqual(json.loads((suite_dir / "result.json").read_text()), suite)
        self.assertEqual(
            list(self.runs.rglob("trace.json")), [suite_dir / "trace.json"]
        )
        results = [
            entry["session_result"]
            for entry in suite["cases"]
            if entry["session_result"] is not None
        ]
        self.assertEqual(
            {path.name for path in self.runs.iterdir()},
            {suite["suite_id"], *(result["session_id"] for result in results)},
        )
        for result in [suite, *results]:
            self.assertTrue(result["artifact_paths"])
            for path in result["artifact_paths"]:
                self.assertTrue(Path(path).exists(), path)
        trace = json.loads((suite_dir / "trace.json").read_text())
        payload = b"".join(self.exporter.payloads)
        self.assertIn(b"submission_id", payload)
        self.assertNotIn(b"data:image", payload)
        self.assertNotIn(b"iVBORw0KGgo", payload)

        first = suite["cases"][0]["session_result"]
        self.assertEqual(first["action_count"], 1)
        session_dir = self.runs / first["session_id"]
        self.assertEqual(json.loads((session_dir / "result.json").read_text()), first)
        self.assertEqual(
            sorted(path.name for path in session_dir.rglob("*.png")),
            ["screen-1.png", "screen-2.png"],
        )
        self.assertNotEqual(evidence["initial"], evidence["changed"])
        self.assertEqual(evidence["changed"], evidence["queued"])
        submissions = set()
        for checkpoint, identifier, image_id in zip(
            first["checkpoints"],
            ("initial", "changed", "queued"),
            ("screen-1", "screen-2", "screen-2"),
            strict=True,
        ):
            self.assertEqual(checkpoint["checkpoint_id"], identifier)
            self.assertEqual(checkpoint["screenshot_id"], image_id)
            submission_id = checkpoint["submission_id"]
            submissions.add(submission_id)
            record = session_dir / "submissions" / submission_id
            saved = json.loads((record / "input.json").read_text())
            self.assertEqual(saved["submission_id"], submission_id)
            self.assertEqual(saved["screenshot_id"], image_id)
            self.assertEqual(
                (session_dir / "screenshots" / f"{image_id}.png").read_bytes(),
                evidence[identifier],
            )
            self.assertIn(image_id, (record / "history.json").read_text())
            self.assertIn(image_id, (record / "requests.jsonl").read_text())
            (span,) = [
                span
                for span in trace["spans"]
                if span["name"] == "verification"
                and span["attributes"].get("submission_id") == submission_id
            ]
            self.assertEqual(span["attributes"]["session_id"], first["session_id"])
            self.assertEqual(
                span["context"]["trace_id"].removeprefix("0x"), trace["trace_id"]
            )
        self.assertEqual(len(submissions), 3)
        self.assertEqual(
            [
                event["tool"]
                for event in read_events(session_dir / "events.jsonl")
                if event.get("status") == "rejected"
            ],
            ["click"],
        )
        last = suite["cases"][4]["session_result"]
        self.assertTrue(recording_execution_exited.is_set())
        self.assertEqual(last["stop_reason"], "recording_error")
        self.assertIsNone(last["execution_outcome"])
        self.assertEqual(last["checkpoints"][0]["verdict"]["status"], "failed")
        self.assertEqual(
            [error["operation"] for error in last["errors"]],
            ["append_verification_finished"],
        )

    async def test_single_case_with_failed_verdict_prints_batch_result_and_exits_one(
        self,
    ):
        steps = iter([[submit("initial")], []])

        async def execute(body, tools):
            return next(steps)

        async def verify(body):
            self.assertIn("Evidence for initial", str(body))
            return verdict("initial", "failed")

        await self.configure(browser_case("single", "initial"), execute, verify)
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = await asyncio.to_thread(
                main, ["--case", str(self.case_path), "--config", str(self.config_path)]
            )

        self.assertEqual(code, 1)
        suite = json.loads(stdout.getvalue())
        self.assertEqual(suite["status"], "failed")
        (entry,) = suite["cases"]
        self.assertEqual(entry["source"]["case_index"], 0)
        self.assertEqual(entry["status"], "failed")
        (checkpoint,) = entry["session_result"]["checkpoints"]
        self.assertEqual(checkpoint["verdict"]["status"], "failed")

    async def test_cancellation_reaches_caller_after_active_requests_and_batch_save(
        self,
    ):
        verification_started = asyncio.Event()
        execution_waiting = asyncio.Event()
        exited = set()
        steps = iter([[submit("active")], [submit("queued")]])

        async def block_request(kind, started):
            started.set()
            try:
                await asyncio.Future()
            finally:
                exited.add(kind)

        async def execute(body, tools):
            step = next(steps, None)
            if step is not None:
                return step
            await block_request("execution", execution_waiting)
            raise AssertionError("Execution should be cancelled")

        async def verify(body):
            self.assertIn("Evidence for active", str(body))
            await block_request("verification", verification_started)
            raise AssertionError("Verification should be cancelled")

        self.defaults["verification_concurrency"] = 1
        await self.configure(
            {
                "cases": [
                    browser_case("cancel", "active", "queued"),
                    browser_case("later", "later"),
                ]
            },
            execute,
            verify,
        )
        task = asyncio.create_task(run_files(self.case_path, self.config_path))
        try:
            async with asyncio.timeout(10):
                await execution_waiting.wait()
                await verification_started.wait()
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertEqual(exited, {"execution", "verification"})
        self.assertEqual(self.request_count, 4)
        self.assertEqual(self.headless, [True])
        self.assertTrue(self.service.client.is_closed())
        (trace,) = self.runs.rglob("trace.json")
        suite = json.loads(trace.with_name("result.json").read_text())
        self.assertEqual(suite["stop_reason"], "cancelled")
        self.assertEqual(
            [entry["status"] for entry in suite["cases"]], ["error", "not_run"]
        )
        session = suite["cases"][0]["session_result"]
        self.assertEqual(session["stop_reason"], "cancelled")
        self.assertEqual(
            [item["state"] for item in session["checkpoints"]], ["finished"] * 2
        )
        self.assertEqual(
            [item["verdict"]["status"] for item in session["checkpoints"]],
            ["error"] * 2,
        )
