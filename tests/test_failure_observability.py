import json
import tempfile
import time
import unittest

from agent_support import PLAN, begin_verification, calls, run_actions
from input_fixtures import case, config, prepared_case
from pydantic_ai.models.function import FunctionModel

from uiprobe.case_input import TestCase
from uiprobe.observation import Screenshot
from uiprobe.recording import Recorder
from uiprobe.verification import Verification


class FailureObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import http.server
        import threading

        class Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<h1>Home</h1><button>Go</button>")

            def log_message(self, format, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/"

    async def asyncTearDown(self):
        import asyncio

        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join()

    async def test_unknown_and_invalid_tools_can_be_corrected_without_dispatch(self):
        from trace_fixtures import CapturingExporter

        from uiprobe.observability import run_trace

        exporter = CapturingExporter()
        with run_trace(exporter):
            _, budget, submission, _, events, _ = await run_actions(
                [
                    calls(("unknown_tool", {})),
                    calls(PLAN),
                    calls(("scroll", {"delta_y": True})),
                    calls(("scroll", {})),
                    calls(("scroll", {"delta_y": 1, "extra": True})),
                    calls(("wait", {"duration_ms": 10001})),
                    calls(("scroll", {"delta_y": 1})),
                ],
                "<p>Page</p>",
            )
        payload = b"".join(exporter.payloads)
        self.assertIn(b"unknown_tool", payload)
        self.assertIn(b"tool_feedback", payload)
        self.assertIn(b"delta_y", payload)
        self.assertEqual(budget.action_count, 1)
        self.assertEqual(submission.text, "Done")
        feedback = [e for e in events if e["type"] == "tool_feedback"]
        self.assertTrue(any(e["tool"] == "unknown_tool" for e in feedback))
        self.assertTrue(any(e["tool"] == "scroll" for e in feedback))
        self.assertTrue(all(e["reason"] for e in feedback))
        rejected = [e for e in events if e.get("status") == "rejected"]
        self.assertTrue(any(e.get("reason") for e in rejected))

    async def test_verification_system_failure_has_linked_diagnostic(self):
        async def respond(messages, info):
            raise ConnectionError("transport disconnected")

        with tempfile.TemporaryDirectory() as directory:
            record = Recorder().begin("run", directory)
            evidence, verification_record = begin_verification(
                record,
                TestCase.model_validate(case()).checkpoints[0],
                Screenshot("screen-1", b"png", 1, 1),
            )
            verdict = await Verification(FunctionModel(respond)).evaluate(
                evidence,
                time.monotonic() + 10,
                record=verification_record,
                request_limit=1,
                retry_limit=1,
            )
            self.assertEqual(verdict.status, "error")
            diagnostic = json.loads(
                next((record.directory / "diagnostics").iterdir()).read_text()
            )
            self.assertIn(diagnostic["error_id"], verdict.assertions[0].reason)
            self.assertIn("transport disconnected", diagnostic["traceback"])

    async def test_dispatched_faults_stop_without_submission_or_verification(self):
        from pathlib import Path
        from unittest.mock import patch

        from pydantic_ai.messages import ModelResponse, TextPart
        from trace_fixtures import CapturingExporter

        from uiprobe.agent import ExecutionAgent
        from uiprobe.browser import Browser
        from uiprobe.observability import run_trace
        from uiprobe.session import Session

        for mode in ("dispatch", "capture", "popup", "closed"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                page = Path(directory, "page.html")
                page.write_text(
                    "<button onclick=\"window.open('about:blank')\">Popup</button>"
                )
                cfg = config(directory)
                cfg["entry_url"] = self.url
                requests = []
                browser = Browser()
                original_scroll = browser.scroll
                original_capture = browser.capture

                async def scroll(*args):
                    result = await original_scroll(*args)
                    if mode == "dispatch":
                        raise ConnectionError("page disconnected after dispatch")
                    if mode == "closed":
                        assert browser.page is not None
                        await browser.page.close()
                    if mode == "popup":
                        await browser.context.new_page()
                    return result

                async def capture(deadline):
                    if mode == "capture" and browser.sequence:
                        raise RuntimeError("screenshot unavailable")
                    return await original_capture(deadline)

                steps = iter([calls(PLAN), calls(("scroll", {"delta_y": 1}))])

                def respond(messages, info):
                    requests.append(messages)
                    return next(steps, ModelResponse(parts=[TextPart("unexpected")]))

                class NoVerification:
                    async def evaluate(self, *args, **kwargs):
                        raise AssertionError("Must not verify without submission")

                exporter = CapturingExporter()
                with (
                    patch.object(browser, "scroll", scroll),
                    patch.object(browser, "capture", capture),
                    run_trace(exporter),
                ):
                    result = await Session(
                        browser_factory=lambda: browser,
                        agent=ExecutionAgent(FunctionModel(respond)),
                        verification=NoVerification(),
                    ).run(prepared_case(cfg))
                self.assertIsNone(result.execution_outcome)
                self.assertIsNone(result.checkpoints[0].verdict)
                self.assertEqual(result.status, "error")
                self.assertEqual(result.stop_reason, "execution_error")
                self.assertEqual(result.action_count, 1)
                self.assertEqual(result.last_screenshot_id, "screen-1")
                self.assertEqual(len(requests), 2)
                error = result.errors[0]
                self.assertEqual(
                    error.operation,
                    "scroll" if mode == "dispatch" else "capture_after_action",
                )
                diagnostic = json.loads(
                    Path(
                        directory,
                        result.session_id,
                        "diagnostics",
                        error.error_id + ".json",
                    ).read_text()
                )
                self.assertEqual(diagnostic["action_index"], 1)
                self.assertEqual(diagnostic["screenshot_id"], "screen-1")
                self.assertEqual(diagnostic["call_id"], "call-0-scroll")
                self.assertTrue(diagnostic["traceback"])
                self.assertIn(error.error_id.encode(), b"".join(exporter.payloads))

    async def test_native_budget_diagnostic_preserves_exception_type(self):
        from pydantic_ai.exceptions import UsageLimitExceeded

        from uiprobe.error_handling import describe

        with self.assertRaises(UsageLimitExceeded) as caught:
            await run_actions([calls(PLAN)], "<p>Page</p>", request_limit=1)
        error, diagnostic = describe(
            caught.exception, "execution", "fallback", "fallback", "fallback"
        )
        self.assertEqual(error.code, "model_budget_exhausted")
        self.assertIn("UsageLimitExceeded", diagnostic["traceback"])

    async def test_verification_diagnostics_distinguish_missing_deadline_and_output(
        self,
    ):
        from pydantic_ai.messages import ModelResponse, ToolCallPart

        for mode, expected in (
            ("missing", "evidence_missing"),
            ("deadline", "deadline_exhausted"),
            ("invalid", "model_output_invalid"),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                requests = []

                def respond(messages, info):
                    requests.append(messages)
                    return ModelResponse(
                        parts=[ToolCallPart(info.output_tools[0].name, {"results": []})]
                    )

                record = Recorder().begin("run", directory)
                evidence, verification_record = begin_verification(
                    record,
                    TestCase.model_validate(case()).checkpoints[0],
                    None if mode == "missing" else Screenshot("screen-1", b"png", 1, 1),
                )
                verdict = await Verification(FunctionModel(respond)).evaluate(
                    evidence,
                    time.monotonic() + (-1 if mode == "deadline" else 10),
                    record=verification_record,
                    request_limit=3,
                    retry_limit=1,
                )
                self.assertEqual(verdict.status, "error")
                self.assertEqual(len(requests), 2 if mode == "invalid" else 0)
                diagnostic = json.loads(
                    next((record.directory / "diagnostics").iterdir()).read_text()
                )
                self.assertEqual(diagnostic["code"], expected)
                self.assertIn(diagnostic["error_id"], verdict.assertions[0].reason)

    async def test_openai_stream_interruption_and_protocol_failure(self):
        from pathlib import Path

        import httpx2 as httpx
        from openai import AsyncOpenAI
        from trace_fixtures import CapturingExporter

        from uiprobe.agent import ExecutionAgent, model_from_client
        from uiprobe.observability import run_trace
        from uiprobe.session import Session

        class Interrupted(httpx.AsyncByteStream):
            async def __aiter__(self):
                for delta in (
                    {"role": "assistant", "content": "partial visible text"},
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "partial-call",
                                "type": "function",
                                "function": {
                                    "name": "scroll",
                                    "arguments": '{"delta_y":',
                                },
                            }
                        ]
                    },
                ):
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "id": "partial",
                                "created": 0,
                                "model": "test",
                                "choices": [
                                    {"index": 0, "delta": delta, "finish_reason": None}
                                ],
                            }
                        )
                        + "\n\n"
                    ).encode()
                raise httpx.ReadError("stream disconnected")

        for mode in ("interrupted", "protocol", "connection"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                requests = []

                def respond(request):
                    requests.append(request)
                    if mode == "connection":
                        raise httpx.ConnectError("cannot connect", request=request)
                    if mode == "protocol":
                        return httpx.Response(200, json={"unexpected": "payload"})
                    return httpx.Response(
                        200,
                        headers={"content-type": "text/event-stream"},
                        stream=Interrupted(),
                    )

                async with AsyncOpenAI(
                    api_key="test",
                    base_url="https://model.invalid/v1",
                    max_retries=2,
                    http_client=httpx.AsyncClient(
                        transport=httpx.MockTransport(respond)
                    ),
                ) as client:
                    cfg = config(directory)
                    cfg["entry_url"] = self.url
                    exporter = CapturingExporter()
                    with run_trace(exporter):
                        result = await Session(
                            agent=ExecutionAgent(model_from_client(client, "test")),
                            verification=Verification(
                                model_from_client(client, "test")
                            ),
                        ).run(prepared_case(cfg))
                self.assertEqual(result.stop_reason, "execution_error")
                self.assertEqual(result.action_count, 0)
                self.assertIsNone(result.execution_outcome)
                self.assertIsNone(result.checkpoints[0].verdict)
                self.assertEqual(len(requests), 3 if mode == "connection" else 1)
                error = result.errors[0]
                diagnostic = json.loads(
                    Path(
                        directory,
                        result.session_id,
                        "diagnostics",
                        error.error_id + ".json",
                    ).read_text()
                )
                self.assertTrue(diagnostic["traceback"])
                if mode == "interrupted":
                    self.assertTrue(diagnostic["incomplete"])
                    self.assertIn("partial visible text", diagnostic["partial_output"])
                    self.assertIn("partial-call", diagnostic["partial_output"])
                    self.assertIn(error.error_id.encode(), b"".join(exporter.payloads))

    async def test_online_failures_preserve_all_visual_verdicts(self):
        from pathlib import Path
        from unittest.mock import patch

        from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
        from test_observability import Submit

        from uiprobe.observability import run_trace
        from uiprobe.observation import AssertionResult, Status, Verdict
        from uiprobe.session import Session

        class Failed(SpanExporter):
            def export(self, spans):
                return SpanExportResult.FAILURE

        class Raised(SpanExporter):
            def export(self, spans):
                raise ConnectionError("collector offline")

        statuses: list[Status] = ["passed", "failed", "error"]
        for status in statuses:
            for mode in ("failure", "exception", "config"):
                with (
                    self.subTest(status=status, mode=mode),
                    tempfile.TemporaryDirectory() as directory,
                ):

                    class Judge:
                        def __init__(self, outcome: Status):
                            self.outcome: Status = outcome

                        async def evaluate(self, evidence, *args, **kwargs):
                            assert evidence.screenshot is not None
                            return Verdict(
                                evidence.submission_id,
                                self.outcome,
                                [
                                    AssertionResult(
                                        "home",
                                        self.outcome,
                                        "Visible evidence",
                                        evidence.screenshot.screenshot_id,
                                    )
                                ],
                            )

                    cfg = config(directory)
                    cfg["entry_url"] = self.url
                    with patch.dict(
                        "os.environ", {"LANGFUSE_PUBLIC_KEY": "test"}, clear=True
                    ):
                        with run_trace(
                            Failed()
                            if mode == "failure"
                            else Raised()
                            if mode == "exception"
                            else None
                        ):
                            result = await Session(
                                agent=Submit(), verification=Judge(status)
                            ).run(prepared_case(cfg))
                    self.assertEqual(result.status, status)
                    assert result.checkpoints[0].verdict is not None
                    self.assertEqual(result.checkpoints[0].verdict.status, status)
                    self.assertFalse(result.errors)
                    self.assertIsNotNone(result.execution_outcome)
                    trace = json.loads(
                        Path(directory, result.session_id, "trace.json").read_text()
                    )
                    self.assertTrue(trace["observability_incomplete"])
                    self.assertEqual(trace["export"]["remote_delivery"], "unknown")
                    self.assertEqual(
                        trace["export"]["flush"],
                        "not_requested" if mode == "config" else "completed",
                    )
                    self.assertEqual(
                        trace["export"]["batches_failed"], 0 if mode == "config" else 1
                    )
                    diagnostic = trace["observability_diagnostics"][0]
                    self.assertIn(diagnostic["error_id"], trace["warnings"][0])
                    if mode == "exception":
                        self.assertIn("collector offline", diagnostic["traceback"])
