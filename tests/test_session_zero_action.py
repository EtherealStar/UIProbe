import functools
import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path

import httpx2 as httpx
from openai import AsyncOpenAI
from test_session_input import case, config
from trace_fixtures import CapturingExporter

from uiprobe.agent import ExecutionAgent, model_from_client
from uiprobe.observability import run_trace
from uiprobe.session import Session
from uiprobe.verification import Verification


class ZeroActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_page_submission_verification_and_client_reuse(self):
        requests = []

        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            if any(
                t["function"]["name"] == "final_result" for t in body.get("tools", [])
            ):
                message = {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "verdict",
                            "type": "function",
                            "function": {
                                "name": body["tools"][0]["function"]["name"],
                                "arguments": json.dumps(
                                    {
                                        "results": [
                                            {
                                                "assertion_id": "home",
                                                "status": "passed",
                                                "reason": "Home title visible",
                                            }
                                        ]
                                    }
                                ),
                            },
                        }
                    ],
                }
            else:
                message = {
                    "role": "assistant",
                    "content": "Initial observation submitted",
                }
            return httpx.Response(
                200,
                json={
                    "id": "response",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "controlled",
                    "choices": [
                        {"index": 0, "message": message, "finish_reason": "stop"}
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "index.html").write_text("<h1>Home</h1>")
            server = http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                functools.partial(
                    http.server.SimpleHTTPRequestHandler, directory=directory
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                async with AsyncOpenAI(
                    api_key="test",
                    max_retries=0,
                    http_client=httpx.AsyncClient(
                        transport=httpx.MockTransport(respond)
                    ),
                ) as client:
                    model = model_from_client(client, "controlled")
                    session = Session(
                        agent=ExecutionAgent(model), verification=Verification(model)
                    )
                    cfg = config(directory)
                    cfg["entry_url"] = (
                        f"http://127.0.0.1:{server.server_port}/index.html"
                    )
                    for _ in range(2):
                        exporter = CapturingExporter()
                        with run_trace(exporter):
                            result = await session.run(json.dumps(case()), cfg)
                        self.assertEqual(result.status, "passed", result.errors)
                        self.assertEqual(result.action_count, 0)
                        self.assertTrue(
                            (Path(directory, result.session_id) / "trace.json").exists()
                        )
                        self.assertIsNotNone(result.submission)
                        self.assertFalse(client.is_closed())
                        run = Path(directory, result.session_id)
                        png = (run / "screenshots/screen-1.png").read_bytes()
                        self.assertTrue(png.startswith(b"\x89PNG"))
                        self.assertEqual(int.from_bytes(png[16:20], "big"), 1280)
                        trace = json.loads((run / "trace.json").read_text())
                        self.assertEqual(
                            len(
                                {span["context"]["trace_id"] for span in trace["spans"]}
                            ),
                            1,
                        )
                        names = [span["name"] for span in trace["spans"]]
                        self.assertIn("application", names)
                        self.assertIn("verification", names)
                        self.assertIn("browser.close", names)
                        model_spans = [
                            span
                            for span in trace["spans"]
                            if span["attributes"].get("gen_ai.operation.name") == "chat"
                        ]
                        self.assertEqual(len(model_spans), 2)
                        self.assertIn(
                            "Initial observation submitted", json.dumps(trace)
                        )
                        payload = b"".join(exporter.payloads)
                        self.assertIn(b"Initial observation submitted", payload)
                        self.assertNotIn(b"data:image", payload)
                        self.assertNotIn(b"iVBORw0KGgo", payload)
                        self.assertNotIn(png, payload)
                        self.assertIn(
                            "screen-1", (run / "execution-requests.jsonl").read_text()
                        )
                        history = (run / "history.json").read_text()
                        self.assertIn("screen-1", history)
                        self.assertNotIn("secret-value", history)
                        self.assertNotIn("data:image", history)
                    self.assertEqual(len(requests), 4)
                    self.assertNotIn("secret-value", repr(requests))
                    self.assertNotIn("Login", repr(requests[1]))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    async def test_cancellation_saves_result_and_releases_browser(self):
        import asyncio
        from unittest.mock import AsyncMock

        from uiprobe.observation import BrowserState, Screenshot

        with tempfile.TemporaryDirectory() as directory:
            browser = AsyncMock()
            browser.open.return_value = BrowserState(
                Screenshot("s", b"png", 1, 1), 1, 1
            )
            agent = AsyncMock()
            agent.execute.side_effect = asyncio.CancelledError
            session = Session(
                browser_factory=lambda: browser, agent=agent, verification=AsyncMock()
            )
            with self.assertRaises(asyncio.CancelledError):
                await session.run(json.dumps(case()), config(directory))
            browser.close.assert_awaited_once()
            result = json.loads(next(Path(directory).glob("*/result.json")).read_text())
            self.assertEqual(result["stop_reason"], "cancelled")
            self.assertEqual(result["status"], "error")
