import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from agent_support import PLAN, calls
from checkpoint_fixtures import images, judge, prepare, submit
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models.function import FunctionModel

from uiprobe.agent import ExecutionAgent
from uiprobe.session import Session
from uiprobe.verification import Verification


class CheckpointBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_action_exhaustion_preserves_submission_and_case_request_limit(self):
        await self.run_with_limit(
            tool_call_limit=30,
            extra_calls=(PLAN,),
            expected_limit="request_limit",
            accepted=("first", "second"),
        )

    async def test_each_submission_counts_against_the_case_tool_limit(self):
        await self.run_with_limit(
            tool_call_limit=3,
            extra_calls=(),
            expected_limit="tool_calls_limit",
            accepted=("first",),
        )

    async def run_with_limit(
        self, *, tool_call_limit, extra_calls, expected_limit, accepted
    ):
        with tempfile.TemporaryDirectory() as directory:
            prepared = prepare(
                self,
                directory,
                "first",
                "second",
                max_actions=1,
                execution_request_limit=3,
                tool_call_limit=tool_call_limit,
                verification_request_limit=2,
                verification_retry_limit=1,
            )
            requests = []
            verification_requests = Counter()
            click = "click", {"screenshot_id": "screen-1", "x": 20, "y": 20}

            def execute(messages, info):
                requests.append(images(messages))
                if len(requests) == 1:
                    response = calls(PLAN)
                elif len(requests) == 2:
                    response = calls(click, *extra_calls, submit("first"))
                else:
                    self.assertEqual(
                        [tool.name for tool in info.function_tools],
                        ["submit_checkpoint"],
                    )
                    response = calls(submit("second"))
                for part in response.parts:
                    if isinstance(part, ToolCallPart):
                        part.tool_call_id = f"{len(requests)}-{part.tool_call_id}"
                return response

            def verify(messages, _):
                identifier = (
                    "first" if "Evidence for first" in str(messages) else "second"
                )
                verification_requests[identifier] += 1
                if verification_requests[identifier] == 1:
                    return judge("wrong-id")
                return judge(identifier)

            result = await Session(
                agent=ExecutionAgent(FunctionModel(execute)),
                verification=Verification(FunctionModel(verify)),
            ).run(prepared)
            self.assertEqual(result.status, "error")
            self.assertEqual(result.stop_reason, "execution_error")
            self.assertIsNone(result.execution_outcome)
            self.assertEqual(result.action_count, 1)
            self.assertEqual(result.last_screenshot_id, "screen-2")
            self.assertEqual(result.errors[0].code, "model_budget_exhausted")
            self.assertIn(expected_limit, result.errors[0].message)
            self.assertEqual(verification_requests, dict.fromkeys(accepted, 2))
            for checkpoint in result.checkpoints:
                if checkpoint.checkpoint_id in accepted:
                    self.assertEqual(checkpoint.screenshot_id, "screen-2")
                    assert checkpoint.verdict is not None
                    self.assertEqual(checkpoint.verdict.status, "passed")
                else:
                    self.assertEqual(checkpoint.state, "not_submitted")
            session = Path(directory, result.session_id)
            self.assertEqual(
                requests,
                [
                    [(session / "screenshots" / f"screen-{index}.png").read_bytes()]
                    for index in (1, 1, 2)
                ],
            )
            history = json.loads((session / "history.json").read_text())
            parts = [part for message in history for part in message["parts"]]
            tool_calls = [part for part in parts if part["part_kind"] == "tool-call"]
            tool_returns = [
                part
                for part in parts
                if part["part_kind"] in {"tool-return", "retry-prompt"}
                and part.get("tool_call_id")
            ]
            self.assertEqual(len(tool_calls), 4 + len(extra_calls))
            self.assertEqual(
                Counter(p["tool_call_id"] for p in tool_calls),
                {p["tool_call_id"]: 1 for p in tool_calls},
            )
            self.assertEqual(len(tool_returns), 2 + len(accepted) + len(extra_calls))
            received = [
                p["content"]
                for p in tool_returns
                if p["part_kind"] == "tool-return"
                and p["tool_name"] == "submit_checkpoint"
                and isinstance(p["content"], dict)
            ]
            self.assertEqual(
                tuple(p["checkpoint_id"] for p in received),
                accepted,
            )
