"""Local records with exclusive directories and atomic final results."""

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from pydantic_ai.messages import (
    BinaryContent,
    ModelMessagesTypeAdapter,
    ModelRequest,
    UserPromptPart,
)

from .case_input import TestCase
from .observation import Screenshot


class SessionRecord:
    def __init__(self, session_id: str, directory: Path):
        self.trace_id: str | None = None
        self.session_id = session_id
        self.directory = directory

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
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + chr(10))

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

    def save_sent_messages(self, role, messages, screenshot):
        # Reuse native serialization and screenshot references without replacing history.
        payload = json.loads(ModelMessagesTypeAdapter.dump_json(messages))

        def references(value):
            if isinstance(value, dict):
                if value.get("kind") == "binary":
                    return {
                        "kind": "screenshot",
                        "screenshot_id": screenshot.screenshot_id,
                    }
                return {k: references(v) for k, v in value.items()}
            if isinstance(value, list):
                return [references(v) for v in value]
            return value

        with (self.directory / f"{role}-requests.jsonl").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(json.dumps(references(payload), ensure_ascii=False) + "\n")

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

    def save_verification_input(
        self, case: TestCase, screenshot: Screenshot | None
    ) -> None:
        self.verification_input = {
            "assertions": [a.model_dump() for a in case.assertions],
            "screenshot_id": screenshot.screenshot_id if screenshot else None,
        }

    def save_messages(self, role: str, messages, screenshot: Screenshot | None) -> None:
        image_ids = iter(
            [
                item.identifier
                if item.identifier.startswith("screen-")
                else (screenshot.screenshot_id if screenshot else None)
                for message in messages
                if isinstance(message, ModelRequest)
                for part in message.parts
                if isinstance(part, UserPromptPart) and isinstance(part.content, list)
                for item in part.content
                if isinstance(item, BinaryContent)
            ]
        )
        payload = json.loads(ModelMessagesTypeAdapter.dump_json(messages))

        def references(value):
            if isinstance(value, dict):
                if value.get("kind") == "binary":
                    return {
                        "kind": "screenshot",
                        "screenshot_id": next(
                            image_ids, screenshot.screenshot_id if screenshot else None
                        ),
                    }
                return {k: references(v) for k, v in value.items()}
            if isinstance(value, list):
                return [references(v) for v in value]
            return value

        data = references(payload)
        if role == "verification":
            data = {"input": self.verification_input, "messages": data}
        (
            self.directory
            / ("verification.json" if role == "verification" else "history.json")
        ).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

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


class Recorder:
    def begin(self, session_id: str, output_dir: str) -> SessionRecord:
        directory = Path(output_dir).absolute() / session_id
        directory.mkdir(parents=True, exist_ok=False)
        return SessionRecord(session_id, directory)
