"""Run-local browser, execution and independent verification lifecycle."""

import asyncio
import math
import time
from dataclasses import dataclass, field
from uuid import uuid4

from .actions import RunBudget
from .agent import Context
from .browser import Browser
from .case_input import InputError, TestCase, prepare
from .observation import Submission, Verdict
from .recording import Recorder


@dataclass(frozen=True)
class SessionError:
    phase: str
    code: str
    message: str


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

    async def run(self, test_json: str, config: object) -> SessionResult:
        started = time.monotonic()
        result = SessionResult(uuid4().hex)
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
            except OSError:
                result.errors.append(
                    SessionError("recording", "begin_failed", "Cannot create record")
                )
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
                        record.append({"type": "session_started"})
                        started_record = True
                        browser = (self.browser_factory or Browser)()
                        state = await browser.open(
                            prepared.config.entry_url,
                            prepared.config.data_values,
                            deadline,
                        )
                        result.last_screenshot_id = state.screenshot.screenshot_id
                        record.save_screenshot(state.screenshot)
                        context = Context(
                            prepared.test_case, list(prepared.config.data_values), state
                        )
                        phase = "execution"
                        assert self.agent is not None and self.verification is not None
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
                    result.errors.append(
                        SessionError(
                            "recording"
                            if isinstance(exc, OSError)
                            and not isinstance(exc, TimeoutError)
                            else phase,
                            "run_failed",
                            "Session phase failed",
                        )
                    )
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
                        except Exception:
                            result.errors.append(
                                SessionError(
                                    "cleanup", "close_failed", "Cannot close browser"
                                )
                            )
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
            try:
                if not started_record:
                    record.append({"type": "session_started"})
                for error in result.errors:
                    record.append({"type": "error", **error.__dict__})
                record.append({"type": "session_finished", "status": result.status})
            except OSError:
                result.status = "error"
                result.errors.append(
                    SessionError("recording", "append_failed", "Cannot append record")
                )
            try:
                result.artifact_paths = record.finish(result, [])
            except OSError:
                result.status = "error"
                result.errors.append(
                    SessionError("recording", "finish_failed", "Cannot save result")
                )
                try:
                    result.artifact_paths = record.artifact_paths
                except OSError:
                    result.artifact_paths = []
        if cancelled:
            raise asyncio.CancelledError
        return result
