"""The M1 input failure path; later milestones add browser execution."""

import math
import time
from dataclasses import dataclass, field
from uuid import uuid4

from .case_input import InputError, TestCase, prepare
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
    submission: None = None
    action_count: int = 0
    last_screenshot_id: str | None = None
    verdict: None = None
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
            result.stop_reason = "execution_unavailable"
            result.errors.append(
                SessionError(
                    "execution",
                    "not_implemented",
                    "Browser execution is not implemented in M1",
                )
            )
        if deadline is not None and time.monotonic() >= deadline:
            result.errors.append(
                SessionError("input", "timeout", "Input preparation exceeded deadline")
            )
        if record is not None:
            try:
                record.append({"type": "session_started"})
                for error in result.errors:
                    record.append({"type": "error", **error.__dict__})
                record.append({"type": "session_finished", "status": result.status})
            except OSError:
                result.errors.append(
                    SessionError("recording", "append_failed", "Cannot append record")
                )
            try:
                result.artifact_paths = record.finish(result, [])
            except OSError:
                result.errors.append(
                    SessionError("recording", "finish_failed", "Cannot save result")
                )
                try:
                    result.artifact_paths = record.artifact_paths
                except OSError:
                    result.artifact_paths = []
        return result
