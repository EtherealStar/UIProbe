"""Run-local browser, execution and independent verification lifecycle."""

import asyncio
from contextvars import copy_context
from copy import deepcopy
from dataclasses import dataclass, field, replace
from uuid import uuid4

from .actions import CheckpointRejected, RunBudget
from .agent import Context
from .browser import Browser
from .case_input import PreparedCase, TestCase
from .error_handling import RunError, describe, locate
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

        async def close_browser():
            if browser is None:
                return
            try:
                async with asyncio.timeout(5):
                    await browser.close()
            except Exception as exc:
                add_failure(
                    exc,
                    "cleanup",
                    "close_browser",
                    "close_failed",
                    "Cannot close browser",
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
                async with asyncio.timeout_at(deadline), verification_slots:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError
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

        try:
            async with asyncio.timeout_at(deadline):
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
        except asyncio.CancelledError:
            cancelled = True
            result.stop_reason = "cancelled"
        except Exception as exc:
            operation = "execute_agent"
            if phase == "initialization":
                current_operation = getattr(browser, "initialization_operation", None)
                operation = (
                    current_operation
                    if isinstance(current_operation, str)
                    else "open_browser"
                )
            error = add_failure(
                exc,
                phase,
                operation,
                "deadline_exhausted" if isinstance(exc, TimeoutError) else "run_failed",
                "Session operation failed",
            )
            result.stop_reason = (
                "deadline_exhausted"
                if isinstance(exc, TimeoutError)
                else "recording_error"
                if error.phase == "recording"
                else phase + "_error"
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
        closing = asyncio.create_task(close_browser())
        tasks = [task for _, _, task in verifications]
        recording_failure = next(
            (
                error
                for error in [*result.errors, *(error for error, _ in record.failures)]
                if error.phase == "recording"
            ),
            None,
        )
        if cancelled or recording_failure is not None:
            for task in tasks:
                task.cancel()
        try:
            await asyncio.gather(
                *tasks, return_exceptions=cancelled or recording_failure is not None
            )
            await asyncio.shield(closing)
        except asyncio.CancelledError:
            cancelled = True
            if result.stop_reason != "execution_completed":
                result.stop_reason = "cancelled"
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.shield(closing)
        for entry, submission_record, _ in verifications:
            if entry.verdict is None:
                reason = "Session cancelled"
                if recording_failure is not None and not cancelled:
                    reason = f"{recording_failure.message}; error_id={recording_failure.error_id}"
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

        saving = asyncio.create_task(
            asyncio.to_thread(
                self._finish_record,
                record,
                deepcopy(result),
                started_record,
                tuple(diagnostics),
            )
        )
        try:
            async with asyncio.timeout(5):
                result = await asyncio.shield(saving)
        except asyncio.CancelledError:
            cancelled = True
            result.status = "error"
            result.stop_reason = "cancelled"
            try:
                async with asyncio.timeout(5):
                    saved = await asyncio.shield(saving)
                    saved.status = "error"
                    saved.stop_reason = "cancelled"
                    result = await asyncio.to_thread(
                        self._finish_record, record, deepcopy(saved), True
                    )
            except (TimeoutError, asyncio.CancelledError):
                pass
        except TimeoutError as exc:
            result.status = "error"
            add_failure(
                exc,
                "recording",
                "finalize_record",
                "finalization_timeout",
                "Record finalization exceeded deadline",
            )
            result.artifact_paths = [str(record.directory)]
        if cancelled:
            raise SessionCancelled(result)
        return result

    @staticmethod
    def _finish_record(record, result, started_record, diagnostics=()):
        def failed(exc, operation, code, message):
            import sys

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
