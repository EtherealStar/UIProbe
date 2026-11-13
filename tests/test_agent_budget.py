import unittest

from agent_support import PLAN, calls, run_actions


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_last_observation_precedes_disabling_all_tools(self):
        context, budget, submission, _, events, requests = await run_actions(
            [
                calls(PLAN),
                calls(
                    ("click", {"screenshot_id": "screen-1", "x": 20, "y": 20}),
                    ("replace_todo", {"items": []}),
                    ("click", {"screenshot_id": "screen-2", "x": 20, "y": 20}),
                ),
            ],
            "<button>Go</button>",
            max_actions=1,
        )
        self.assertEqual(budget.action_count, 1)
        self.assertEqual(context.browser_state.screenshot.screenshot_id, "screen-2")
        self.assertTrue(context.todo)
        self.assertEqual(submission.text, "Done")
        self.assertEqual(sum(e.get("status") == "rejected" for e in events), 2)
        self.assertIn("exhausted", str(requests[-1]))

    async def test_request_limit_does_not_fabricate_submission(self):
        from pydantic_ai.exceptions import UsageLimitExceeded

        with self.assertRaises(UsageLimitExceeded):
            await run_actions([calls(PLAN)], "<button>Go</button>", request_limit=1)

    async def test_continued_calls_after_exhaustion_are_bounded(self):
        from pydantic_ai.exceptions import UsageLimitExceeded

        with self.assertRaises(UsageLimitExceeded):
            await run_actions(
                [
                    calls(PLAN),
                    calls(("click", {"screenshot_id": "screen-1", "x": 20, "y": 20})),
                    calls(PLAN),
                    calls(PLAN),
                ],
                "<button>Go</button>",
                max_actions=1,
                request_limit=4,
            )

    async def test_expired_deadline_starts_no_capture(self):
        import asyncio
        from unittest.mock import AsyncMock

        from uiprobe.browser import Browser

        browser = Browser()
        page = AsyncMock()
        browser.page = page
        with self.assertRaises(TimeoutError):
            await browser.capture(asyncio.get_running_loop().time() - 1)
        page.screenshot.assert_not_awaited()
