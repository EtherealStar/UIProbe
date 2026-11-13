import asyncio
import unittest

from agent_support import PLAN, calls, run_actions

from uiprobe.browser import Browser, BrowserRejected


class ObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_scroll_wait_and_strict_arguments(self):
        context, budget, _, _, events, _ = await run_actions(
            [
                calls(PLAN),
                calls(("scroll", {"delta_y": True})),
                calls(("scroll", {"delta_y": "200"})),
                calls(("wait", {"duration_ms": 0})),
                calls(("wait", {"duration_ms": 10001})),
                calls(("scroll", {"delta_y": 200})),
                calls(("scroll", {"delta_y": -100})),
                calls(("wait", {"duration_ms": 1})),
            ],
            '<div style="height:3000px;background:linear-gradient(red,blue)">Top</div>',
        )
        self.assertEqual(budget.action_count, 3)
        self.assertEqual(context.browser_state.screenshot.screenshot_id, "screen-4")
        self.assertEqual(len([e for e in events if e["type"] == "observation"]), 4)

    async def test_page_scroll_and_remaining_wait_preflight(self):
        browser = Browser()
        deadline = asyncio.get_running_loop().time() + 30
        claims = []
        try:
            await browser.open(
                'data:text/html,<div style="height:3000px">Top</div>', {}, deadline
            )
            assert browser.page is not None
            await browser.scroll(200, deadline, lambda: claims.append(1))
            self.assertEqual(await browser.page.evaluate("scrollY"), 200)
            await browser.scroll(-100, deadline, lambda: claims.append(1))
            self.assertEqual(await browser.page.evaluate("scrollY"), 100)
            with self.assertRaises(BrowserRejected):
                await browser.wait(
                    100,
                    asyncio.get_running_loop().time() + 0.01,
                    lambda: claims.append(1),
                )
            self.assertEqual(len(claims), 2)
        finally:
            await browser.close()
