"""Local records with exclusive directories and atomic final results."""
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

class SessionRecord:
    def __init__(self, session_id: str, directory: Path):
        self.session_id = session_id
        self.directory = directory

    @property
    def artifact_paths(self) -> list[str]:
        return [str(path) for path in sorted(self.directory.iterdir())
                if path.name != ".result.tmp"]

    def append(self, event: dict) -> None:
        payload = {**event, "session_id": self.session_id,
                   "timestamp": datetime.now(timezone.utc).isoformat()}
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + chr(10))

    def finish(self, result, history: list) -> list[str]:
        (self.directory / "history.json").write_text(json.dumps(history), encoding="utf-8")
        paths = self.artifact_paths + [str(self.directory / "result.json")]
        payload = asdict(result)
        if result.test_case is not None:
            payload["test_case"] = result.test_case.model_dump()
        payload["artifact_paths"] = paths
        temporary = self.directory / ".result.tmp"
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.directory / "result.json")
        finally:
            temporary.unlink(missing_ok=True)
        return paths

class Recorder:
    def begin(self, session_id: str, output_dir: str) -> SessionRecord:
        directory = Path(output_dir).absolute() / session_id
        directory.mkdir(parents=True, exist_ok=False)
        return SessionRecord(session_id, directory)
