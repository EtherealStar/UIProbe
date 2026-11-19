"""Local records with exclusive directories and atomic final results."""

import json
import sys
from collections.abc import Callable
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

from .error_handling import LocatedFailure, RunError, describe
from .observation import CheckpointSubmission, Screenshot


@contextmanager
def _writing(
    failures: list[tuple[RunError, dict]],
    operation: str,
    *,
    defer: bool = False,
    association: dict | None = None,
    notify: Callable[[RunError], None] | None = None,
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
        if notify is not None:
            notify(error)
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


class RunRecord:
    def __init__(self, directory: Path, association: dict[str, str]):
        self.directory = directory
        self.association = association
        self.trace_id: str | None = None

    @property
    def artifact_paths(self) -> list[str]:
        return [
            str(path)
            for path in sorted(self.directory.iterdir())
            if path.name not in (".result.tmp", ".trace.tmp")
        ]

    def append(self, event: dict) -> None:
        payload = {
            **event,
            **self.association,
            "trace_id": getattr(self, "trace_id", None),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _append_json(self.directory / "events.jsonl", payload)

    def save_trace(self, spans, warnings, export_status=None, diagnostics=()):
        self._write_atomically(
            "trace",
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
        )

    def save_diagnostic(self, diagnostic: dict) -> None:
        directory = self.directory / "diagnostics"
        directory.mkdir(exist_ok=True)
        (directory / f"{diagnostic['error_id']}.json").write_text(
            json.dumps({**diagnostic, **self.association}, ensure_ascii=False),
            encoding="utf-8",
        )

    def save_result(self, result) -> list[str]:
        destination = self.directory / "result.json"
        paths = [path for path in self.artifact_paths if path != str(destination)]
        paths.append(str(destination))
        payload = asdict(result)
        payload["artifact_paths"] = paths
        self._write_atomically(
            "result",
            json.dumps(
                payload,
                ensure_ascii=False,
                default=lambda value: value.model_dump(),
            ),
        )
        return paths

    def _write_atomically(self, name: str, data: str) -> None:
        temporary = self.directory / f".{name}.tmp"
        try:
            temporary.write_text(data, encoding="utf-8")
            temporary.replace(self.directory / f"{name}.json")
        finally:
            temporary.unlink(missing_ok=True)


class SuiteRecord(RunRecord):
    def __init__(self, suite_id: str, directory: Path):
        super().__init__(directory, {"suite_id": suite_id})
        self.suite_id = suite_id
        self.trace_save_confirmed = False

    @property
    def artifact_paths(self) -> list[str]:
        paths = super().artifact_paths
        if self.trace_save_confirmed:
            return paths
        return [path for path in paths if Path(path).name != "trace.json"]


class SessionRecord(RunRecord):
    def __init__(self, session_id: str, directory: Path, suite_id: str | None = None):
        association = {"session_id": session_id}
        if suite_id is not None:
            association["suite_id"] = suite_id
        super().__init__(directory, association)
        self.failures: list[tuple[RunError, dict]] = []
        self.session_id = session_id

    def writing(self, operation: str, *, defer: bool = False):
        return _writing(
            self.failures,
            operation,
            defer=defer,
            association=self.association,
        )

    def begin_submission(self, submission: CheckpointSubmission) -> "SubmissionRecord":
        if submission.session_id != self.session_id:
            raise ValueError("Submission belongs to a different session")
        record = SubmissionRecord(self, submission)
        with record.writing("create_submission_record"):
            record.directory.mkdir(parents=True, exist_ok=False)
        return record

    def save_sent_messages(self, messages, screenshot: Screenshot) -> None:
        _append_json(
            self.directory / "execution-requests.jsonl",
            _message_references(messages, screenshot),
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
            _save_json(self.directory / "history.json", history)
        return self.save_result(result)


class SubmissionRecord:
    def __init__(self, session: SessionRecord, submission: CheckpointSubmission):
        self._session = session
        self._submission = submission
        self._input_saved = False
        self.directory = session.directory / "submissions" / submission.submission_id
        self.failures: list[tuple[RunError, dict]] = []
        self.on_write_failure: Callable[[RunError], None] | None = None

    @property
    def submission(self) -> CheckpointSubmission:
        return self._submission

    @property
    def association(self) -> dict[str, str]:
        submission = self._submission
        fields = {
            **self._session.association,
            "submission_id": submission.submission_id,
        }
        if submission.checkpoint_id is not None:
            fields["checkpoint_id"] = submission.checkpoint_id
        if submission.screenshot is not None:
            fields["screenshot_id"] = submission.screenshot.screenshot_id
        return fields

    def writing(self, operation: str, *, defer: bool = False):
        return _writing(
            self.failures,
            operation,
            defer=defer,
            association=self.association,
            notify=self.on_write_failure,
        )

    def append(self, event: dict) -> None:
        self._session.append({**event, **self.association})

    def save_diagnostic(self, diagnostic: dict) -> None:
        self._session.save_diagnostic(diagnostic)

    def save_input(self) -> None:
        if self._input_saved:
            return
        _save_json(
            self.directory / "input.json",
            {
                **self.association,
                "assertions": [a.model_dump() for a in self._submission.assertions],
            },
        )

        self._input_saved = True

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
    def begin(
        self, session_id: str, output_dir: str, *, suite_id: str | None = None
    ) -> SessionRecord:
        directory = Path(output_dir).absolute() / session_id
        directory.mkdir(parents=True, exist_ok=False)
        return SessionRecord(session_id, directory, suite_id)

    def begin_suite(self, suite_id: str, output_dir: str) -> SuiteRecord:
        directory = Path(output_dir).absolute() / suite_id
        directory.mkdir(parents=True, exist_ok=False)
        return SuiteRecord(suite_id, directory)
