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

from uiprobe.__main__ import main, run_files
from uiprobe.browser import Browser
from uiprobe.model_service import ModelService, ModelServiceConfig
from uiprobe.suite_runner import SuiteResult, SuiteRunner


class ApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_and_initial_observation_verdict_statuses(self):
        import functools
        import http.server
        import itertools
        import threading

        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "page.html").write_text(
                """<input style="position:absolute;left:10px;top:10px"><input type="password" style="position:absolute;left:10px;top:50px"><button style="position:absolute;left:10px;top:90px" onclick="if(document.querySelectorAll('input')[0].value==='admin' && document.querySelectorAll('input')[1].value==='123456')document.body.innerHTML='<h1>Home</h1>'">Login</button>"""
            )
            Path(directory, "initial.html").write_text("<h1>Home</h1>")
            server = http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                functools.partial(
                    http.server.SimpleHTTPRequestHandler, directory=directory
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for status, zero_action in itertools.product(
                    ("passed", "failed", "error"), (False, True)
                ):
                    with self.subTest(status=status, zero_action=zero_action):
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
                                ("submit_checkpoint", {"checkpoint_id": "home"}),
                            ][-1 if zero_action else 0 :]
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
                            cfg["defaults"].update(
                                entry_url=f"http://127.0.0.1:{server.server_port}/{'initial' if zero_action else 'page'}.html",
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

                            case = {
                                "id": "login",
                                "name": "Login",
                                "checkpoints": [{"id": "home", **case}],
                            }
                            case_path = Path(directory, "case.json")
                            case_path.write_text(json.dumps(case))
                            config_path = Path(directory, "config.json")
                            config_path.write_text(json.dumps(cfg))

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
                                patch(
                                    "uiprobe.__main__.SuiteRunner",
                                    functools.partial(SuiteRunner, exporter=exporter),
                                ),
                                patch(
                                    "uiprobe.__main__.ModelService",
                                    return_value=service,
                                ),
                                patch(
                                    "uiprobe.__main__.ModelServiceConfig.from_env",
                                    return_value=service.config,
                                ),
                                patch(
                                    "uiprobe.__main__.Browser", return_value=browser
                                ) as browser_type,
                            ):
                                suite = await run_files(
                                    case_path, config_path, headed=status == "passed"
                                )
                            result = suite.cases[0].session_result
                            assert result is not None, suite.errors
                            self.assertEqual(suite.status, status)
                            browser_type.assert_called_once_with(
                                headless=status != "passed"
                            )
                            self.assertEqual(
                                result.status,
                                status,
                                [
                                    p.read_text()
                                    for p in Path(
                                        directory, result.session_id, "diagnostics"
                                    ).glob("*.json")
                                ],
                            )
                            self.assertEqual(browser.final_text, "Home")
                            self.assertEqual(result.status, status, result.errors)
                            self.assertEqual(
                                result.action_count, 0 if zero_action else 5
                            )
                            self.assertTrue(service.client.is_closed())
                            run = Path(directory, result.session_id)
                            self.assertEqual(
                                json.loads((run / "result.json").read_text())["status"],
                                status,
                            )
                            self.assertEqual(
                                len(list((run / "screenshots").glob("*.png"))),
                                1 if zero_action else 6,
                            )
                            assert result.checkpoints[0].verdict is not None
                            submission_dir = (
                                run
                                / "submissions"
                                / result.checkpoints[0].verdict.submission_id
                            )
                            evidence = json.loads(
                                (submission_dir / "input.json").read_text()
                            )
                            self.assertEqual(
                                evidence["screenshot_id"], result.last_screenshot_id
                            )
                            self.assertTrue((submission_dir / "history.json").is_file())
                            self.assertTrue(
                                (submission_dir / "requests.jsonl").is_file()
                            )
                            trace = json.loads(
                                Path(
                                    directory, suite.suite_id, "trace.json"
                                ).read_text()
                            )
                            payload = b"".join(exporter.payloads)
                            self.assertNotIn(b"data:image", payload)
                            self.assertNotIn(b"iVBORw0KGgo", payload)
                            if not zero_action:
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
    def test_headed_flag_reaches_application(self):
        for flags, headed in (([], False), (["--headed"], True)):
            with (
                self.subTest(headed=headed),
                patch(
                    "uiprobe.__main__.run_files",
                    return_value=SuiteResult("run", status="passed"),
                ) as application,
                patch("uiprobe.__main__.ModelServiceConfig.from_env") as connection,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                connection.return_value = ModelServiceConfig(
                    "http://controlled/v1", "test", "controlled"
                )
                code = main(
                    [
                        "--case",
                        "login-demo/mvp-case.json",
                        "--config",
                        "login-demo/mvp-config.json",
                        *flags,
                    ]
                )
            self.assertEqual(code, 0)
            application.assert_awaited_once()
            assert application.await_args is not None
            self.assertEqual(application.await_args.kwargs, {"headed": headed})

    def test_result_json_and_exit_codes(self):
        for status, expected in (("passed", 0), ("failed", 1), ("error", 2)):
            with (
                self.subTest(status=status),
                patch(
                    "uiprobe.__main__.run_files",
                    return_value=SuiteResult("run", status=status),
                ),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                code = main(["--case", "case.json", "--config", "config.json"])
            self.assertEqual(code, expected)
            self.assertEqual(json.loads(output.getvalue())["status"], status)

    def test_missing_model_configuration_is_safe_json(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "uiprobe.__main__.ModelServiceConfig.from_env",
                side_effect=ValueError("secret"),
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            config_path = Path(directory, "config.json")
            config = json.loads(Path("login-demo/mvp-config.json").read_text())
            config["defaults"]["output_dir"] = directory
            config_path.write_text(json.dumps(config))
            code = main(
                [
                    "--case",
                    "login-demo/mvp-case.json",
                    "--config",
                    str(config_path),
                ]
            )
        self.assertEqual(code, 2)
        entry = json.loads(output.getvalue())["cases"][0]
        self.assertEqual(entry["status"], "not_run")
        self.assertIsNone(entry["session_result"])
        self.assertNotIn("secret", output.getvalue())
