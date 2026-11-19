"""Independent verification materials under interleaved model calls."""

import asyncio
import base64
import json
import tempfile
import unittest

from pydantic_ai.messages import (
    BinaryContent,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel
from trace_fixtures import CapturingExporter

from uiprobe.case_input import Assertion
from uiprobe.observability import bind_record, run_trace
from uiprobe.observation import CheckpointSubmission, Screenshot
from uiprobe.recording import Recorder
from uiprobe.verification import Verification


class SubmissionRecordTests(unittest.IsolatedAsyncioTestCase):
    async def test_interleaved_verifications_keep_evidence_and_trace_ownership(self):
        first_entered, release_first = asyncio.Event(), asyncio.Event()
        completions = []
        requests: dict[str, list[bytes]] = {"first": [], "second": []}

        async def respond(messages, info):
            prompt = next(
                part.content
                for message in messages
                for part in message.parts
                if isinstance(part, UserPromptPart) and isinstance(part.content, list)
            )
            text, image = prompt
            assert isinstance(text, str) and isinstance(image, BinaryContent)
            assertion = json.loads(text)["assertions"][0]
            name = assertion["id"]
            self.assertEqual(assertion["expected"], f"{name} evidence")
            requests[name].append(image.data)
            if name == "first":
                if len(requests[name]) > 1:
                    raise ConnectionError("first transport fault")
                first_entered.set()
                await release_first.wait()
                judgments = []
            else:
                judgments = [
                    {
                        "assertion_id": name,
                        "status": "passed",
                        "reason": "second judged",
                    }
                ]
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"results": judgments})]
            )

        verification = Verification(FunctionModel(respond))
        exporter = CapturingExporter()
        with tempfile.TemporaryDirectory() as directory:
            session = Recorder().begin("session", directory)
            submissions = []
            for index, name in enumerate(("first", "second"), 1):
                assertions = [Assertion(id=name, expected=f"{name} evidence")]
                screenshot = Screenshot(
                    f"screen-{index}", f"png-bytes-{name}".encode(), 1, 1
                )
                session.save_screenshot(screenshot)
                evidence = CheckpointSubmission(
                    f"submission-{name}",
                    session.session_id,
                    f"step-{name}",
                    tuple(assertions),
                    screenshot,
                )
                assertions.clear()
                submissions.append((evidence, session.begin_submission(evidence)))

            deadline = asyncio.get_running_loop().time() + 10

            async def evaluate(evidence, record):
                verdict = await verification.evaluate(
                    evidence, deadline, record=record, request_limit=2, retry_limit=1
                )
                completions.append(verdict.submission_id)
                return verdict

            with run_trace(exporter):
                bind_record(session)
                async with asyncio.timeout_at(deadline), asyncio.TaskGroup() as group:
                    first = group.create_task(evaluate(*submissions[0]))
                    await first_entered.wait()
                    second = group.create_task(evaluate(*submissions[1]))
                    passed = await second
                    self.assertFalse(first.done())
                    release_first.set()
                    failed = await first

            self.assertEqual(completions, ["submission-second", "submission-first"])
            self.assertEqual((failed.status, passed.status), ("error", "passed"))
            trace = json.loads((session.directory / "trace.json").read_text())
            spans = {
                span["attributes"]["submission_id"]: span
                for span in trace["spans"]
                if span["name"] == "verification"
            }
            self.assertEqual(set(spans), set(completions))
            self.assertEqual(len({span["parent_id"] for span in spans.values()}), 1)
            payload = b"".join(exporter.payloads)
            self.assertNotIn(b"data:image", payload)
            self.assertEqual(
                sorted(p.name for p in session.directory.rglob("*.png")),
                ["screen-1.png", "screen-2.png"],
            )
            for (evidence, _), verdict, name, other in zip(
                submissions, (failed, passed), ("first", "second"), ("second", "first")
            ):
                with self.subTest(submission=name):
                    assert evidence.screenshot is not None
                    screenshot = evidence.screenshot
                    self.assertEqual(
                        requests[name], [screenshot.png] * (2 if name == "first" else 1)
                    )
                    self.assertEqual(
                        verdict.assertions[0].screenshot_id, screenshot.screenshot_id
                    )
                    path = session.directory / "submissions" / verdict.submission_id
                    saved_input = json.loads((path / "input.json").read_text())
                    association = {
                        "session_id": session.session_id,
                        "checkpoint_id": f"step-{name}",
                        "submission_id": f"submission-{name}",
                        "screenshot_id": screenshot.screenshot_id,
                    }
                    self.assertEqual(
                        saved_input,
                        {
                            **association,
                            "assertions": [
                                {"id": name, "expected": f"{name} evidence"}
                            ],
                        },
                    )
                    self.assertEqual(
                        (
                            session.directory
                            / "screenshots"
                            / f"{screenshot.screenshot_id}.png"
                        ).read_bytes(),
                        screenshot.png,
                    )
                    history = (path / "history.json").read_text()
                    views = (path / "requests.jsonl").read_text().splitlines()
                    self.assertEqual(len(views), len(requests[name]))
                    for material in (history, *views):
                        self.assertIn(f"{name} evidence", material)
                        self.assertIn(screenshot.screenshot_id, material)
                        self.assertNotIn(f"{other} evidence", material)
                        self.assertNotIn("png-bytes-", material)
                    span = spans[verdict.submission_id]
                    self.assertEqual(span["attributes"], association)
                    self.assertIn(verdict.submission_id.encode(), payload)
                    self.assertNotIn(screenshot.png, payload)
                    self.assertNotIn(base64.b64encode(screenshot.png), payload)

            self.assertIn(
                "Return exactly one result for every supplied assertion ID.",
                (submissions[0][1].directory / "history.json").read_text(),
            )
            self.assertIn(
                "second judged",
                (submissions[1][1].directory / "history.json").read_text(),
            )
            (diagnostic_path,) = (session.directory / "diagnostics").glob("*.json")
            diagnostic = json.loads(diagnostic_path.read_text())
            self.assertEqual(diagnostic["submission_id"], failed.submission_id)
            self.assertEqual(diagnostic["screenshot_id"], "screen-1")
            self.assertEqual(diagnostic["checkpoint_id"], "step-first")
            self.assertIn(diagnostic["error_id"], failed.assertions[0].reason)
            self.assertIn(
                diagnostic["error_id"],
                json.dumps(spans[failed.submission_id]["events"]),
            )
            self.assertEqual(spans[passed.submission_id]["events"], [])
            events = [
                json.loads(line)
                for line in (session.directory / "events.jsonl")
                .read_text()
                .splitlines()
            ]
            (failure_event,) = [
                event for event in events if event["type"] == "verification_error"
            ]
            self.assertEqual(failure_event["error_id"], diagnostic["error_id"])
            self.assertEqual(failure_event["submission_id"], failed.submission_id)
