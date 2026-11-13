import asyncio
import unittest

from uiprobe.browser import Browser, BrowserRejected


class ClickTests(unittest.IsolatedAsyncioTestCase):
    async def test_scaled_click_and_preflight(self):
        browser = Browser(
            viewport_width=400, viewport_height=300, device_scale_factor=2
        )
        deadline = asyncio.get_running_loop().time() + 30
        count = []
        try:
            state = await browser.open(
                'data:text/html,<button style="position:absolute;left:100px;top:50px" onclick="document.title=\'clicked\'">Go</button>',
                {},
                deadline,
            )
            self.assertEqual(state.screenshot.image_width, 800)
            await browser.click(
                state.screenshot.screenshot_id,
                220,
                120,
                deadline,
                lambda: count.append(1),
            )
            assert browser.page is not None
            self.assertEqual(await browser.page.title(), "clicked")
            await browser.capture(deadline)
            with self.assertRaises(BrowserRejected):
                await browser.click(
                    state.screenshot.screenshot_id,
                    220,
                    120,
                    deadline,
                    lambda: count.append(1),
                )
            self.assertEqual(count, [1])
        finally:
            await browser.close()

    async def test_plan_barrier_stale_click_and_event_pairs(self):
        from agent_support import PLAN, calls, run_actions

        context, budget, submission, content, events, requests = await run_actions(
            [
                calls(("click", {"screenshot_id": "screen-1", "x": 30, "y": 20})),
                calls(
                    PLAN,
                    ("click", {"screenshot_id": "screen-1", "x": 30, "y": 20}),
                    ("click", {"screenshot_id": "screen-1", "x": 30, "y": 20}),
                ),
                calls(("replace_todo", {"items": []})),
            ],
            "<button onclick=\"this.textContent='Clicked'\">Go</button>",
        )
        self.assertEqual(budget.action_count, 1)
        self.assertIn("Clicked", content)
        self.assertTrue(context.plan_created)
        self.assertEqual(context.todo, [])
        self.assertEqual(context.browser_state.screenshot.screenshot_id, "screen-2")
        starts = [e["call_id"] for e in events if e["type"] == "tool_started"]
        ends = [e["call_id"] for e in events if e["type"] == "tool_finished"]
        self.assertCountEqual(starts, ends)

    async def test_budget_refusal_and_dispatched_failure(self):
        from unittest.mock import AsyncMock, patch

        from pydantic_ai import ModelRetry

        from uiprobe.actions import RunBudget

        browser = Browser()
        deadline = asyncio.get_running_loop().time() + 30
        try:
            state = await browser.open(
                "data:text/html,<button>Go</button>", {}, deadline
            )
            budget = RunBudget(deadline, 0)
            with self.assertRaises(ModelRetry):
                await browser.click(
                    state.screenshot.screenshot_id,
                    20,
                    20,
                    deadline,
                    budget.claim_browser_action,
                )
            self.assertEqual(budget.action_count, 0)
            budget.max_actions = 1
            assert browser.page is not None
            with patch.object(
                browser.page.mouse,
                "click",
                new=AsyncMock(side_effect=RuntimeError("dispatch failed")),
            ) as dispatch:
                with self.assertRaises(RuntimeError):
                    await browser.click(
                        state.screenshot.screenshot_id,
                        20,
                        20,
                        deadline,
                        budget.claim_browser_action,
                    )
                dispatch.assert_awaited_once()
            self.assertEqual(budget.action_count, 1)
        finally:
            await browser.close()

    async def test_invalid_plan_and_coordinate_parameters_do_not_dispatch(self):
        from agent_support import PLAN, calls, run_actions

        _, budget, _, _, _, _ = await run_actions(
            [
                calls(
                    (
                        "replace_todo",
                        {"items": [{"description": " ", "status": "pending"}]},
                    )
                ),
                calls(
                    (
                        "replace_todo",
                        {
                            "items": [
                                {"description": "a", "status": "in_progress"},
                                {"description": "b", "status": "in_progress"},
                            ]
                        },
                    )
                ),
                calls(PLAN),
                calls(("click", {"screenshot_id": "screen-1", "x": True, "y": 20})),
                calls(("click", {"screenshot_id": "screen-1", "x": 1280, "y": 20})),
                calls(
                    (
                        "click",
                        {"screenshot_id": "screen-1", "x": 20, "y": 20, "extra": 1},
                    )
                ),
            ],
            "<button>Go</button>",
        )
        self.assertEqual(budget.action_count, 0)
