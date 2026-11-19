"""Preflight, serial case scheduling and ownership of batch resources."""

import asyncio
import sys
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from .agent import ExecutionAgent, model_from_client
from .browser import Browser
from .case_input import FieldError, SourceRef, prepare_suite
from .error_handling import RunError, describe
from .lifecycle import (
    FINALIZATION_SECONDS,
    close_within_deadline,
    settle,
    start_background_work,
)
from .model_service import ModelService
from .observability import bind_record, fact, run_trace
from .recording import Recorder, SuiteRecord
from .session import Session, SessionCancelled, SessionResult
from .verification import Verification


@dataclass
class SuiteCaseResult:
    source: SourceRef
    case_id: str | None
    status: str = "not_run"
    session_result: SessionResult | None = None
    errors: list[RunError] = field(default_factory=list)


@dataclass
class SuiteResult:
    suite_id: str
    status: str = "error"
    stop_reason: str = "input_error"
    cases: list[SuiteCaseResult] = field(default_factory=list)
    artifact_paths: list[str] = field(default_factory=list)
    errors: list[RunError] = field(default_factory=list)


class SuiteRunner:
    def __init__(
        self,
        service_factory: Callable[[], ModelService],
        *,
        recorder: Recorder | None = None,
        browser_factory: Callable[[], Browser] = Browser,
        exporter=None,
    ):
        self.service_factory = service_factory
        self.recorder = recorder if recorder is not None else Recorder()
        self.browser_factory = browser_factory
        self.exporter = exporter

    async def run(self, source: str | Path, config: object) -> SuiteResult:
        result = SuiteResult(uuid4().hex)
        record = None
        diagnostics = []
        cancelled: asyncio.CancelledError | None = None
        service: ModelService | None = None
        loop = asyncio.get_running_loop()

        def mark_cancelled(exc: asyncio.CancelledError):
            nonlocal cancelled
            if cancelled is None:
                cancelled = exc
            result.stop_reason = "cancelled"
            result.status = "error"

        def input_error(problem: FieldError, ref: SourceRef | None = None):
            error = RunError(
                "input", "invalid_input", f"{problem.path}: {problem.reason}"
            )
            diagnostic = {
                **error.__dict__,
                "source": ref.source if ref else None,
                "case_index": ref.case_index if ref else None,
                "exception_type": None,
                "exception_message": None,
                "traceback": None,
            }
            if problem.cause is not None:
                error, diagnostic = describe(
                    problem.cause,
                    "input",
                    "read_config" if problem.path == "config" else "read_case",
                    "startup_failed",
                    error.message,
                )
            diagnostic["suite_id"] = result.suite_id
            diagnostics.append(diagnostic)
            fact("diagnostic", **diagnostic)
            return error

        def failure(exc, phase, operation, code, message):
            error, diagnostic = describe(exc, phase, operation, code, message)
            result.errors.append(error)
            diagnostics.append(diagnostic)
            fact("diagnostic", **diagnostic)

        async def run_cases():
            nonlocal record, service
            with scope.tracer.start_as_current_span("prepare_suite"):
                prepared = await start_background_work(prepare_suite, source, config)
            for entry in prepared.entries:
                item = SuiteCaseResult(entry.source, entry.case_id)
                if entry.error is not None:
                    item.status = "error"
                    item.errors = [
                        input_error(problem, entry.source)
                        for problem in entry.error.errors
                    ]
                result.cases.append(item)
            result.errors.extend(input_error(problem) for problem in prepared.errors)

            if prepared.output_dir is not None:
                try:
                    record = self.recorder.begin_suite(
                        result.suite_id, prepared.output_dir
                    )
                    bind_record(record)
                    record.append({"type": "suite_started"})
                except OSError as exc:
                    failure(
                        exc,
                        "recording",
                        "create_record" if record is None else "append_events",
                        "begin_failed" if record is None else "append_failed",
                        "Cannot start suite record",
                    )
                    result.stop_reason = "recording_error"

            if result.errors or not any(entry.prepared for entry in prepared.entries):
                return
            try:
                with scope.tracer.start_as_current_span("model_client.create"):
                    service = self.service_factory()
                    model = model_from_client(service.client, service.config.model)
            except Exception as exc:
                failure(
                    exc,
                    "configuration",
                    "configure_model",
                    "startup_failed",
                    "Invalid or unavailable model configuration",
                )
                result.stop_reason = "configuration_error"
                return

            session = Session(
                recorder=self.recorder,
                browser_factory=self.browser_factory,
                agent=ExecutionAgent(model),
                verification=Verification(model),
                suite_id=result.suite_id,
            )
            result.stop_reason = "suite_completed"
            for entry, item in zip(prepared.entries, result.cases, strict=True):
                if entry.prepared is None:
                    continue
                try:
                    item.session_result = await session.run(entry.prepared)
                except SessionCancelled as exc:
                    item.session_result = exc.result
                    item.status = exc.result.status
                    raise
                item.status = item.session_result.status
                recording_error = next(
                    (
                        error
                        for error in item.session_result.errors
                        if error.phase == "recording"
                    ),
                    None,
                )
                if recording_error is not None:
                    result.stop_reason = "recording_error"
                    error = RunError(
                        "recording",
                        "session_record_failed",
                        "A required session record failed",
                        "run_session",
                    )
                    result.errors.append(error)
                    diagnostic = {
                        **error.__dict__,
                        "suite_id": result.suite_id,
                        "session_id": item.session_result.session_id,
                        "cause_error_id": recording_error.error_id,
                    }
                    diagnostics.append(diagnostic)
                    fact("diagnostic", **diagnostic)
                    break

        with run_trace(
            self.exporter, independent=True, defer_finalization=True
        ) as scope:
            assert scope.root is not None
            scope.root.set_attribute("suite_id", result.suite_id)
            try:
                await run_cases()
            except asyncio.CancelledError as exc:
                mark_cancelled(exc)
            finally:
                if service is not None:
                    with scope.tracer.start_as_current_span("model_client.close"):
                        closing = asyncio.create_task(
                            close_within_deadline(service.close(), FINALIZATION_SECONDS)
                        )
                        try:
                            await settle(closing, mark_cancelled)
                        except asyncio.CancelledError as exc:
                            mark_cancelled(exc)
                        except Exception as exc:
                            failure(
                                exc,
                                "cleanup",
                                "close_model_client",
                                "close_failed",
                                "Cannot close model client",
                            )

        exporting = start_background_work(scope.finish_export)
        await settle(exporting, mark_cancelled)
        saved_trace = None
        if record is not None:
            trace_deadline = loop.time() + FINALIZATION_SECONDS
            writing_trace = start_background_work(scope.save)
            try:
                await settle(writing_trace, mark_cancelled, deadline=trace_deadline)
            except (OSError, TimeoutError) as exc:
                failure(
                    exc,
                    "recording",
                    "save_trace",
                    "finalization_timeout"
                    if isinstance(exc, TimeoutError)
                    else "trace_save_failed",
                    "Cannot save suite trace",
                )
                print(
                    f"Cannot save suite trace; error_id={result.errors[-1].error_id}",
                    file=sys.stderr,
                )
            else:
                record.trace_save_confirmed = True
                saved_trace = str(record.directory / "trace.json")
        if (
            cancelled is None
            and not result.errors
            and all(item.status != "error" for item in result.cases)
        ):
            if any(item.status == "failed" for item in result.cases):
                result.status = "failed"
            elif result.cases and all(item.status == "passed" for item in result.cases):
                result.status = "passed"
        if record is not None:
            save_deadline = loop.time() + FINALIZATION_SECONDS
            saved_cancellation = cancelled is not None
            saving = start_background_work(
                _finish_record, record, deepcopy(result), tuple(diagnostics)
            )
            try:
                result = await settle(saving, mark_cancelled, deadline=save_deadline)
                if cancelled is not None and not saved_cancellation:
                    mark_cancelled(cancelled)
                    saving = start_background_work(
                        _save_result, record, deepcopy(result), True
                    )
                    result = await settle(
                        saving, mark_cancelled, deadline=save_deadline
                    )
            except TimeoutError as exc:
                failure(
                    exc,
                    "recording",
                    "save_result",
                    "finalization_timeout",
                    "Suite result save exceeded deadline",
                )
                result.status = "error"
                result.artifact_paths = [str(record.directory)]
                if saved_trace is not None:
                    result.artifact_paths.append(saved_trace)
                print(
                    f"Suite result save exceeded deadline; error_id={result.errors[-1].error_id}",
                    file=sys.stderr,
                )
        if cancelled is not None:
            raise cancelled
        return result


def _record_failure(
    record: SuiteRecord,
    result: SuiteResult,
    exc: OSError,
    operation: str,
    code: str,
    message: str,
) -> None:
    error, diagnostic = describe(exc, "recording", operation, code, message)
    result.errors.append(error)
    result.status = "error"
    print(f"{message}; error_id={error.error_id}", file=sys.stderr)
    try:
        record.save_diagnostic(diagnostic)
    except OSError as diagnostic_exc:
        error, _ = describe(
            diagnostic_exc,
            "recording",
            "save_diagnostic",
            "diagnostic_save_failed",
            "Cannot save suite diagnostic",
        )
        result.errors.append(error)
        print(f"{error.message}; error_id={error.error_id}", file=sys.stderr)


def _finish_record(
    record: SuiteRecord, result: SuiteResult, diagnostics: tuple[dict, ...]
) -> SuiteResult:
    try:
        for diagnostic in diagnostics:
            record.save_diagnostic(diagnostic)
        for error in result.errors:
            record.append({"type": "error", **error.__dict__})
        record.append({"type": "suite_finished", "status": result.status})
    except OSError as exc:
        _record_failure(
            record,
            result,
            exc,
            "append_events",
            "append_failed",
            "Cannot save suite events or diagnostics",
        )
    return _save_result(record, result)


def _save_result(
    record: SuiteRecord, result: SuiteResult, cancellation_update: bool = False
) -> SuiteResult:
    if cancellation_update:
        try:
            record.append({"type": "suite_cancelled", "status": result.status})
        except OSError as exc:
            _record_failure(
                record,
                result,
                exc,
                "append_events",
                "append_failed",
                "Cannot save suite cancellation",
            )
    try:
        result.artifact_paths = record.save_result(result)
    except OSError as exc:
        _record_failure(
            record,
            result,
            exc,
            "save_result",
            "finish_failed",
            "Cannot save suite result",
        )
        try:
            result.artifact_paths = [
                path
                for path in record.artifact_paths
                if Path(path).name != "result.json"
            ]
        except OSError:
            result.artifact_paths = []
    return result
