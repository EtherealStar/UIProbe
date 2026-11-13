import unittest

from agent_support import PLAN, calls, run_actions


class LoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_focus_rejections_and_reference_login(self):
        context, budget, _, content, events, requests = await run_actions(
            [
                calls(PLAN),
                calls(("fill_value", {"ref": "password"})),
                calls(("click", {"screenshot_id": "screen-1", "x": 40, "y": 20})),
                calls(("fill_value", {"ref": "missing"})),
                calls(("fill_value", {"ref": "username"})),
                calls(("click", {"screenshot_id": "screen-3", "x": 40, "y": 60})),
                calls(("fill_value", {"ref": "password"})),
                calls(("click", {"screenshot_id": "screen-5", "x": 40, "y": 100})),
            ],
            """<input id="user" value="old" style="position:absolute;top:10px;left:10px">
        <input id="pass" type="password" style="position:absolute;top:50px;left:10px">
        <button style="position:absolute;top:90px;left:10px" onclick="if(document.querySelector('#user').value==='Alice' && document.querySelector('#pass').value==='secret-password') document.body.innerHTML='<h1>Home</h1>'">Login</button>""",
            values={"username": "Alice", "password": "secret-password"},
        )
        self.assertIn("<h1>Home</h1>", content)
        self.assertEqual(budget.action_count, 5)
        self.assertEqual(context.browser_state.screenshot.screenshot_id, "screen-6")
        self.assertNotIn("secret-password", repr(events))
        # Binary screenshots show the real page; textual model content carries references only.
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        texts = [
            p.content
            for request in requests
            for m in request
            if isinstance(m, ModelRequest)
            for p in m.parts
            if isinstance(p, UserPromptPart) and isinstance(p.content, str)
        ]
        self.assertNotIn("secret-password", repr(texts))
