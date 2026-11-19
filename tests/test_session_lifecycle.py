import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from agent_support import finish_execution, submit_and_finish
from input_fixtures import config, prepared_case

from uiprobe.observation import BrowserState, Screenshot, Verdict
from uiprobe.recording import Recorder, SessionRecord
from uiprobe.session import Session, SessionCancelled


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import http.server
        import threading

        class Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<h1>Home</h1><button>Go</button>")

            def log_message(self, format, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/"

    async def asyncTearDown(self):
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join()

    async def run_failure(self, phase):
        with tempfile.TemporaryDirectory() as directory:
            browser = AsyncMock()
            browser.open.return_value = BrowserState(
                Screenshot("screen-1", b"png", 1, 1), 1, 1
            )
            agent = AsyncMock()
            agent.execute.side_effect = submit_and_finish
            verification = AsyncMock()
            verification.evaluate.return_value = Verdict(
                "test-submission", "passed", []
            )
            if phase == "initialization":
                browser.open.side_effect = RuntimeError("private")
            elif phase == "execution":
                agent.execute.side_effect = RuntimeError("private")
            elif phase == "verification":
                verification.evaluate.side_effect = RuntimeError("private")
            elif phase == "cleanup":
                browser.close.side_effect = RuntimeError("private")
            elif phase == "timeout":

                async def expire(*args, **kwargs):
                    await asyncio.sleep(1)

                agent.execute.side_effect = expire
            elif phase == "cancel":
                agent.execute.side_effect = asyncio.CancelledError

            class BrokenRecord(SessionRecord):
                def finish(self, result, history):
                    raise OSError("private")

            class BrokenRecorder(Recorder):
                def begin(self, session_id, output_dir, *, suite_id=None):
                    record = super().begin(session_id, output_dir, suite_id=suite_id)
                    return BrokenRecord(session_id, record.directory, suite_id)

            session = Session(
                browser_factory=lambda: browser,
                agent=agent,
                verification=verification,
                recorder=BrokenRecorder() if phase == "finish" else None,
            )
            cfg = config(directory)
            if phase == "timeout":
                cfg["timeout_seconds"] = 0.05
            if phase == "cancel":
                with self.assertRaises(asyncio.CancelledError):
                    await session.run(prepared_case(cfg))
                verification.evaluate.assert_not_awaited()
                browser.close.assert_awaited_once()
                return
            result = await session.run(prepared_case(cfg))
            self.assertEqual(result.status, "error")
            browser.close.assert_awaited_once()
            self.assertNotIn("private", repr(result))
            if phase in ("cleanup", "finish"):
                assert result.checkpoints[0].verdict is not None
                self.assertEqual(result.checkpoints[0].verdict.status, "passed")
                self.assertEqual(result.stop_reason, "execution_completed")
            elif phase in ("initialization", "execution", "timeout"):
                verification.evaluate.assert_not_awaited()
            self.assertTrue(all(Path(p).exists() for p in result.artifact_paths))

    async def test_stage_failures_preserve_conclusions_and_release_resources(self):
        for phase in (
            "initialization",
            "execution",
            "verification",
            "cleanup",
            "finish",
            "timeout",
            "cancel",
        ):
            with self.subTest(phase=phase):
                await self.run_failure(phase)

    async def test_real_browser_and_verification_preserve_pass_after_cleanup_failure(
        self,
    ):
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        from uiprobe.agent import ExecutionAgent
        from uiprobe.browser import Browser
        from uiprobe.verification import Verification

        class CloseFailure(Browser):
            async def close(self):
                await super().close()
                raise RuntimeError("cleanup failure")

        def respond(messages, info):
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
            return finish_execution(info)

        with tempfile.TemporaryDirectory() as directory:
            cfg = config(directory)
            cfg["entry_url"] = self.url
            model = FunctionModel(respond)
            result = await Session(
                browser_factory=CloseFailure,
                agent=ExecutionAgent(model),
                verification=Verification(model),
            ).run(prepared_case(cfg))
            self.assertEqual(result.status, "error")
            assert result.checkpoints[0].verdict is not None
            self.assertEqual(result.checkpoints[0].verdict.status, "passed")
            self.assertEqual(result.stop_reason, "execution_completed")
            assert result.checkpoints[0].verdict is not None
            submission_dir = (
                Path(directory, result.session_id, "submissions")
                / result.checkpoints[0].verdict.submission_id
            )
            self.assertTrue((submission_dir / "history.json").is_file())

    async def test_real_browser_faults_stop_execution_without_verification(self):
        from agent_support import PLAN, calls
        from pydantic_ai.models.function import FunctionModel

        from uiprobe.agent import ExecutionAgent
        from uiprobe.browser import Browser

        for fault in ("capture", "popup", "dispatch", "append"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:

                class FaultBrowser(Browser):
                    async def capture(self, deadline_at):
                        if fault == "capture" and self.sequence:
                            raise RuntimeError("capture failed")
                        return await super().capture(deadline_at)

                    async def click(
                        self, screenshot_id, x, y, deadline_at, before_dispatch
                    ):
                        if fault == "dispatch":
                            before_dispatch()
                            raise RuntimeError("dispatch failed")
                        if fault == "popup":
                            await self.context.new_page()
                        return await super().click(
                            screenshot_id, x, y, deadline_at, before_dispatch
                        )

                class FaultRecord(SessionRecord):
                    def append(self, event):
                        if fault == "append" and event["type"] == "tool_finished":
                            raise OSError("append failed")
                        return super().append(event)

                class FaultRecorder(Recorder):
                    def begin(self, session_id, output_dir, *, suite_id=None):
                        record = super().begin(
                            session_id, output_dir, suite_id=suite_id
                        )
                        return FaultRecord(session_id, record.directory, suite_id)

                browser = FaultBrowser()
                responses = [
                    calls(PLAN),
                    calls(("click", {"screenshot_id": "screen-1", "x": 20, "y": 20})),
                ]
                requests = []

                def respond(messages, info):
                    requests.append(messages)
                    return responses.pop(0)

                verification = AsyncMock()
                cfg = config(directory)
                cfg["entry_url"] = self.url
                result = await Session(
                    browser_factory=lambda: browser,
                    recorder=FaultRecorder(),
                    agent=ExecutionAgent(FunctionModel(respond)),
                    verification=verification,
                ).run(prepared_case(cfg))
                self.assertEqual(result.status, "error")
                verification.evaluate.assert_not_awaited()
                self.assertEqual(len(requests), 1 if fault == "append" else 2)
                self.assertEqual(result.last_screenshot_id, "screen-1")
                self.assertEqual(result.action_count, 0 if fault == "append" else 1)
                assert browser.browser is not None
                self.assertFalse(browser.browser.is_connected())

    async def test_blocked_final_save_has_independent_wait_limit(self):
        import threading

        release = threading.Event()
        completed = threading.Event()

        class SlowRecord(SessionRecord):
            def finish(self, result, history):
                release.wait(10)
                try:
                    return super().finish(result, history)
                finally:
                    completed.set()

        class SlowRecorder(Recorder):
            def begin(self, session_id, output_dir, *, suite_id=None):
                record = super().begin(session_id, output_dir, suite_id=suite_id)
                return SlowRecord(session_id, record.directory, suite_id)

        with tempfile.TemporaryDirectory() as directory:
            browser = AsyncMock()
            browser.open.return_value = BrowserState(
                Screenshot("screen-1", b"png", 1, 1), 1, 1
            )
            agent = AsyncMock()
            agent.execute.side_effect = submit_and_finish
            verification = AsyncMock()
            verification.evaluate.return_value = Verdict(
                "test-submission", "passed", []
            )
            try:
                async with asyncio.timeout(7):
                    result = await Session(
                        browser_factory=lambda: browser,
                        agent=agent,
                        verification=verification,
                        recorder=SlowRecorder(),
                    ).run(prepared_case(config(directory)))
                self.assertEqual(result.errors[-1].code, "finalization_timeout")
                self.assertEqual(result.status, "error")
                self.assertEqual(result.stop_reason, "execution_completed")
                self.assertFalse(
                    any(p.endswith("result.json") for p in result.artifact_paths)
                )
                trace = json.loads(
                    Path(directory, result.session_id, "trace.json").read_text()
                )
                diagnostics = [
                    event["attributes"]["error_id"]
                    for span in trace["spans"]
                    for event in span["events"]
                    if event["name"] == "diagnostic"
                ]
                self.assertIn(result.errors[-1].error_id, diagnostics)
                browser.close.assert_awaited_once()
            finally:
                release.set()
                await asyncio.to_thread(completed.wait, 2)
            self.assertEqual(result.status, "error")

    async def test_cancellation_during_final_save_is_recorded_and_propagated(self):
        import threading

        entered = threading.Event()
        release = threading.Event()

        class PausedRecord(SessionRecord):
            def finish(self, result, history):
                entered.set()
                release.wait(3)
                return super().finish(result, history)

        class PausedRecorder(Recorder):
            def begin(self, session_id, output_dir, *, suite_id=None):
                record = super().begin(session_id, output_dir, suite_id=suite_id)
                return PausedRecord(session_id, record.directory, suite_id)

        with tempfile.TemporaryDirectory() as directory:
            browser = AsyncMock()
            browser.open.return_value = BrowserState(
                Screenshot("screen-1", b"png", 1, 1), 1, 1
            )
            agent = AsyncMock()
            agent.execute.side_effect = submit_and_finish
            verification = AsyncMock()
            verification.evaluate.return_value = Verdict(
                "test-submission", "passed", []
            )
            task = asyncio.create_task(
                Session(
                    browser_factory=lambda: browser,
                    agent=agent,
                    verification=verification,
                    recorder=PausedRecorder(),
                ).run(prepared_case(config(directory)))
            )
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
            finally:
                release.set()
            with self.assertRaises(SessionCancelled) as cancellation:
                await task
            self.assertEqual(cancellation.exception.result.stop_reason, "cancelled")
            path = next(Path(directory).glob("*/result.json"))
            saved = json.loads(path.read_text())
            self.assertEqual(saved["stop_reason"], "cancelled")
            self.assertEqual(saved["status"], "error")
            self.assertEqual(saved["checkpoints"][0]["verdict"]["status"], "passed")
            events = [
                json.loads(line)
                for line in path.with_name("events.jsonl").read_text().splitlines()
            ]
            self.assertEqual([e["type"] for e in events].count("session_finished"), 1)
            self.assertEqual(events[-1]["type"], "session_cancelled")
