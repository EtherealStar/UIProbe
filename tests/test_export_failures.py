"""SDK-visible queue and flush states, without remote delivery assumptions."""

import functools
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from trace_fixtures import CapturingExporter

from uiprobe.observability import run_trace


class ExportFailureTests(unittest.TestCase):
    def test_flush_false_exception_and_shutdown_failure(self):
        for mode in ("false", "exception", "shutdown"):
            with self.subTest(mode=mode):
                exporter = CapturingExporter()
                patcher = None
                with patch.object(
                    exporter,
                    "shutdown",
                    side_effect=RuntimeError("shutdown failed")
                    if mode == "shutdown"
                    else None,
                ):
                    with run_trace(exporter) as scope:
                        if mode != "shutdown":
                            patcher = patch.object(
                                scope.provider,
                                "force_flush",
                                return_value=False,
                                side_effect=RuntimeError("flush failed")
                                if mode == "exception"
                                else None,
                            )
                            patcher.start()
                    if patcher is not None:
                        patcher.stop()
                self.assertEqual(scope.export_status["flush"], "failed")
                self.assertTrue(scope.diagnostics)
                self.assertEqual(scope.export_status["remote_delivery"], "unknown")

    def test_real_sdk_queue_drop_is_observable(self):
        entered = threading.Event()
        release = threading.Event()

        class Blocked(SpanExporter):
            def export(self, spans):
                entered.set()
                release.wait(5)
                return SpanExportResult.SUCCESS

        with patch(
            "uiprobe.observability.BatchSpanProcessor",
            functools.partial(
                BatchSpanProcessor, max_queue_size=2, max_export_batch_size=1
            ),
        ):
            try:
                with run_trace(Blocked()) as scope:
                    with scope.tracer.start_as_current_span("first"):
                        pass
                    self.assertTrue(entered.wait(1))
                    for _ in range(10):
                        with scope.tracer.start_as_current_span("queued"):
                            pass
                    release.set()
                self.assertTrue(
                    any(d["operation"] == "sdk_queue" for d in scope.diagnostics)
                )
                self.assertEqual(scope.export_status["flush"], "completed")
            finally:
                release.set()

    def test_exit_timeout_snapshot_is_not_overwritten_after_release(self):
        from uiprobe.observability import bind_record
        from uiprobe.recording import Recorder

        release = threading.Event()
        done = threading.Event()

        class Blocked(SpanExporter):
            def export(self, spans):
                release.wait(5)
                return SpanExportResult.SUCCESS

            def shutdown(self):
                done.set()

        with tempfile.TemporaryDirectory() as directory:
            try:
                started = time.monotonic()
                with run_trace(Blocked()) as scope:
                    record = Recorder().begin("run", directory)
                    bind_record(record)
                self.assertLess(time.monotonic() - started, 3.5)
                before = (record.directory / "trace.json").read_text()
                self.assertEqual(scope.export_status["flush"], "timed_out")
                release.set()
                self.assertTrue(done.wait(1))
                self.assertEqual(scope.export_status["flush"], "timed_out")
                self.assertEqual((record.directory / "trace.json").read_text(), before)
            finally:
                release.set()
