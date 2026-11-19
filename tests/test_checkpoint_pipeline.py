import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_support import PLAN, calls
from checkpoint_fixtures import images, judge, prepare, submit
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from trace_fixtures import CapturingExporter

from uiprobe.agent import ExecutionAgent
from uiprobe.browser import Browser
from uiprobe.observability import run_trace
from uiprobe.recording import SessionRecord
from uiprobe.session import Session
from uiprobe.verification import Verification


class CheckpointPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_execution_advances_while_verification_slots_are_occupied(self):
        for concurrency in (None, 2):
            with (
                self.subTest(concurrency=concurrency),
                tempfile.TemporaryDirectory() as directory,
            ):
                await self.run_pipeline(directory, concurrency)

    async def run_pipeline(self, directory, concurrency):
        first = "initial-stage"
        second = "clicked-stage"
        third = "reported-stage"
        settings = (
            {} if concurrency is None else {"verification_concurrency": concurrency}
        )
        prepared = prepare(
            self, directory, first, second, third, max_actions=2, **settings
        )
        closed = asyncio.Event()
        started_first = asyncio.Event()
        started_second = asyncio.Event()
        finished_third = asyncio.Event()
        started = []
        completed = []
        seen_images = {}
        requests = []

        class ObservedBrowser(Browser):
            async def close(self):
                await super().close()
                closed.set()

        append_event = SessionRecord.append

        def observe_event(record, event):
            append_event(record, event)
            if event["type"] == "verification_finished":
                completed.append(event["checkpoint_id"])
                if event["checkpoint_id"] == third:
                    finished_third.set()

        async def verify(messages, _):
            content = str(messages)
            (identifier,) = [
                key
                for key in (first, second, third)
                if f"Evidence for {key}" in content
            ]
            started.append(identifier)
            (seen_images[identifier],) = images(messages)
            if identifier == first:
                started_first.set()
                await (finished_third if concurrency == 2 else closed).wait()
            elif identifier == second:
                started_second.set()
                await closed.wait()
            return judge(identifier)

        async def execute(messages, info):
            requests.append(messages)
            self.assertEqual(len(images(messages)), 1)
            content = str(messages)
            tool_names = {tool.name for tool in info.function_tools}
            if len(requests) == 1:
                self.assertNotIn(second, content)
                self.assertNotIn(third, content)
                submit_tool = next(
                    tool
                    for tool in info.function_tools
                    if tool.name == "submit_checkpoint"
                )
                self.assertNotIn(second, repr(submit_tool))
                self.assertNotIn(third, repr(submit_tool))
                return calls(
                    PLAN,
                    submit(first),
                    ("click", {"screenshot_id": "screen-1", "x": 20, "y": 20}),
                    submit(first),
                )
            if len(requests) == 2:
                self.assertIn(f"Goal for {second}", content)
                self.assertNotIn(third, content)
                await started_first.wait()
                return calls(
                    ("click", {"screenshot_id": "screen-1", "x": 20, "y": 20}),
                    submit(second),
                )
            if len(requests) == 3:
                self.assertIn(f"Goal for {third}", content)
                if concurrency == 2:
                    await started_second.wait()
                return calls(submit(third), PLAN)
            self.assertEqual(len(requests), 4)
            self.assertEqual(tool_names, set())
            self.assertEqual(started, [first, second] if concurrency == 2 else [first])
            self.assertEqual(completed, [])
            self.assertNotIn("Observed evidence", content)
            return ModelResponse(parts=[TextPart("Execution finished")])

        exporter = CapturingExporter()
        with (
            patch.object(SessionRecord, "append", observe_event),
            run_trace(exporter),
        ):
            async with asyncio.timeout(10):
                result = await Session(
                    browser_factory=ObservedBrowser,
                    agent=ExecutionAgent(FunctionModel(execute)),
                    verification=Verification(FunctionModel(verify)),
                ).run(prepared)
        self.assertEqual(result.status, "passed", result.errors)
        self.assertEqual(result.action_count, 1)
        self.assertEqual(
            [item.checkpoint_id for item in result.checkpoints], [first, second, third]
        )
        self.assertEqual([item.state for item in result.checkpoints], ["finished"] * 3)
        self.assertEqual(
            [item.screenshot_id for item in result.checkpoints],
            ["screen-1", "screen-2", "screen-2"],
        )
        self.assertEqual(
            completed,
            [second, third, first] if concurrency == 2 else [first, second, third],
        )
        session = Path(directory, result.session_id)
        self.assertEqual(len(list(session.glob("screenshots/*.png"))), 2)
        for item in result.checkpoints:
            record = session / "submissions" / str(item.submission_id)
            saved = json.loads((record / "input.json").read_text())
            self.assertEqual(saved["checkpoint_id"], item.checkpoint_id)
            self.assertEqual(saved["screenshot_id"], item.screenshot_id)
            self.assertEqual(
                seen_images[item.checkpoint_id],
                (session / "screenshots" / f"{item.screenshot_id}.png").read_bytes(),
            )
        events = [
            json.loads(line)
            for line in (session / "events.jsonl").read_text().splitlines()
        ]
        self.assertEqual(
            [item["tool"] for item in events if item.get("status") == "rejected"],
            ["click", "submit_checkpoint", "replace_todo"],
        )

        self.assertEqual(events[-1]["type"], "session_finished")
        (session_span,) = [span for span in exporter.spans if span.name == "session"]
        verification_spans = [
            span for span in exporter.spans if span.name == "verification"
        ]
        self.assertEqual(len(verification_spans), 3)
        assert session_span.context is not None
        for span in verification_spans:
            assert span.parent is not None
            self.assertEqual(span.parent.span_id, session_span.context.span_id)

    async def test_failed_receipt_preserves_submission_and_keeps_next_stage_unpublished(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            prepared = prepare(self, directory, "submitted", "future")
            requests = 0

            def execute(messages, _):
                nonlocal requests
                requests += 1
                self.assertNotIn("Goal for future", str(messages))
                return calls(submit("submitted"))

            append_event = SessionRecord.append

            def fail_receipt(record, event):
                if (
                    event["type"] == "tool_finished"
                    and event.get("tool") == "submit_checkpoint"
                    and event.get("status") == "completed"
                ):
                    raise OSError("Cannot record receipt")
                append_event(record, event)

            with patch.object(SessionRecord, "append", fail_receipt):
                result = await Session(
                    agent=ExecutionAgent(FunctionModel(execute)),
                    verification=Verification(
                        FunctionModel(lambda *_: judge("submitted"))
                    ),
                ).run(prepared)
            self.assertEqual(requests, 1)
            self.assertEqual(result.stop_reason, "recording_error")
            first, future = result.checkpoints
            self.assertEqual(first.state, "finished")
            self.assertIsNotNone(first.submission_id)
            self.assertEqual(future.state, "not_reached")
            self.assertIsNone(future.verdict)
            (error,) = result.errors
            self.assertEqual(error.operation, "append_tool_result")
            self.assertEqual(error.checkpoint_id, first.checkpoint_id)
            self.assertEqual(error.submission_id, first.submission_id)
            session = Path(directory, result.session_id)
            (evidence,) = session.glob("submissions/*/input.json")
            self.assertEqual(
                json.loads(evidence.read_text())["submission_id"], first.submission_id
            )
