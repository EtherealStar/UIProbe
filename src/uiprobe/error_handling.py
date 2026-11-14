"""Error summaries and serializable diagnostics, without persistence or policy."""

import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class SessionError:
    phase: str
    code: str
    message: str
    operation: str = ""
    error_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self):
        if not self.operation:
            object.__setattr__(
                self,
                "operation",
                {
                    "invalid_input": "validate_input",
                    "begin_failed": "create_record",
                    "close_failed": "close_browser",
                    "append_failed": "append_events",
                    "finish_failed": "save_result",
                    "finalization_timeout": "finalize_record",
                    "timeout": "prepare_input",
                    "cancelled": "cancel_run",
                }.get(self.code, "run_session"),
            )


class LocatedFailure(Exception):
    def __init__(self, summary: SessionError, diagnostic: dict):
        super().__init__(summary.message)
        self.summary = summary
        self.diagnostic = diagnostic


def describe(exc: BaseException, phase: str, operation: str, code: str, message: str):
    if isinstance(exc, LocatedFailure):
        return exc.summary, exc.diagnostic
    summary = SessionError(phase, code, message, operation)
    diagnostic = {
        **summary.__dict__,
        "exception_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "exception_message": str(exc),
        "traceback": "".join(traceback.format_exception(exc)),
    }
    return summary, diagnostic


@contextmanager
def locate(phase: str, operation: str, code: str, message: str):
    try:
        yield
    except Exception as exc:
        summary, diagnostic = describe(
            exc,
            phase,
            operation,
            code,
            f"{message}: {str(exc).splitlines()[0]}" if str(exc) else message,
        )
        raise LocatedFailure(summary, diagnostic) from exc
