import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from agent_support import calls
from input_fixtures import case, config
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from uiprobe.model_service import ModelServiceConfig
from uiprobe.observation import BrowserState, Screenshot
from uiprobe.recording import SubmissionRecord
from uiprobe.suite_runner import SuiteRunner


class AsyncRecordingFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_write_failure_stops_blocked_execution_and_suite(self):
        with tempfile.TemporaryDirectory() as directory:
            browser = AsyncMock()
            browser.open.return_value = BrowserState(
                Screenshot("screen-1", b"png", 1, 1), 1, 1
            )
            browser_factory = Mock(return_value=browser)
            service = AsyncMock()
            service.config = ModelServiceConfig(
                "http://controlled/v1", "test", "controlled"
            )
            executing = asyncio.Event()
            execution_cancelled = asyncio.Event()
            execution_requests = 0
            first_finished = asyncio.Event()
            original_append = SubmissionRecord.append

            def append(record, event):
                original_append(record, event)
                if (
                    record.submission.checkpoint_id == "home"
                    and event["type"] == "verification_finished"
                ):
                    first_finished.set()
                if (
                    record.submission.checkpoint_id == "second"
                    and event["type"] == "verification_finished"
                ):
                    raise OSError("cannot save verification completion")

            async def respond(messages, info):
                nonlocal execution_requests
                if info.output_tools:
                    self.assertNotIn("queued-assertion", repr(messages))
                    if "second-assertion" in repr(messages):
                        await executing.wait()
                        assertion_id = "second-assertion"
                    else:
                        assertion_id = "home"
                    return calls(
                        (
                            info.output_tools[0].name,
                            {
                                "results": [
                                    {
                                        "assertion_id": assertion_id,
                                        "status": "passed",
                                        "reason": "Home visible",
                                    }
                                ]
                            },
                        )
                    )
                execution_requests += 1
                if execution_requests <= 3:
                    identifier = ("home", "second", "queued")[execution_requests - 1]
                    if execution_requests == 2:
                        await first_finished.wait()
                    return calls(("submit_checkpoint", {"checkpoint_id": identifier}))
                executing.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    execution_cancelled.set()
                    raise
                return ModelResponse(parts=[TextPart("Unexpected")])

            first = case()
            first["checkpoints"].extend(
                {
                    "id": identifier,
                    "execution": {"goal": "Stay here", "instructions": []},
                    "assertions": [
                        {"id": f"{identifier}-assertion", "expected": "Home visible"}
                    ],
                }
                for identifier in ("second", "queued")
            )
            with (
                patch(
                    "uiprobe.suite_runner.model_from_client",
                    return_value=FunctionModel(respond),
                ),
                patch.object(SubmissionRecord, "append", append),
            ):
                result = await asyncio.wait_for(
                    SuiteRunner(lambda: service, browser_factory=browser_factory).run(
                        json.dumps(
                            {
                                "cases": [
                                    first,
                                    {"id": "invalid"},
                                    {**case(), "id": "later"},
                                ]
                            }
                        ),
                        {"defaults": config(directory)},
                    ),
                    2,
                )

            self.assertTrue(execution_cancelled.is_set())
            self.assertEqual(execution_requests, 4)
            self.assertEqual(result.stop_reason, "recording_error")
            self.assertEqual(
                [item.status for item in result.cases], ["error", "error", "not_run"]
            )
            session = result.cases[0].session_result
            assert session is not None
            self.assertEqual(session.stop_reason, "recording_error")
            self.assertEqual(
                [item.state for item in session.checkpoints],
                ["finished", "finished", "finished"],
            )
            self.assertEqual(
                [
                    item.verdict.status if item.verdict else None
                    for item in session.checkpoints
                ],
                ["passed", "passed", "error"],
            )
            self.assertEqual(len(session.errors), 1)
            error = session.errors[0]
            self.assertEqual(error.operation, "append_verification_finished")
            queued = session.checkpoints[2].verdict
            assert queued is not None
            self.assertIn(error.error_id, queued.assertions[0].reason)
            diagnostic = json.loads(
                Path(
                    directory,
                    session.session_id,
                    "diagnostics",
                    f"{error.error_id}.json",
                ).read_text()
            )
            self.assertEqual(
                diagnostic["submission_id"], session.checkpoints[1].submission_id
            )
            self.assertEqual(diagnostic["screenshot_id"], "screen-1")
            browser_factory.assert_called_once()
            browser.close.assert_awaited_once()
            service.close.assert_awaited_once()

    async def test_concurrent_external_cancel_retains_recording_stop_reason(self):
        from input_fixtures import prepared_case

        from uiprobe.observation import Verdict
        from uiprobe.session import Session, SessionCancelled

        with tempfile.TemporaryDirectory() as directory:
            screenshot = Screenshot("screen-1", b"png", 1, 1)
            browser = AsyncMock()
            browser.open.return_value = BrowserState(screenshot, 1, 1)
            agent = AsyncMock()
            verification = AsyncMock()

            async def execute(context, *, accept_checkpoint, **kwargs):
                accept_checkpoint("home", screenshot)
                await asyncio.Future()

            async def evaluate(submission, *args, **kwargs):
                return Verdict(submission.submission_id, "passed", [])

            def append(record, event):
                if event["type"] == "verification_finished":
                    task.cancel()
                    raise OSError("verification completion unavailable")
                original_append(record, event)

            agent.execute.side_effect = execute
            verification.evaluate.side_effect = evaluate
            original_append = SubmissionRecord.append
            with patch.object(SubmissionRecord, "append", append):
                task = asyncio.create_task(
                    Session(
                        browser_factory=lambda: browser,
                        agent=agent,
                        verification=verification,
                    ).run(prepared_case(config(directory)))
                )
                with self.assertRaises(SessionCancelled) as interrupted:
                    await asyncio.wait_for(task, 2)

            result = interrupted.exception.result
            self.assertEqual(result.stop_reason, "recording_error")
            self.assertEqual(
                [error.operation for error in result.errors],
                ["append_verification_finished"],
            )
            verdict = result.checkpoints[0].verdict
            assert verdict is not None
            self.assertEqual(verdict.status, "passed")
            browser.close.assert_awaited_once()
