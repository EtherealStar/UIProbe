import tempfile
import time
import unittest

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from uiprobe.case_input import TestCase
from uiprobe.observation import Screenshot
from uiprobe.recording import Recorder
from uiprobe.verification import Verification


class VerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_isolated_failure_without_retry(self):
        requests = []

        async def respond(messages, info):
            requests.append(messages)
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "results": [
                                {
                                    "assertion_id": "home",
                                    "status": "failed",
                                    "reason": "Login visible",
                                }
                            ]
                        },
                    )
                ]
            )

        with tempfile.TemporaryDirectory() as directory:
            record = Recorder().begin("test", directory)
            screenshot = Screenshot("screen-1", b"png", 10, 10)
            record.save_screenshot(screenshot)
            case = TestCase.model_validate(
                {
                    "execution": {"goal": "PRIVATE EXECUTION", "instructions": []},
                    "assertions": [{"id": "home", "expected": "Home visible"}],
                }
            )
            verdict = await Verification(FunctionModel(respond)).evaluate(
                case,
                screenshot,
                time.monotonic() + 10,
                record=record,
                request_limit=3,
                retry_limit=2,
            )
            self.assertEqual(verdict.status, "failed")
            self.assertEqual(verdict.assertions[0].screenshot_id, "screen-1")
            self.assertEqual(len(requests), 1)
            self.assertNotIn("PRIVATE EXECUTION", repr(requests))
            self.assertIn("Home visible", repr(requests))
            self.assertIn("BinaryContent", repr(requests))

    async def test_mapping_correction_synthesis_and_invalid_outputs(self):
        for statuses, expected in [
            (["passed", "passed"], "passed"),
            (["passed", "error"], "error"),
            (["failed", "error"], "failed"),
        ]:
            with (
                self.subTest(statuses=statuses),
                tempfile.TemporaryDirectory() as directory,
            ):
                requests = []

                async def respond(messages, info):
                    requests.append(messages)
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                info.output_tools[0].name,
                                {
                                    "results": [
                                        {
                                            "assertion_id": identifier,
                                            "status": status,
                                            "reason": "Visible evidence",
                                        }
                                        for identifier, status in zip(
                                            ["one", "two"], statuses
                                        )
                                    ]
                                },
                            )
                        ]
                    )

                case = TestCase.model_validate(
                    {
                        "execution": {"goal": "private", "instructions": []},
                        "assertions": [
                            {"id": i, "expected": i} for i in ["one", "two"]
                        ],
                    }
                )
                record = Recorder().begin("test", directory)
                result = await Verification(FunctionModel(respond)).evaluate(
                    case,
                    Screenshot("s", b"png", 1, 1),
                    time.monotonic() + 10,
                    record=record,
                    request_limit=3,
                    retry_limit=1,
                )
                self.assertEqual(result.status, expected)
                self.assertEqual(len(requests), 1)

    async def test_invalid_mapping_and_reason_exhaustion_and_correction(self):
        for invalid in [
            [],
            [{"assertion_id": "unknown", "status": "passed", "reason": "ok"}],
            [{"assertion_id": "home", "status": "passed", "reason": " "}],
            [{"assertion_id": "home", "status": "invalid", "reason": "ok"}],
            [{"assertion_id": "home", "status": "passed", "reason": "ok"}] * 2,
        ]:
            for correct in [False, True]:
                with (
                    self.subTest(invalid=invalid, correct=correct),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    requests = []

                    async def respond(messages, info):
                        requests.append(messages)
                        items = (
                            [
                                {
                                    "assertion_id": "home",
                                    "status": "passed",
                                    "reason": "Home visible",
                                }
                            ]
                            if correct and len(requests) > 1
                            else invalid
                        )
                        return ModelResponse(
                            parts=[
                                ToolCallPart(
                                    info.output_tools[0].name, {"results": items}
                                )
                            ]
                        )

                    case = TestCase.model_validate(
                        {
                            "execution": {"goal": "private", "instructions": []},
                            "assertions": [{"id": "home", "expected": "Home"}],
                        }
                    )
                    result = await Verification(FunctionModel(respond)).evaluate(
                        case,
                        Screenshot("s", b"png", 1, 1),
                        time.monotonic() + 10,
                        record=Recorder().begin("test", directory),
                        request_limit=2,
                        retry_limit=1,
                    )
                    self.assertEqual(result.status, "passed" if correct else "error")
                    self.assertEqual(len(requests), 2)
                    self.assertEqual(len(result.assertions), 1)
                    self.assertNotIn("private", repr(requests))

    async def test_missing_evidence_expired_deadline_and_transport_failure(self):
        for mode in ["missing", "expired", "transport", "refusal"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                requests = []

                async def respond(messages, info):
                    requests.append(messages)
                    if mode == "transport":
                        raise ConnectionError("private transport details")
                    from pydantic_ai.messages import TextPart

                    return ModelResponse(parts=[TextPart("Cannot judge")])

                case = TestCase.model_validate(
                    {
                        "execution": {"goal": "private", "instructions": []},
                        "assertions": [{"id": "home", "expected": "Home"}],
                    }
                )
                result = await Verification(FunctionModel(respond)).evaluate(
                    case,
                    None if mode == "missing" else Screenshot("s", b"png", 1, 1),
                    time.monotonic() + (-1 if mode == "expired" else 10),
                    record=Recorder().begin("test", directory),
                    request_limit=1,
                    retry_limit=1,
                )
                self.assertEqual(result.status, "error")
                self.assertNotIn("private", repr(result))
                self.assertEqual(
                    len(requests), 0 if mode in ["missing", "expired"] else 1
                )

    async def test_recording_failure_propagates(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:

            async def respond(messages, info):
                return ModelResponse(parts=[])

            case = TestCase.model_validate(
                {
                    "execution": {"goal": "private", "instructions": []},
                    "assertions": [{"id": "home", "expected": "Home"}],
                }
            )
            record = Recorder().begin("test", directory)
            with patch.object(
                record, "save_messages", side_effect=OSError("disk unavailable")
            ):
                with self.assertRaises(OSError):
                    await Verification(FunctionModel(respond)).evaluate(
                        case,
                        Screenshot("s", b"png", 1, 1),
                        time.monotonic() + 10,
                        record=record,
                        request_limit=1,
                        retry_limit=1,
                    )
