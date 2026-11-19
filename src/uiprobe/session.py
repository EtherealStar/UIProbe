"""Run-local browser, execution and independent verification lifecycle."""

import asyncio
import sys
from contextvars import copy_context
from copy import deepcopy
from dataclasses import dataclass, field, replace
from uuid import uuid4

from .actions import CheckpointRejected, RunBudget
from .agent import Context
from .browser import Browser
from .case_input import PreparedCase, TestCase
from .error_handling import RunError, describe, locate
from .lifecycle import (
    FINALIZATION_SECONDS,
    close_within_deadline,
    settle,
    start_background_work,
)
from .observability import bind_record, fact, traced
from .observation import (
    AssertionResult,
    CheckpointReceipt,
    CheckpointResult,
    CheckpointSubmission,
    ExecutionOutcome,
    Screenshot,
    Verdict,
)
from .recording import Recorder, SubmissionRecord


@dataclass
class SessionResult:
    session_id: str
    test_case: TestCase
    checkpoints: list[CheckpointResult]
    status: str = "error"
    stop_reason: str = "initialization_error"
    execution_outcome: ExecutionOutcome | None = None
    action_count: int = 0
    last_screenshot_id: str | None = None
    artifact_paths: list[str] = field(default_factory=list)
    errors: list[RunError] = field(default_factory=list)


class SessionCancelled(asyncio.CancelledError):
    def __init__(self, result: SessionResult):
        super().__init__("Session cancelled")
        self.result = result


class Session:
    def __init__(
        self,
        *,
        recorder=None,
        browser_factory=None,
        agent=None,
        verification=None,
        suite_id: str | None = None,
    ):
        self.recorder = recorder if recorder is not None else Recorder()
        self.browser_factory = browser_factory
        self.agent = agent
        self.verification = verification
        self.suite_id = suite_id

    @traced("session")
    async def run(self, prepared: PreparedCase) -> SessionResult:
        config = prepared.session_config
        deadline = asyncio.get_running_loop().time() + config.timeout_seconds
        result = SessionResult(
            uuid4().hex,
            prepared.test_case,
            [CheckpointResult(item.id) for item in prepared.test_case.checkpoints],
        )
        checkpoints = prepared.test_case.checkpoints
        current_index = 0
        diagnostics = []
        try:
            record = self.recorder.begin(
                result.session_id, config.output_dir, suite_id=self.suite_id
            )
        except asyncio.CancelledError as exc:
            result.stop_reason = "cancelled"
            raise SessionCancelled(result) from exc
        except OSError as exc:
            error, diagnostic = describe(
                exc,
                "recording",
                "create_record",
                "begin_failed",
                "Cannot create record",
            )
            fact("diagnostic", **diagnostic)
            result.errors.append(error)
            result.stop_reason = "recording_error"
            return result
        bind_record(record)
        verification_context = copy_context()
        loop = asyncio.get_running_loop()
        recording_failed: asyncio.Future[RunError] = loop.create_future()
        execution_stopped_by_recording = False

        def notify_recording_failure(error: RunError):
            nonlocal execution_stopped_by_recording
            if recording_failed.done():
                return
            recording_failed.set_result(error)
            current_task = asyncio.current_task()
            if (
                execution is not current_task
                and not execution.done()
                and not execution.cancelling()
            ):
                execution_stopped_by_recording = True
                execution.cancel()
            for _, _, task in verifications:
                if (
                    task is not current_task
                    and not task.done()
                    and not task.cancelling()
                ):
                    task.cancel()

        verifications: list[
            tuple[CheckpointResult, SubmissionRecord, asyncio.Task[None]]
        ] = []
        verification_slots = asyncio.Semaphore(config.verification_concurrency)
        browser = None
        context = None
        cancelled = False
        started_record = False
        phase = "initialization"
        budget = RunBudget(deadline, config.max_actions)

        def accept_checkpoint(
            checkpoint_id: str, screenshot: Screenshot
        ) -> CheckpointReceipt:
            nonlocal current_index
            checkpoint = checkpoints[current_index]
            entry = result.checkpoints[current_index]
            if checkpoint_id != checkpoint.id or entry.submission_id is not None:
                raise CheckpointRejected("Submit the current checkpoint once.")
            evidence = CheckpointSubmission(
                uuid4().hex,
                result.session_id,
                checkpoint.id,
                tuple(checkpoint.assertions),
                screenshot,
            )
            candidate = record.begin_submission(evidence)
            with candidate.writing("save_verification_input"):
                candidate.save_input()
            with candidate.writing("append_submission"):
                candidate.append({"type": "submission"})
            candidate.on_write_failure = notify_recording_failure
            task = asyncio.create_task(
                verify(entry, candidate), context=verification_context.copy()
            )
            verifications.append((entry, candidate, task))
            entry.submission_id = evidence.submission_id
            entry.screenshot_id = screenshot.screenshot_id
            entry.state = "queued"
            fact("checkpoint_submitted", **candidate.association)
            next_checkpoint = None
            if current_index + 1 < len(checkpoints):
                current_index += 1
                next_checkpoint = checkpoints[current_index]
            return CheckpointReceipt(
                evidence.submission_id,
                checkpoint.id,
                screenshot.screenshot_id,
                next_checkpoint,
            )

        def add_failure(exc, phase, operation, code, message):
            error, diagnostic = describe(exc, phase, operation, code, message)
            if phase == "execution" and context is not None:
                entry = next(
                    item
                    for item in result.checkpoints
                    if item.checkpoint_id == context.checkpoint.id
                )
                error = replace(
                    error,
                    checkpoint_id=entry.checkpoint_id,
                    submission_id=entry.submission_id,
                )
                diagnostic["checkpoint_id"] = error.checkpoint_id
                if error.submission_id is not None:
                    diagnostic["submission_id"] = error.submission_id
            result.errors.append(error)
            diagnostics.append(diagnostic)
            return error

        def start_browser_close():
            if browser is None:
                return None
            return asyncio.create_task(
                close_within_deadline(browser.close(), FINALIZATION_SECONDS)
            )

        def execution_operation():
            if phase == "execution":
                return "execute_agent"
            current_operation = getattr(browser, "initialization_operation", None)
            return (
                current_operation
                if isinstance(current_operation, str)
                else "open_browser"
            )

        def finish_verification_error(
            entry: CheckpointResult, evidence: CheckpointSubmission, reason: str
        ):
            entry.verdict = Verdict(
                evidence.submission_id,
                "error",
                [
                    AssertionResult(item.id, "error", reason, entry.screenshot_id)
                    for item in evidence.assertions
                ],
            )

        async def verify(entry: CheckpointResult, candidate: SubmissionRecord):
            evidence = candidate.submission
            try:
                assert self.verification is not None
                async with verification_slots:
                    if recording_failed.done() or loop.time() >= deadline:
                        return
                    entry.state = "running"
                    with candidate.writing("append_verification_started"):
                        candidate.append({"type": "verification_started"})
                    entry.verdict = await self.verification.evaluate(
                        evidence,
                        deadline,
                        record=candidate,
                        request_limit=config.verification_request_limit,
                        retry_limit=config.verification_retry_limit,
                    )
            except Exception as exc:
                error, diagnostic = describe(
                    exc,
                    "verification",
                    "evaluate_assertions",
                    "deadline_exhausted"
                    if isinstance(exc, TimeoutError)
                    else "run_failed",
                    "Verification operation failed",
                )
                candidate.failures.append(
                    (
                        error,
                        {**diagnostic, **candidate.association},
                    )
                )
                finish_verification_error(
                    entry, evidence, f"{error.message}; error_id={error.error_id}"
                )
            finally:
                if entry.verdict is not None:
                    entry.state = "finished"
                    with candidate.writing("append_verification_finished", defer=True):
                        candidate.append(
                            {
                                "type": "verification_finished",
                                "status": entry.verdict.status,
                            }
                        )

        async def execute():
            nonlocal browser, context, started_record, phase
            try:
                with locate(
                    "recording",
                    "append_events",
                    "append_failed",
                    "Cannot append record",
                ):
                    record.append({"type": "session_started"})
                started_record = True
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError
                browser = (self.browser_factory or Browser)()
                state = await browser.open(
                    config.entry_url, config.data_values, deadline
                )
                if loop.time() >= deadline:
                    raise TimeoutError
                with locate(
                    "recording",
                    "save_initial_screenshot",
                    "screenshot_save_failed",
                    "Cannot save initial screenshot",
                ):
                    record.save_screenshot(state.screenshot)
                result.last_screenshot_id = state.screenshot.screenshot_id
                context = Context(checkpoints[0], list(config.data_values), state)
                result.checkpoints[0].state = "not_submitted"
                phase = "execution"
                assert self.agent is not None
                result.execution_outcome = await self.agent.execute(
                    context,
                    browser=browser,
                    budget=budget,
                    tool_call_limit=config.tool_call_limit,
                    record=record,
                    deadline_at=deadline,
                    request_limit=config.execution_request_limit,
                    retry_limit=config.tool_retry_limit,
                    accept_checkpoint=accept_checkpoint,
                )
                result.stop_reason = (
                    "execution_completed"
                    if all(item.submission_id for item in result.checkpoints)
                    else "execution_incomplete"
                )
            except Exception as exc:
                error = add_failure(
                    exc,
                    phase,
                    execution_operation(),
                    "deadline_exhausted"
                    if isinstance(exc, TimeoutError)
                    else "run_failed",
                    "Session operation failed",
                )
                if error.phase == "recording":
                    notify_recording_failure(error)
                result.stop_reason = (
                    "deadline_exhausted"
                    if isinstance(exc, TimeoutError)
                    else "recording_error"
                    if error.phase == "recording"
                    else phase + "_error"
                )
            finally:
                if record.failures:
                    notify_recording_failure(record.failures[0][0])

        def mark_cancelled(_exc: asyncio.CancelledError):
            nonlocal cancelled
            cancelled = True
            if (
                result.execution_outcome is None
                and not result.errors
                and not recording_failed.done()
                and result.stop_reason != "deadline_exhausted"
            ):
                result.stop_reason = "cancelled"

        async def wait_for_business(tasks: list[asyncio.Task[None]]):
            pending: set[asyncio.Future] = {task for task in tasks if not task.done()}
            while pending and not recording_failed.done() and loop.time() < deadline:
                _, pending = await asyncio.wait(
                    pending | {recording_failed},
                    timeout=deadline - loop.time(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                pending.discard(recording_failed)

        execution = asyncio.create_task(execute())
        closing = None
        try:
            await wait_for_business([execution])
            if execution.done():
                if not execution_stopped_by_recording:
                    execution.result()
                closing = start_browser_close()
                await wait_for_business([task for _, _, task in verifications])
        except asyncio.CancelledError as exc:
            mark_cancelled(exc)

        recording_failure = (
            recording_failed.result() if recording_failed.done() else None
        )
        execution_pending = not execution.done()
        deadline_reached = (
            not cancelled
            and recording_failure is None
            and (
                execution_pending
                or any(entry.verdict is None for entry, _, _ in verifications)
            )
        )
        if recording_failure is not None and (
            execution_stopped_by_recording or execution_pending
        ):
            result.stop_reason = "recording_error"
        elif deadline_reached and execution_pending:
            result.stop_reason = "deadline_exhausted"

        tasks = [execution, *(task for _, _, task in verifications)]
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        await settle(asyncio.gather(*tasks, return_exceptions=True), mark_cancelled)
        if closing is None:
            closing = start_browser_close()
        if closing is not None:
            try:
                await settle(closing, mark_cancelled)
            except asyncio.CancelledError as exc:
                mark_cancelled(exc)
            except Exception as exc:
                add_failure(
                    exc,
                    "cleanup",
                    "close_browser",
                    "close_failed",
                    "Cannot close browser",
                )

        deadline_failure = None
        if deadline_reached and (
            execution_pending
            or any(entry.verdict is None for entry, _, _ in verifications)
        ):
            deadline_failure = next(
                (
                    error
                    for error in result.errors
                    if error.code == "deadline_exhausted"
                ),
                None,
            )
            if deadline_failure is None:
                deadline_failure = add_failure(
                    TimeoutError("Session deadline exhausted"),
                    phase if execution_pending else "verification",
                    execution_operation()
                    if execution_pending
                    else "evaluate_assertions",
                    "deadline_exhausted",
                    "Session deadline exhausted",
                )

        result.action_count = budget.action_count
        if context is not None:
            result.last_screenshot_id = context.browser_state.screenshot.screenshot_id
            current_entry = result.checkpoints[current_index]
            # A registered submission can outlive a receipt that failed to publish.
            if (
                current_entry.state == "not_reached"
                and current_entry.checkpoint_id == context.checkpoint.id
            ):
                current_entry.state = "not_submitted"
        for entry, submission_record, _ in verifications:
            if entry.verdict is None:
                reason = "Session cancelled"
                failure = recording_failure or deadline_failure
                if failure is not None:
                    reason = f"{failure.message}; error_id={failure.error_id}"
                finish_verification_error(entry, submission_record.submission, reason)
                entry.state = "finished"
            for error, diagnostic in submission_record.failures:
                result.errors.append(
                    replace(
                        error,
                        checkpoint_id=entry.checkpoint_id,
                        submission_id=entry.submission_id,
                    )
                )
                diagnostics.append(diagnostic)
        for error, diagnostic in record.failures:
            if not any(item.error_id == error.error_id for item in result.errors):
                result.errors.append(error)
                diagnostics.append(diagnostic)
        if recording_failure is not None:
            # Preserve the cause of the stop ahead of failures during shutdown.
            first_recording_error = next(
                i for i, error in enumerate(result.errors) if error.phase == "recording"
            )
            primary = next(
                i
                for i, error in enumerate(result.errors)
                if error.error_id == recording_failure.error_id
            )
            result.errors.insert(first_recording_error, result.errors.pop(primary))
        if (
            not cancelled
            and not result.errors
            and result.stop_reason == "execution_completed"
        ):
            verdicts = [item.verdict for item in result.checkpoints]
            if any(verdict and verdict.status == "failed" for verdict in verdicts):
                result.status = "failed"
            elif all(verdict and verdict.status == "passed" for verdict in verdicts):
                result.status = "passed"

        def mark_save_cancelled():
            result.status = "error"
            if result.stop_reason in ("execution_completed", "execution_incomplete"):
                result.stop_reason = "cancelled"

        def cancel_during_save(exc: asyncio.CancelledError):
            mark_cancelled(exc)
            mark_save_cancelled()

        save_deadline = loop.time() + FINALIZATION_SECONDS
        saved_cancellation = cancelled
        saving = start_background_work(
            self._finish_record,
            record,
            deepcopy(result),
            started_record,
            tuple(diagnostics),
        )
        try:
            result = await settle(saving, cancel_during_save, deadline=save_deadline)
            if cancelled and not saved_cancellation:
                mark_save_cancelled()
                saving = start_background_work(
                    self._finish_record, record, deepcopy(result), None
                )
                result = await settle(
                    saving, cancel_during_save, deadline=save_deadline
                )
        except TimeoutError as exc:
            result.status = "error"
            error = add_failure(
                exc,
                "recording",
                "finalize_record",
                "finalization_timeout",
                "Record finalization exceeded deadline",
            )
            result.artifact_paths = [str(record.directory)]
            fact("diagnostic", **diagnostics[-1])
            print(f"{error.message}; error_id={error.error_id}", file=sys.stderr)
        if cancelled:
            raise SessionCancelled(result)
        return result

    @staticmethod
    def _finish_record(record, result, started_record, diagnostics=()):
        def failed(exc, operation, code, message):
            error, diagnostic = describe(exc, "recording", operation, code, message)
            result.errors.append(error)
            result.status = "error"
            fact("diagnostic", **diagnostic)
            print(f"{message}; error_id={error.error_id}", file=sys.stderr)
            if operation != "save_diagnostic":
                try:
                    record.save_diagnostic(diagnostic)
                except OSError as write_exc:
                    failed(
                        write_exc,
                        "save_diagnostic",
                        "diagnostic_save_failed",
                        "Cannot save diagnostic",
                    )

        for diagnostic in diagnostics:
            fact("diagnostic", **diagnostic)
            try:
                record.save_diagnostic(diagnostic)
            except OSError as exc:
                failed(
                    exc,
                    "save_diagnostic",
                    "diagnostic_save_failed",
                    "Cannot save diagnostic",
                )
                break
        try:
            if started_record is None:
                record.append({"type": "session_cancelled", "status": result.status})
            else:
                if not started_record:
                    record.append({"type": "session_started"})
                for error in result.errors:
                    record.append({"type": "error", **error.__dict__})
                record.append({"type": "session_finished", "status": result.status})
        except OSError as exc:
            failed(exc, "append_events", "append_failed", "Cannot append record")
        try:
            result.artifact_paths = record.finish(result, [])
        except OSError as exc:
            failed(exc, "save_result", "finish_failed", "Cannot save result")
            try:
                result.artifact_paths = [
                    p for p in record.artifact_paths if not p.endswith("/result.json")
                ]
            except OSError:
                result.artifact_paths = []
        return result
