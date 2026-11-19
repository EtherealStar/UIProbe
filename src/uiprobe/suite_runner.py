"""Preflight, serial case scheduling and ownership of batch resources."""

import asyncio
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from .agent import ExecutionAgent, model_from_client
from .browser import Browser
from .case_input import FieldError, SourceRef, prepare_suite
from .error_handling import RunError, describe
from .model_service import ModelService
from .observability import bind_record, fact, run_trace, traced
from .recording import Recorder
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
        cancelled = None

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
            diagnostics.append(diagnostic)
            fact("diagnostic", **diagnostic)
            return error

        def failure(exc, phase, operation, code, message):
            error, diagnostic = describe(exc, phase, operation, code, message)
            result.errors.append(error)
            diagnostics.append(diagnostic)
            fact("diagnostic", **diagnostic)

        with run_trace(self.exporter, independent=True) as scope:
            assert scope.root is not None
            scope.root.set_attribute("suite_id", result.suite_id)
            prepared = prepare_suite(source, config)
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

            if not result.errors and any(entry.prepared for entry in prepared.entries):
                service = None
                try:
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
                else:
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
                            cancelled = exc
                            result.stop_reason = "cancelled"
                            break
                        except asyncio.CancelledError as exc:
                            cancelled = exc
                            result.stop_reason = "cancelled"
                            break
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
                            diagnostics.append(
                                {
                                    **error.__dict__,
                                    "session_id": item.session_result.session_id,
                                    "cause_error_id": recording_error.error_id,
                                }
                            )
                            break
                finally:
                    if service is not None:
                        try:
                            async with asyncio.timeout(5):
                                await _close_service(service)
                        except asyncio.CancelledError as exc:
                            cancelled = exc
                            result.stop_reason = "cancelled"
                        except Exception as exc:
                            failure(
                                exc,
                                "cleanup",
                                "close_model_client",
                                "close_failed",
                                "Cannot close model client",
                            )

        if scope.local_error is not None:
            failure(
                scope.local_error,
                "recording",
                "save_trace",
                "trace_save_failed",
                "Cannot save suite trace",
            )
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
            try:
                for diagnostic in diagnostics:
                    record.save_diagnostic(diagnostic)
                for error in result.errors:
                    record.append({"type": "error", **error.__dict__})
                record.append({"type": "suite_finished", "status": result.status})
            except OSError as exc:
                failure(
                    exc,
                    "recording",
                    "append_events",
                    "append_failed",
                    "Cannot save suite events or diagnostics",
                )
                result.status = "error"
            try:
                async with asyncio.timeout(5):
                    result.artifact_paths = await asyncio.to_thread(
                        record.save_result, deepcopy(result)
                    )
            except asyncio.CancelledError as exc:
                cancelled = exc
            except (OSError, TimeoutError) as exc:
                failure(
                    exc,
                    "recording",
                    "save_result",
                    "finish_failed",
                    "Cannot save suite result",
                )
                result.status = "error"
                try:
                    result.artifact_paths = [
                        path
                        for path in record.artifact_paths
                        if Path(path).name != "result.json"
                    ]
                except OSError:
                    pass
        if cancelled is not None:
            raise cancelled
        return result


@traced("model_client.close")
async def _close_service(service: ModelService) -> None:
    await service.close()
