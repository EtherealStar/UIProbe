"""Run-scoped native tracing with local records and optional Langfuse OTLP."""

import base64
import json
import os
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Span
from pydantic_ai.models.instrumented import InstrumentationSettings

_current: ContextVar[Any] = ContextVar("uiprobe_observability", default=None)


class LocalExporter(SpanExporter):
    def __init__(self):
        self.spans = []

    def export(self, spans):
        self.spans.extend(json.loads(span.to_json()) for span in spans)
        return SpanExportResult.SUCCESS


class IsolatedExporter(SpanExporter):
    def __init__(self, exporter, warnings):
        self.exporter = exporter
        self.warnings = warnings

    def export(self, spans):
        try:
            result = self.exporter.export(spans)
            if result != SpanExportResult.SUCCESS:
                self.warnings.append("Online export failed; remote delivery unknown")
            return result
        except Exception as exc:
            self.warnings.append(f"Online export failed: {type(exc).__name__}")
            return SpanExportResult.FAILURE

    def shutdown(self):
        self.exporter.shutdown()


class RunTrace:
    def __init__(self, exporter=None):
        self.local = LocalExporter()
        self.provider = TracerProvider(shutdown_on_exit=False)
        self.provider.add_span_processor(SimpleSpanProcessor(self.local))
        self.warnings = []
        self.local_error: OSError | None = None
        self.record = None
        self.root: Span | None = None
        try:
            if exporter is None and os.getenv("LANGFUSE_PUBLIC_KEY"):
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                secret = os.environ["LANGFUSE_SECRET_KEY"]
                auth = base64.b64encode(
                    f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{secret}".encode()
                ).decode()
                host = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
                exporter = OTLPSpanExporter(
                    endpoint=host + "/api/public/otel/v1/traces",
                    headers={"Authorization": "Basic " + auth},
                    timeout=2,
                )
            if exporter is not None:
                self.provider.add_span_processor(
                    BatchSpanProcessor(
                        IsolatedExporter(exporter, self.warnings),
                        export_timeout_millis=2000,
                    )
                )
        except Exception as exc:
            self.warnings.append(f"Online tracing unavailable: {type(exc).__name__}")
        self.tracer = self.provider.get_tracer("uiprobe")
        self.instrument = InstrumentationSettings(
            tracer_provider=self.provider,
            include_binary_content=False,
            include_content=True,
            include_model_request_parameters=True,
        )

    def save(self):
        if self.record is not None:
            self.record.save_trace(self.local.spans, self.warnings)


@contextmanager
def run_trace(exporter=None):
    existing = _current.get()
    if existing is not None:
        yield existing
        return
    scope = RunTrace(exporter)
    token = _current.set(scope)
    try:
        with scope.tracer.start_as_current_span("application") as root:
            scope.root = root
            yield scope
    finally:
        try:

            def flush():
                try:
                    scope.provider.force_flush()
                    scope.provider.shutdown()
                except Exception as exc:
                    scope.warnings.append(f"Online flush failed: {type(exc).__name__}")

            worker = threading.Thread(target=flush, daemon=True)
            worker.start()
            worker.join(2.5)
            if worker.is_alive():
                scope.warnings.append(
                    "Online flush incomplete; remote delivery unknown"
                )
            try:
                scope.save()
            except OSError as exc:
                scope.local_error = exc
                # Final trace update follows the already finalized SessionResult.
                print(
                    f"Cannot finalize local trace: {type(exc).__name__}",
                    file=sys.stderr,
                )
        finally:
            _current.reset(token)


def instrumentation():
    scope = _current.get()
    return scope.instrument if scope is not None else False


def traced(name):
    def decorate(function):
        @wraps(function)
        async def call(*args, **kwargs):
            with run_trace() as scope:
                with scope.tracer.start_as_current_span(name):
                    result = await function(*args, **kwargs)
            if scope.local_error is not None and hasattr(result, "errors"):
                from .error_handling import describe

                error, _ = describe(
                    scope.local_error,
                    "recording",
                    "save_trace",
                    "trace_save_failed",
                    "Cannot finalize local trace",
                )
                result.errors.append(error)
                result.status = "error"
            return result

        return call

    return decorate


def fact(name, **attributes):
    scope = _current.get()
    if scope is not None:
        from opentelemetry import trace

        trace.get_current_span().add_event(name, attributes)


def bind_record(record):
    scope = _current.get()
    if scope is not None:
        scope.record = record
        scope.root.set_attribute("session_id", record.session_id)
        record.trace_id = format(scope.root.get_span_context().trace_id, "032x")
        scope.save()
