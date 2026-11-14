"""Capture the actual OTLP protobuf payload at the network boundary."""

from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


class CapturingExporter(SpanExporter):
    def __init__(self):
        self.payloads = []
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        self.payloads.append(encode_spans(spans).SerializeToString())
        return SpanExportResult.SUCCESS
