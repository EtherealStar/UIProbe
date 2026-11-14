"""Run-local browser, execution and independent verification lifecycle."""

import asyncio
import math
import time
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import uuid4

from .actions import RunBudget
from .agent import Context
from .browser import Browser
from .case_input import InputError, TestCase, prepare
from .error_handling import SessionError, describe, locate
from .observability import bind_record, fact, traced
from .observation import Submission, Verdict
from .recording import Recorder


@dataclass
class SessionResult:
    session_id: str
    test_case: TestCase | None = None
    status: str = "error"
    stop_reason: str = "input_error"
    submission: Submission | None = None
    action_count: int = 0
    last_screenshot_id: str | None = None
    verdict: Verdict | None = None
    artifact_paths: list[str] = field(default_factory=list)
    errors: list[SessionError] = field(default_factory=list)


class Session:
    def __init__(
        self, *, recorder=None, browser_factory=None, agent=None, verification=None
    ):
        self.recorder = recorder if recorder is not None else Recorder()
        self.browser_factory = browser_factory
        self.agent = agent
        self.verification = verification

    @traced("session")
    async def run(self, test_json: str, config: object) -> SessionResult:
        started = time.monotonic()
        result = SessionResult(uuid4().hex)
        diagnostics = []
        record = None
        cancelled = False
        started_record = False
        timeout = config.get("timeout_seconds") if isinstance(config, dict) else None
        try:
            deadline = (
                started + timeout
                if isinstance(timeout, (int, float))
                and type(timeout) in (int, float)
                and math.isfinite(timeout)
                and timeout > 0
                else None
            )
        except OverflowError:
            deadline = None
        output_dir = config.get("output_dir") if isinstance(config, dict) else None
        if (
            isinstance(output_dir, str)
            and output_dir.strip()
            and chr(0) not in output_dir
        ):
            try:
                record = self.recorder.begin(result.session_id, output_dir)
                bind_record(record)
            except OSError as exc:
                error, diagnostic = describe(
                    exc,
                    "recording",
                    "create_record",
                    "begin_failed",
                    "Cannot create record",
                )
                result.errors.append(error)
                diagnostics.append(diagnostic)
        prepared = prepare(test_json, config)
        if isinstance(prepared, InputError):
            result.errors.extend(
                SessionError("input", "invalid_input", f"{e.path}: {e.reason}")
                for e in prepared.errors
            )
        else:
            result.test_case = prepared.test_case
            browser = None
            context = None
            budget = RunBudget(
                deadline if deadline is not None else started,
                prepared.config.max_actions,
            )
            if record is not None and not result.errors:
                phase = "initialization"
                try:
                    assert deadline is not None
                    async with asyncio.timeout_at(deadline):
                        with locate(
                            "recording",
                            "append_events",
                            "append_failed",
                            "Cannot append record",
                        ):
                            record.append({"type": "session_started"})
                        started_record = True
                        if time.monotonic() >= deadline:
                            raise TimeoutError
                        browser = (self.browser_factory or Browser)()
                        state = await browser.open(
                            prepared.config.entry_url,
                            prepared.config.data_values,
                            deadline,
                        )
                        result.last_screenshot_id = state.screenshot.screenshot_id
                        with locate(
                            "recording",
                            "save_initial_screenshot",
                            "screenshot_save_failed",
                            "Cannot save initial screenshot",
                        ):
                            record.save_screenshot(state.screenshot)
                        context = Context(
                            prepared.test_case, list(prepared.config.data_values), state
                        )
                        phase = "execution"
                        assert self.agent is not None and self.verification is not None
                        if time.monotonic() >= deadline:
                            raise TimeoutError
                        result.submission = await self.agent.execute(
                            context,
                            browser=browser,
                            budget=budget,
                            tool_call_limit=prepared.config.tool_call_limit,
                            record=record,
                            deadline_at=deadline,
                            request_limit=prepared.config.execution_request_limit,
                            retry_limit=prepared.config.tool_retry_limit,
                        )
                        assert result.submission is not None
                        record.append(
                            {"type": "submission", "text": result.submission.text}
                        )
                        phase = "verification"
                        if time.monotonic() >= deadline:
                            raise TimeoutError
                        result.verdict = await self.verification.evaluate(
                            prepared.test_case,
                            context.browser_state.screenshot,
                            deadline,
                            record=record,
                            request_limit=prepared.config.verification_request_limit,
                            retry_limit=prepared.config.verification_retry_limit,
                        )
                        assert result.verdict is not None
                        result.status = result.verdict.status
                        result.stop_reason = "verification_completed"
                except asyncio.CancelledError:
                    result.stop_reason = "cancelled"
                    cancelled = True
                    result.errors.append(
                        SessionError(phase, "cancelled", "Session cancelled")
                    )
                except Exception as exc:
                    result.stop_reason = phase + "_error"
                    error, diagnostic = describe(
                        exc,
                        phase,
                        {
                            "initialization": (
                                getattr(
                                    browser,
                                    "initialization_operation",
                                    "launch_browser",
                                )
                                if isinstance(browser, Browser)
                                else "open_browser"
                            ),
                            "execution": "execute_agent",
                            "verification": "evaluate_assertions",
                        }[phase],
                        "deadline_exhausted"
                        if isinstance(exc, TimeoutError)
                        else "run_failed",
                        "Session operation failed",
                    )
                    if record is not None:
                        # Verification may already have caught its model failure.
                        # Evidence writes must follow that original failure.
                        for deferred_error, deferred_diagnostic in record.failures:
                            if deferred_error.phase != "recording":
                                result.errors.append(deferred_error)
                                diagnostics.append(deferred_diagnostic)
                    result.errors.append(error)
                    diagnostics.append(diagnostic)
                finally:
                    result.action_count = budget.action_count
                    if context is not None:
                        result.last_screenshot_id = (
                            context.browser_state.screenshot.screenshot_id
                        )
                    if browser is not None:
                        try:
                            async with asyncio.timeout(5):
                                await browser.close()
                        except (Exception, asyncio.CancelledError) as exc:
                            if isinstance(exc, asyncio.CancelledError):
                                cancelled = True
                            error, diagnostic = describe(
                                exc,
                                "cleanup",
                                "close_browser",
                                "close_failed",
                                "Cannot close browser",
                            )
                            result.errors.append(error)
                            diagnostics.append(diagnostic)
                    if result.errors:
                        result.status = "error"
        if (
            isinstance(prepared, InputError)
            and deadline is not None
            and time.monotonic() >= deadline
        ):
            result.errors.append(
                SessionError("input", "timeout", "Input preparation exceeded deadline")
            )
        if record is not None:
            for error, diagnostic in record.failures:
                if not any(e.error_id == error.error_id for e in result.errors):
                    result.errors.append(error)
                    diagnostics.append(diagnostic)
            if result.errors:
                result.status = "error"
        for error in result.errors:
            if not any(d["error_id"] == error.error_id for d in diagnostics):
                diagnostics.append(
                    {
                        **error.__dict__,
                        "exception_type": None,
                        "exception_message": None,
                        "traceback": None,
                    }
                )
        if record is not None:
            snapshot = deepcopy(result)
            saving = asyncio.create_task(
                asyncio.to_thread(
                    self._finish_record, record, snapshot, started_record, diagnostics
                )
            )
            try:
                async with asyncio.timeout(5):
                    result = await asyncio.shield(saving)
            except asyncio.CancelledError:
                cancelled = True
                result.status = "error"
                result.stop_reason = "cancelled"
                result.errors.append(
                    SessionError("recording", "cancelled", "Session cancelled")
                )
                try:
                    async with asyncio.timeout(5):
                        await asyncio.shield(saving)
                        result = await asyncio.to_thread(
                            self._finish_record,
                            record,
                            deepcopy(result),
                            True,
                            diagnostics,
                        )
                except (TimeoutError, asyncio.CancelledError):
                    pass
            except TimeoutError:
                result.status = "error"
                result.errors.append(
                    SessionError(
                        "recording",
                        "finalization_timeout",
                        "Record finalization exceeded deadline",
                    )
                )
                result.artifact_paths = [str(record.directory)]
        if cancelled:
            raise asyncio.CancelledError
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
