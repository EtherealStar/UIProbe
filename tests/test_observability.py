"""Observable navigation and exporter isolation at production interfaces."""

import functools
import http.server
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from test_session_input import case, config
from trace_fixtures import CapturingExporter

from uiprobe.observability import run_trace
from uiprobe.observation import AssertionResult, Submission, Verdict
from uiprobe.session import Session


class Submit:
    async def execute(self, *args, **kwargs):
        return Submission("Initial error page observed")


class Judge:
    async def evaluate(self, evidence, *args, **kwargs):
        assert evidence.screenshot is not None
        return Verdict(
            evidence.submission_id,
            "failed",
            [
                AssertionResult(
                    "home",
                    "failed",
                    "Error page visible",
                    evidence.screenshot.screenshot_id,
                )
            ],
        )


class BrokenExporter(SpanExporter):
    def export(self, spans):
        raise ConnectionError("offline")


class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_error_page_continues_and_online_failure_preserves_verdict(self):
        with tempfile.TemporaryDirectory() as directory:
            server = http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                functools.partial(
                    http.server.SimpleHTTPRequestHandler, directory=directory
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                cfg = config(directory)
                cfg["entry_url"] = f"http://127.0.0.1:{server.server_port}/missing"
                for exporter in (CapturingExporter(), BrokenExporter()):
                    with run_trace(exporter):
                        result = await Session(
                            agent=Submit(), verification=Judge()
                        ).run(json.dumps(case()), cfg)
                    self.assertEqual(result.status, "failed", result.errors)
                    self.assertEqual(result.action_count, 0)
                    trace = json.loads(
                        Path(directory, result.session_id, "trace.json").read_text()
                    )
                    navigation = [
                        e
                        for s in trace["spans"]
                        for e in s["events"]
                        if e["name"] == "navigation"
                    ]
                    self.assertEqual(navigation[0]["attributes"]["http_status"], 404)
                    self.assertEqual(
                        bool(trace["warnings"]), isinstance(exporter, BrokenExporter)
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


class ExitTests(unittest.TestCase):
    def test_blocked_export_has_independent_exit_bound(self):
        release = threading.Event()

        class Blocked(SpanExporter):
            def export(self, spans):
                release.wait(10)
                return SpanExportResult.SUCCESS

        try:
            started = time.monotonic()
            with run_trace(Blocked()):
                pass
            self.assertLess(time.monotonic() - started, 3.5)
        finally:
            release.set()

    def test_real_otlp_http_endpoint_receives_only_trace_payload(self):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        received = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(
                    (self.path, self.rfile.read(int(self.headers["Content-Length"])))
                )
                self.send_response(200)
                self.end_headers()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            exporter = OTLPSpanExporter(
                endpoint=f"http://127.0.0.1:{server.server_port}/api/public/otel/v1/traces",
                timeout=1,
            )
            with run_trace(exporter):
                pass
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0][0], "/api/public/otel/v1/traces")
            decoded = ExportTraceServiceRequest.FromString(received[0][1])
            self.assertEqual(
                decoded.resource_spans[0].scope_spans[0].spans[0].name, "application"
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
