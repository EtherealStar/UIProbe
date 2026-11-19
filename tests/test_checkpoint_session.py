import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agent_support import calls
from input_fixtures import config, prepared_case
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from uiprobe.agent import ExecutionAgent
from uiprobe.observation import BrowserState, Screenshot, Verdict
from uiprobe.recording import SubmissionRecord
from uiprobe.session import Session


class CheckpointSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_receipt_follows_persisted_evidence_and_disables_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            browser = AsyncMock()
            browser.open.return_value = BrowserState(
                Screenshot("screen-1", b"png", 1, 1), 1, 1
            )
            verifier = AsyncMock()

            async def evaluate(evidence, *args, **kwargs):
                return Verdict(evidence.submission_id, "passed", [])

            verifier.evaluate.side_effect = evaluate
            requests = 0

            def respond(messages, info):
                nonlocal requests
                requests += 1
                if requests == 1:
                    return calls(("submit_checkpoint", {"checkpoint_id": "unknown"}))
                if requests == 2:
                    self.assertFalse(list(Path(directory).glob("*/submissions/*")))
                    return calls(("submit_checkpoint", {"checkpoint_id": "home"}))
                self.assertEqual(info.function_tools, [])
                artifact = next(Path(directory).glob("*/submissions/*/input.json"))
                self.assertEqual(
                    json.loads(artifact.read_text())["screenshot_id"], "screen-1"
                )
                return ModelResponse(parts=[TextPart("Execution ended")])

            result = await Session(
                browser_factory=lambda: browser,
                agent=ExecutionAgent(FunctionModel(respond)),
                verification=verifier,
            ).run(prepared_case(config(directory)))
            self.assertEqual(result.status, "passed", result.errors)
            self.assertEqual(result.stop_reason, "execution_completed")
            self.assertEqual(result.action_count, 0)
            self.assertEqual(requests, 3)
            self.assertEqual(len(list(Path(directory).glob("*/screenshots/*.png"))), 1)
            self.assertEqual(result.checkpoints[0].state, "finished")
            self.assertEqual(result.checkpoints[0].screenshot_id, "screen-1")
            browser.capture.assert_not_awaited()
            verifier.evaluate.assert_awaited_once()

    async def test_final_text_without_submission_has_no_verdict(self):
        with tempfile.TemporaryDirectory() as directory:
            browser = AsyncMock()
            browser.open.return_value = BrowserState(
                Screenshot("screen-1", b"png", 1, 1), 1, 1
            )
            verifier = AsyncMock()
            result = await Session(
                browser_factory=lambda: browser,
                agent=ExecutionAgent(
                    FunctionModel(
                        lambda *_: ModelResponse(parts=[TextPart("Already done")])
                    )
                ),
                verification=verifier,
            ).run(prepared_case(config(directory)))
            self.assertEqual(result.status, "error")
            self.assertEqual(result.stop_reason, "execution_incomplete")
            assert result.execution_outcome is not None
            self.assertEqual(result.execution_outcome.text, "Already done")
            checkpoint = result.checkpoints[0]
            self.assertEqual(checkpoint.state, "not_submitted")
            self.assertIsNone(checkpoint.submission_id)
            self.assertIsNone(checkpoint.verdict)
            verifier.evaluate.assert_not_awaited()
            browser.close.assert_awaited_once()

    async def test_submission_record_failure_prevents_receipt_and_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            browser = AsyncMock()
            browser.open.return_value = BrowserState(
                Screenshot("screen-1", b"png", 1, 1), 1, 1
            )
            verifier = AsyncMock()
            with patch.object(
                SubmissionRecord, "save_input", side_effect=OSError("cannot write")
            ):
                result = await Session(
                    browser_factory=lambda: browser,
                    agent=ExecutionAgent(
                        FunctionModel(
                            lambda *_: calls(
                                ("submit_checkpoint", {"checkpoint_id": "home"})
                            )
                        )
                    ),
                    verification=verifier,
                ).run(prepared_case(config(directory)))
            self.assertEqual(result.status, "error")
            self.assertEqual(result.stop_reason, "recording_error")
            self.assertEqual(result.checkpoints[0].state, "not_submitted")
            self.assertIsNone(result.checkpoints[0].submission_id)
            self.assertIsNone(result.execution_outcome)
            self.assertEqual(result.errors[0].operation, "save_verification_input")
            self.assertEqual(result.errors[0].checkpoint_id, "home")
            self.assertIsNone(result.errors[0].submission_id)
            verifier.evaluate.assert_not_awaited()
