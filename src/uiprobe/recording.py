"""Local records with exclusive directories and atomic final results."""

import json
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from pydantic_ai.messages import (
    BinaryContent,
    ModelMessagesTypeAdapter,
    ModelRequest,
    UserPromptPart,
)

from .error_handling import LocatedFailure, SessionError, describe
from .observation import CheckpointSubmission, Screenshot


@contextmanager
def _writing(
    failures: list[tuple[SessionError, dict]],
    operation: str,
    *,
    defer: bool = False,
    association: dict | None = None,
):
    """Keep a primary exception while collecting failures of its evidence writes."""
    primary = sys.exception()
    try:
        yield
    except OSError as exc:
        error, diagnostic = describe(
            exc, "recording", operation, "write_failed", f"Cannot {operation}"
        )
        if association is not None:
            diagnostic.update(association)
        if primary is None and not defer:
            raise LocatedFailure(error, diagnostic) from exc
        failures.append((error, diagnostic))
        print(f"{error.message}; error_id={error.error_id}", file=sys.stderr)


def _message_references(messages, screenshot: Screenshot | None):
    screenshot_id = screenshot.screenshot_id if screenshot else None
    image_ids = iter(
        [
            item.identifier if item.identifier.startswith("screen-") else screenshot_id
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, list)
            for item in part.content
            if isinstance(item, BinaryContent)
        ]
    )

    def references(value):
        if isinstance(value, dict):
            if value.get("kind") == "binary":
                return {
                    "kind": "screenshot",
                    "screenshot_id": next(image_ids, screenshot_id),
                }
            return {k: references(v) for k, v in value.items()}
        if isinstance(value, list):
            return [references(v) for v in value]
        return value

    return references(json.loads(ModelMessagesTypeAdapter.dump_json(messages)))


def _append_json(path: Path, payload) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _save_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class SessionRecord:
    def __init__(self, session_id: str, directory: Path):
        self.failures: list[tuple[SessionError, dict]] = []
        self.trace_id: str | None = None
        self.session_id = session_id
        self.directory = directory

    def writing(self, operation: str, *, defer: bool = False):
        return _writing(self.failures, operation, defer=defer)

    def begin_submission(self, submission: CheckpointSubmission) -> "SubmissionRecord":
        if submission.session_id != self.session_id:
            raise ValueError("Submission belongs to a different session")
        record = SubmissionRecord(self, submission)
        with record.writing("create_submission_record"):
            record.directory.mkdir(parents=True, exist_ok=False)
        return record

    @property
    def artifact_paths(self) -> list[str]:
        return [
            str(path)
            for path in sorted(self.directory.iterdir())
            if path.name != ".result.tmp"
        ]

    def append(self, event: dict) -> None:
        payload = {
            **event,
            "session_id": self.session_id,
            "trace_id": getattr(self, "trace_id", None),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _append_json(self.directory / "events.jsonl", payload)

    def save_trace(self, spans, warnings, export_status=None, diagnostics=()):
        (self.directory / "trace.json").write_text(
            json.dumps(
                {
                    "trace_id": self.trace_id,
                    "spans": spans,
                    "warnings": warnings,
                    "export": export_status,
                    "observability_diagnostics": diagnostics,
                    "observability_incomplete": bool(warnings),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def save_sent_messages(self, messages, screenshot: Screenshot) -> None:
        _append_json(
            self.directory / "execution-requests.jsonl",
            _message_references(messages, screenshot),
        )

    def save_diagnostic(self, diagnostic: dict) -> None:
        directory = self.directory / "diagnostics"
        directory.mkdir(exist_ok=True)
        (directory / f"{diagnostic['error_id']}.json").write_text(
            json.dumps(diagnostic, ensure_ascii=False), encoding="utf-8"
        )

    def save_screenshot(self, screenshot: Screenshot) -> None:
        directory = self.directory / "screenshots"
        directory.mkdir(exist_ok=True)
        (directory / f"{screenshot.screenshot_id}.png").write_bytes(screenshot.png)
        self.append({"type": "observation", "screenshot_id": screenshot.screenshot_id})

    def save_messages(self, messages, screenshot: Screenshot) -> None:
        _save_json(
            self.directory / "history.json", _message_references(messages, screenshot)
        )

    def finish(self, result, history: list) -> list[str]:
        if not (self.directory / "history.json").exists():
            (self.directory / "history.json").write_text(
                json.dumps(history), encoding="utf-8"
            )
        paths = self.artifact_paths + [str(self.directory / "result.json")]
        payload = asdict(result)
        if result.test_case is not None:
            payload["test_case"] = result.test_case.model_dump()
        payload["artifact_paths"] = paths
        temporary = self.directory / ".result.tmp"
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            temporary.replace(self.directory / "result.json")
        finally:
            temporary.unlink(missing_ok=True)
        return paths


class SubmissionRecord:
    def __init__(self, session: SessionRecord, submission: CheckpointSubmission):
        self._session = session
        self._submission = submission
        self.directory = session.directory / "submissions" / submission.submission_id
        self.failures: list[tuple[SessionError, dict]] = []

    @property
    def submission(self) -> CheckpointSubmission:
        return self._submission

    @property
    def association(self) -> dict[str, str]:
        submission = self._submission
        fields = {
            "session_id": submission.session_id,
            "submission_id": submission.submission_id,
        }
        if submission.checkpoint_id is not None:
            fields["checkpoint_id"] = submission.checkpoint_id
        if submission.screenshot is not None:
            fields["screenshot_id"] = submission.screenshot.screenshot_id
        return fields

    def writing(self, operation: str, *, defer: bool = False):
        return _writing(
            self.failures, operation, defer=defer, association=self.association
        )

    def append(self, event: dict) -> None:
        self._session.append({**event, **self.association})

    def save_diagnostic(self, diagnostic: dict) -> None:
        self._session.save_diagnostic(diagnostic)

    def save_input(self) -> None:
        _save_json(
            self.directory / "input.json",
            {
                **self.association,
                "assertions": [a.model_dump() for a in self._submission.assertions],
            },
        )

    def save_messages(self, messages) -> None:
        _save_json(
            self.directory / "history.json",
            _message_references(messages, self._submission.screenshot),
        )

    def save_sent_messages(self, messages) -> None:
        _append_json(
            self.directory / "requests.jsonl",
            _message_references(messages, self._submission.screenshot),
        )


class Recorder:
    def begin(self, session_id: str, output_dir: str) -> SessionRecord:
        directory = Path(output_dir).absolute() / session_id
        directory.mkdir(parents=True, exist_ok=False)
        return SessionRecord(session_id, directory)
