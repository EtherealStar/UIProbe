import asyncio
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from agent_support import calls
from checkpoint_fixtures import judge, prepare, submit
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from uiprobe.agent import ExecutionAgent
from uiprobe.browser import Browser
from uiprobe.session import Session
from uiprobe.verification import Verification


class CheckpointFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_frozen_evidence_survives_early_exit_and_execution_failure(self):
        for execution_fails in (False, True):
            with (
                self.subTest(execution_fails=execution_fails),
                tempfile.TemporaryDirectory() as directory,
            ):
                await self.run_incomplete_case(directory, execution_fails)

    async def run_incomplete_case(self, directory, execution_fails):
        prepared = prepare(self, directory, "submitted", "open", "future")
        started = asyncio.Event()
        closed = asyncio.Event()
        requests = 0

        class ObservedBrowser(Browser):
            async def close(self):
                await super().close()
                closed.set()
                if execution_fails:
                    raise OSError("Browser cleanup failed")

        async def execute(messages, _):
            nonlocal requests
            requests += 1
            if requests == 1:
                return calls(submit("submitted"))
            self.assertEqual(requests, 2)
            self.assertIn("Goal for open", str(messages))
            self.assertNotIn("Goal for future", str(messages))
            await started.wait()
            if execution_fails:
                raise ConnectionError("Execution connection lost")
            return ModelResponse(parts=[TextPart("Stopped early")])

        async def verify(messages, _):
            self.assertIn("Evidence for submitted", str(messages))
            started.set()
            await closed.wait()
            return judge("submitted")

        async with asyncio.timeout(10):
            result = await Session(
                browser_factory=ObservedBrowser,
                agent=ExecutionAgent(FunctionModel(execute)),
                verification=Verification(FunctionModel(verify)),
            ).run(prepared)
        self.assertEqual(result.status, "error")
        first, current, future = result.checkpoints
        self.assertEqual(first.state, "finished")
        assert first.verdict is not None
        self.assertEqual(first.verdict.status, "passed")
        self.assertEqual(current.state, "not_submitted")
        self.assertEqual(future.state, "not_reached")
        self.assertIsNone(current.verdict)
        self.assertIsNone(future.verdict)
        if execution_fails:
            self.assertEqual(result.stop_reason, "execution_error")
            self.assertIsNone(result.execution_outcome)
            execution_error, close_error = result.errors
            self.assertEqual(execution_error.checkpoint_id, "open")
            self.assertEqual(close_error.operation, "close_browser")
        else:
            self.assertEqual(result.stop_reason, "execution_incomplete")
            assert result.execution_outcome is not None
            self.assertEqual(result.execution_outcome.text, "Stopped early")
            self.assertEqual(result.errors, [])

    async def test_system_and_visual_faults_leave_sibling_verification_independent(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            identifiers = (
                "invalid-output",
                "counterevidence",
                "insufficient",
                "visible",
            )
            prepared = prepare(
                self, directory, *identifiers, verification_request_limit=2
            )
            invalid_seen = asyncio.Event()
            execution_count = 0
            verification_requests = Counter()

            async def execute(messages, info):
                nonlocal execution_count
                index = execution_count
                execution_count += 1
                self.assertNotIn("Observed evidence", str(messages))
                if index == len(identifiers):
                    self.assertEqual(info.function_tools, [])
                    return ModelResponse(parts=[TextPart("Execution finished")])
                if index == 1:
                    await invalid_seen.wait()
                return calls(submit(identifiers[index]))

            async def verify(messages, _):
                (identifier,) = [
                    key for key in identifiers if f"Evidence for {key}" in str(messages)
                ]
                verification_requests[identifier] += 1
                if identifier == "invalid-output":
                    if verification_requests[identifier] == 2:
                        invalid_seen.set()
                    return judge("unrelated")
                return judge(
                    identifier,
                    {
                        "counterevidence": "failed",
                        "insufficient": "error",
                        "visible": "passed",
                    }[identifier],
                )

            async with asyncio.timeout(10):
                result = await Session(
                    agent=ExecutionAgent(FunctionModel(execute)),
                    verification=Verification(FunctionModel(verify)),
                ).run(prepared)
            self.assertEqual(result.status, "error")
            self.assertEqual(result.stop_reason, "execution_completed")
            assert result.execution_outcome is not None
            self.assertEqual(result.execution_outcome.text, "Execution finished")
            self.assertEqual(
                verification_requests, dict(zip(identifiers, (2, 1, 1, 1)))
            )
            self.assertEqual(
                [item.state for item in result.checkpoints], ["finished"] * 4
            )
            self.assertEqual(
                [item.verdict.status for item in result.checkpoints if item.verdict],
                ["error", "failed", "error", "passed"],
            )
            (error,) = result.errors
            first = result.checkpoints[0]
            self.assertEqual(error.checkpoint_id, first.checkpoint_id)
            self.assertEqual(error.submission_id, first.submission_id)
            assert first.verdict is not None
            self.assertIn(error.error_id, first.verdict.assertions[0].reason)
            self.assertTrue(
                Path(
                    directory,
                    result.session_id,
                    "diagnostics",
                    f"{error.error_id}.json",
                ).is_file()
            )
