"""Exercise the application assembly with Chromium and controlled SDK responses."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx2 as httpx
from stream_fixtures import streamed_completion
from trace_fixtures import CapturingExporter

from uiprobe.__main__ import main, run_application
from uiprobe.browser import Browser
from uiprobe.model_service import ModelService, ModelServiceConfig
from uiprobe.observability import run_trace
from uiprobe.session import SessionResult


class ApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_and_independent_verdict_statuses(self):
        import functools
        import http.server
        import threading

        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "page.html").write_text(
                """<input style="position:absolute;left:10px;top:10px"><input type="password" style="position:absolute;left:10px;top:50px"><button style="position:absolute;left:10px;top:90px" onclick="if(document.querySelectorAll('input')[0].value==='admin' && document.querySelectorAll('input')[1].value==='123456')document.body.innerHTML='<h1>Home</h1>'">Login</button>"""
            )
            server = http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                functools.partial(
                    http.server.SimpleHTTPRequestHandler, directory=directory
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for status in ("passed", "failed", "error"):
                    with self.subTest(status=status):
                        steps = iter(
                            [
                                (
                                    "replace_todo",
                                    {
                                        "items": [
                                            {
                                                "description": "Login",
                                                "status": "in_progress",
                                            }
                                        ]
                                    },
                                ),
                                (
                                    "click",
                                    {"screenshot_id": "screen-1", "x": 40, "y": 20},
                                ),
                                ("fill_value", {"ref": "username"}),
                                (
                                    "click",
                                    {"screenshot_id": "screen-3", "x": 40, "y": 60},
                                ),
                                ("fill_value", {"ref": "password"}),
                                (
                                    "click",
                                    {"screenshot_id": "screen-5", "x": 40, "y": 100},
                                ),
                            ]
                        )
                        requests = []

                        def respond(request):
                            body = json.loads(request.content)
                            requests.append(body)
                            self.assertIs(body["stream"], True)
                            verification = any(
                                t["function"]["name"] == "final_result"
                                for t in body.get("tools", [])
                            )
                            step = next(steps, None) if not verification else None
                            if verification:
                                step = (
                                    "final_result",
                                    {
                                        "results": [
                                            {
                                                "assertion_id": "home",
                                                "status": status,
                                                "reason": {
                                                    "passed": "Home visible",
                                                    "failed": "Expected login form absent",
                                                    "error": "Cannot determine account identity",
                                                }[status],
                                            }
                                        ]
                                    },
                                )
                            message = {"role": "assistant", "content": "Submitted"}
                            if step:
                                message = {
                                    "role": "assistant",
                                    "tool_calls": [
                                        {
                                            "id": str(len(requests)),
                                            "type": "function",
                                            "function": {
                                                "name": step[0],
                                                "arguments": json.dumps(step[1]),
                                            },
                                        }
                                    ],
                                }
                            return streamed_completion(
                                {
                                    "id": "r",
                                    "object": "chat.completion",
                                    "created": 1,
                                    "model": "controlled",
                                    "choices": [
                                        {
                                            "index": 0,
                                            "message": message,
                                            "finish_reason": "stop",
                                        }
                                    ],
                                }
                            )

                        async with ModelService(
                            ModelServiceConfig(
                                "http://controlled/v1", "test", "controlled"
                            )
                        ) as service:
                            await service.client.close()
                            from openai import AsyncOpenAI

                            service.client = AsyncOpenAI(
                                api_key="test",
                                max_retries=0,
                                http_client=httpx.AsyncClient(
                                    transport=httpx.MockTransport(respond)
                                ),
                            )
                            cfg = json.loads(
                                Path("login-demo/mvp-config.json").read_text()
                            )
                            cfg.update(
                                entry_url=f"http://127.0.0.1:{server.server_port}/page.html",
                                output_dir=directory,
                            )
                            case = {
                                "execution": {"goal": "Login", "instructions": []},
                                "assertions": [
                                    {
                                        "id": "home",
                                        "expected": {
                                            "passed": "Home visible",
                                            "failed": "Login form visible",
                                            "error": "Account identity visible",
                                        }[status],
                                    }
                                ],
                            }

                            class ObservedBrowser(Browser):
                                final_text = None

                                async def close(self):
                                    if self.page is not None:
                                        self.final_text = await self.page.inner_text(
                                            "body"
                                        )
                                    await super().close()

                            browser = ObservedBrowser()
                            exporter = CapturingExporter()
                            with (
                                run_trace(exporter),
                                patch("uiprobe.session.Browser", return_value=browser),
                            ):
                                result = await run_application(
                                    json.dumps(case), cfg, service
                                )
                            self.assertEqual(browser.final_text, "Home")
                            self.assertEqual(result.status, status, result.errors)
                            self.assertEqual(result.action_count, 5)
                            self.assertFalse(service.client.is_closed())
                            run = Path(directory, result.session_id)
                            self.assertEqual(
                                json.loads((run / "result.json").read_text())["status"],
                                status,
                            )
                            self.assertEqual(
                                len(list((run / "screenshots").glob("*.png"))), 6
                            )
                            self.assertTrue((run / "verification.json").exists())
                            trace = json.loads((run / "trace.json").read_text())
                            payload = b"".join(exporter.payloads)
                            self.assertNotIn(b"data:image", payload)
                            self.assertNotIn(b"iVBORw0KGgo", payload)
                            self.assertIn(b"browser_dispatch", payload)
                            self.assertIn(b"css_x", payload)
                            self.assertIn(b"replace_todo", payload)
                            self.assertEqual(
                                len(
                                    [
                                        s
                                        for s in trace["spans"]
                                        if s["attributes"].get("gen_ai.operation.name")
                                        == "chat"
                                    ]
                                ),
                                len(requests),
                            )
                            if status == "passed":
                                self.assertNotIn("Login", repr(requests[-1]))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


class CommandTests(unittest.TestCase):
    def test_result_json_and_exit_codes(self):
        for status, expected in (("passed", 0), ("failed", 1), ("error", 2)):
            with (
                self.subTest(status=status),
                patch(
                    "uiprobe.__main__.run_files",
                    return_value=SessionResult("run", status=status),
                ),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                code = main(["--case", "case.json", "--config", "config.json"])
            self.assertEqual(code, expected)
            self.assertEqual(json.loads(output.getvalue())["status"], status)

    def test_missing_model_configuration_is_safe_json(self):
        with (
            patch(
                "uiprobe.__main__.ModelServiceConfig.from_env",
                side_effect=ValueError("secret"),
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            code = main(
                [
                    "--case",
                    "login-demo/mvp-case.json",
                    "--config",
                    "login-demo/mvp-config.json",
                ]
            )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["action_count"], 0)
        self.assertNotIn("secret", output.getvalue())
