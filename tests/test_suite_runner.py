import asyncio
import functools
import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx2 as httpx
from input_fixtures import case, config
from openai import AsyncOpenAI
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from stream_fixtures import streamed_completion

from uiprobe.browser import Browser
from uiprobe.model_service import ModelService, ModelServiceConfig
from uiprobe.observation import BrowserState, Screenshot
from uiprobe.recording import SessionRecord
from uiprobe.suite_runner import SuiteRunner


class SuiteRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_serial_cases_use_isolated_pages_and_shared_model_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in ("override", "default"):
                (root / f"{filename}.html").write_text(
                    '<input type="password" style="position:absolute;left:10px;top:10px">'
                )
            server = http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                functools.partial(
                    http.server.SimpleHTTPRequestHandler, directory=directory
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addAsyncCleanup(asyncio.to_thread, server.shutdown)
            base_url = f"http://127.0.0.1:{server.server_port}"
            defaults = config(directory)
            defaults["entry_url"] = f"{base_url}/default.html"
            defaults["max_actions"] = 2
            opened = []
            closed = []
            requests = []
            execution_steps: dict[int, int] = {}
            first_verification = asyncio.Event()
            release_verification = asyncio.Event()

            class ObservedBrowser(Browser):
                async def open(self, entry_url, data_values, deadline_at):
                    # Suite and fixture files have no session history.
                    previous = list(root.glob("*/history.json"))
                    assert len(previous) == len(opened)
                    assert all(
                        (path.parent / "result.json").is_file() for path in previous
                    )
                    assert len(closed) == len(opened)
                    opened.append(entry_url)
                    return await super().open(entry_url, data_values, deadline_at)

                async def close(self):
                    try:
                        if self.page is not None:
                            closed.append(
                                await self.page.locator("input").input_value(
                                    timeout=1000
                                )
                            )
                    finally:
                        await super().close()

            stages = [
                (
                    "replace_todo",
                    {"items": [{"description": "Fill field", "status": "pending"}]},
                ),
                ("click", {"screenshot_id": "screen-1", "x": 30, "y": 20}),
                ("fill_value", {"ref": "password"}),
                ("submit_checkpoint", {"checkpoint_id": "home"}),
            ]

            async def respond(request):
                body = json.loads(request.content)
                messages = body["messages"]
                text = repr(messages)
                self.assertNotIn("override-value", text)
                self.assertNotIn("secret-value", text)
                name_list = [item["function"]["name"] for item in body.get("tools", [])]
                step = None
                if "final_result" in name_list:
                    identifier = next(
                        key for key in ("first", "third", "last") if key in text
                    )
                    if identifier == "first":
                        first_verification.set()
                        await release_verification.wait()
                    status = {"first": "failed", "third": "error", "last": "passed"}[
                        identifier
                    ]
                    step = (
                        "final_result",
                        {
                            "results": [
                                {
                                    "assertion_id": identifier,
                                    "status": status,
                                    "reason": "Observed page",
                                }
                            ]
                        },
                    )
                else:
                    case_number = len(opened)
                    step_number = execution_steps.get(case_number, 0)
                    execution_steps[case_number] = step_number + 1
                    if step_number < len(stages):
                        step = stages[step_number]
                    else:
                        self.assertEqual(name_list, [])
                        last_tool = max(
                            i
                            for i, item in enumerate(messages)
                            if item["role"] == "tool"
                        )
                        self.assertNotIn(
                            "Submit the current evidence or explain",
                            repr(messages[last_tool + 1 :]),
                        )
                requests.append(body)
                message = {"role": "assistant", "content": "Execution finished"}
                if step is not None:
                    message = {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": f"call-{len(requests)}",
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
                        "id": f"response-{len(requests)}",
                        "object": "chat.completion",
                        "created": 1,
                        "model": "controlled",
                        "choices": [
                            {"index": 0, "message": message, "finish_reason": "stop"}
                        ],
                    }
                )

            service = ModelService(
                ModelServiceConfig("http://controlled/v1", "test", "controlled")
            )
            await service.close()
            service.client = AsyncOpenAI(
                api_key="test",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
            )
            self.addAsyncCleanup(service.close)
            factory_calls = 0

            def create_service():
                nonlocal factory_calls
                factory_calls += 1
                return service

            def named_case(identifier):
                data = case()
                data["id"] = identifier
                data["checkpoints"][0]["assertions"][0]["id"] = identifier
                return data

            source = json.dumps(
                {
                    "cases": [
                        named_case("first"),
                        {"id": "invalid"},
                        named_case("third"),
                        named_case("last"),
                    ]
                }
            )
            cfg = {
                "defaults": defaults,
                "case_overrides": {
                    "first": {
                        "entry_url": f"{base_url}/override.html",
                        "data_values": {"password": "override-value"},
                    }
                },
            }
            task = asyncio.create_task(
                SuiteRunner(create_service, browser_factory=ObservedBrowser).run(
                    source, cfg
                )
            )
            try:
                await asyncio.wait_for(first_verification.wait(), 10)
                self.assertEqual(opened, [f"{base_url}/override.html"])
                self.assertFalse(service.client.is_closed())
            finally:
                release_verification.set()
                result = await task
                if not first_verification.is_set():
                    self.fail(
                        [
                            item.session_result.errors
                            for item in result.cases
                            if item.session_result
                        ]
                    )

            self.assertEqual(factory_calls, 1)
            self.assertTrue(service.client.is_closed())
            self.assertEqual(
                opened,
                [
                    f"{base_url}/override.html",
                    f"{base_url}/default.html",
                    f"{base_url}/default.html",
                ],
            )
            self.assertEqual(closed, ["override-value", "secret-value", "secret-value"])
            self.assertEqual(
                [item.case_id for item in result.cases],
                ["first", "invalid", "third", "last"],
            )
            self.assertEqual(
                [item.status for item in result.cases],
                ["failed", "error", "error", "passed"],
            )
            self.assertEqual(result.status, "error")
            self.assertIsNone(result.cases[1].session_result)
            self.assertEqual(
                [item.source.case_index for item in result.cases], [0, 1, 2, 3]
            )
            runs = [item.session_result for item in result.cases if item.session_result]
            self.assertEqual(len({run.session_id for run in runs}), 3)
            self.assertTrue(all(run.action_count == 2 for run in runs))
            self.assertEqual({run.last_screenshot_id for run in runs}, {"screen-3"})
            self.assertEqual(len(requests), 18)
            traces = list(root.glob("*/trace.json"))
            self.assertEqual(traces, [root / result.suite_id / "trace.json"])
            trace = json.loads(traces[0].read_text())
            for name in ("session", "verification"):
                spans = [span for span in trace["spans"] if span["name"] == name]
                self.assertEqual(
                    {span["attributes"]["session_id"] for span in spans},
                    {run.session_id for run in runs},
                )
                self.assertEqual(
                    {span["attributes"]["suite_id"] for span in spans},
                    {result.suite_id},
                )

    async def test_public_error_retains_invalid_entries_without_allocating_resources(
        self,
    ):
        def unexpected():
            self.fail("Invalid configuration must prevent allocating resources")

        with tempfile.TemporaryDirectory() as directory:
            result = await SuiteRunner(unexpected, browser_factory=unexpected).run(
                json.dumps({"cases": [case(), {"id": "invalid"}]}),
                {"defaults": config(directory), "case_overrides": {"unknown": {}}},
            )
            self.assertEqual(result.status, "error")
            self.assertEqual(
                [item.status for item in result.cases], ["not_run", "error"]
            )
            self.assertTrue(all(item.session_result is None for item in result.cases))
            self.assertIn("unmatched_case_id", result.errors[0].message)
            self.assertEqual(result.cases[0].errors, [])
            self.assertTrue(result.cases[1].errors)

    async def test_required_execution_record_failure_stops_later_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            browser = AsyncMock()
            browser.open.return_value = BrowserState(
                Screenshot("screen-1", b"png", 1, 1), 1, 1
            )
            browser_factory = Mock(return_value=browser)
            service = AsyncMock()
            service.config = ModelServiceConfig(
                "http://controlled/v1", "test", "controlled"
            )
            model_response = Mock(return_value=ModelResponse(parts=[TextPart("Done")]))
            with (
                patch(
                    "uiprobe.suite_runner.model_from_client",
                    return_value=FunctionModel(model_response),
                ),
                patch.object(
                    SessionRecord,
                    "save_sent_messages",
                    side_effect=OSError("requests unavailable"),
                ),
            ):
                result = await SuiteRunner(
                    lambda: service,
                    browser_factory=browser_factory,
                ).run(
                    json.dumps({"cases": [case(), {**case(), "id": "later"}]}),
                    {"defaults": config(directory)},
                )

            self.assertEqual(result.stop_reason, "recording_error")
            self.assertEqual(
                [item.status for item in result.cases], ["error", "not_run"]
            )
            first = result.cases[0].session_result
            assert first is not None
            self.assertEqual(first.errors[0].phase, "recording")
            self.assertEqual(first.errors[0].operation, "save_execution_requests")
            self.assertEqual(first.errors[0].checkpoint_id, "home")
            browser_factory.assert_called_once()
            browser.close.assert_awaited_once()
            service.close.assert_awaited_once()
            model_response.assert_not_called()
