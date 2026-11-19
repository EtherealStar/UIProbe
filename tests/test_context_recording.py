import unittest

from agent_support import PLAN, calls, run_actions, unexpected_submission
from pydantic_ai import BinaryContent
from pydantic_ai.messages import ModelRequest, ToolReturnPart, UserPromptPart


def images(messages):
    return [
        item.identifier
        for m in messages
        if isinstance(m, ModelRequest)
        for p in m.parts
        if isinstance(p, UserPromptPart) and isinstance(p.content, list)
        for item in p.content
        if isinstance(item, BinaryContent)
    ]


class RecordingTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_observations_keep_history_and_send_latest_image(self):
        context, _, _, _, events, requests = await run_actions(
            [
                calls(PLAN),
                calls(("click", {"screenshot_id": "screen-1", "x": 20, "y": 20})),
                calls(("click", {"screenshot_id": "screen-2", "x": 20, "y": 20})),
            ],
            '<button onclick="this.textContent += 1">Go</button>',
        )
        self.assertEqual(
            [images(r) for r in requests],
            [["screen-1"], ["screen-1"], ["screen-2"], ["screen-3"]],
        )
        self.assertEqual(
            set(images(context.history)), {"screen-1", "screen-2", "screen-3"}
        )
        self.assertEqual(
            [e["screenshot_id"] for e in events if e["type"] == "observation"],
            ["screen-1", "screen-2", "screen-3"],
        )
        self.assertEqual(
            sum(
                isinstance(p, ToolReturnPart) for m in context.history for p in m.parts
            ),
            3,
        )

    async def test_request_exhaustion_keeps_tool_return_in_saved_history(self):
        import asyncio
        import json
        import tempfile

        from input_fixtures import case
        from pydantic_ai.exceptions import UsageLimitExceeded
        from pydantic_ai.models.function import FunctionModel

        from uiprobe.actions import RunBudget
        from uiprobe.agent import Context, ExecutionAgent
        from uiprobe.browser import Browser
        from uiprobe.case_input import TestCase
        from uiprobe.observation import BrowserState, Screenshot
        from uiprobe.recording import Recorder

        with tempfile.TemporaryDirectory() as directory:
            record = Recorder().begin("test", directory)
            state = BrowserState(Screenshot("screen-1", b"png", 1, 1), 1, 1)
            record.save_screenshot(state.screenshot)
            context = Context(TestCase.model_validate(case()).checkpoints[0], [], state)
            deadline = asyncio.get_running_loop().time() + 10
            with self.assertRaises(UsageLimitExceeded):
                await ExecutionAgent(
                    FunctionModel(lambda messages, info: calls(PLAN))
                ).execute(
                    context,
                    record=record,
                    deadline_at=deadline,
                    request_limit=1,
                    retry_limit=1,
                    browser=Browser(),
                    budget=RunBudget(deadline, 1),
                    tool_call_limit=5,
                    accept_checkpoint=unexpected_submission,
                )
            history = json.loads((record.directory / "history.json").read_text())
            self.assertEqual(
                sum(
                    p["part_kind"] == "tool-return" for m in history for p in m["parts"]
                ),
                1,
            )
