import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from uiprobe.case_input import InputError, PreparedSession, prepare
from uiprobe.recording import Recorder, SessionRecord
from uiprobe.session import Session


def case():
    return {
        "execution": {"goal": "Login", "instructions": []},
        "assertions": [{"id": "home", "expected": "Home visible"}],
    }


def config(directory: str) -> dict[str, object]:
    return dict(
        entry_url="http://127.0.0.1/login",
        data_values={"password": "secret-value"},
        max_actions=10,
        execution_request_limit=20,
        verification_request_limit=3,
        tool_call_limit=30,
        tool_retry_limit=2,
        verification_retry_limit=2,
        timeout_seconds=60,
        output_dir=directory,
    )


class InputTests(unittest.TestCase):
    def test_valid_input(self):
        prepared = prepare(json.dumps(case()), config("/tmp/runs"))
        assert isinstance(prepared, PreparedSession)
        self.assertEqual(prepared.test_case.assertions[0].id, "home")

    def test_aggregate_and_safe_errors(self):
        value = case()
        value["execution"]["goal"] = " "
        value["assertions"].append({"id": "home", "expected": ""})
        value["secret-field"] = "secret-value"
        cfg = config("/tmp/runs")
        cfg["max_actions"] = True
        error = prepare(json.dumps(value), cfg)
        assert isinstance(error, InputError)
        paths = {item.path for item in error.errors}
        self.assertTrue(
            {
                "execution.goal",
                "assertions[1].expected",
                "assertions[1].id",
                "config.max_actions",
            }
            <= paths
        )
        self.assertNotIn("secret", repr(error))

    def test_data_reference_names_are_not_echoed_on_failure(self):
        cfg = config("/tmp/runs")
        cfg["data_values"] = {"secret-key": 123}
        error = prepare("{}", cfg)
        self.assertNotIn("secret-key", repr(error))

    def test_unknown_field_with_dots_is_not_echoed(self):
        value = case()
        value["execution"]["secret.value"] = 1
        self.assertNotIn(
            "secret", repr(prepare(json.dumps(value), config("/tmp/runs")))
        )

    def test_invalid_json_does_not_echo_input(self):
        error = prepare('{"secret-value":', config("/tmp/runs"))
        assert isinstance(error, InputError)
        self.assertEqual(
            [(e.path, e.reason) for e in error.errors], [("test_json", "invalid_json")]
        )

    def test_strict_config_and_nested_fields(self):
        for field in (
            "max_actions",
            "execution_request_limit",
            "verification_request_limit",
            "tool_call_limit",
            "tool_retry_limit",
            "verification_retry_limit",
        ):
            for value in (True, "2", 0, -1):
                with self.subTest(field=field, value=value):
                    cfg = config("/tmp/runs")
                    cfg[field] = value
                    self.assertIsInstance(prepare(json.dumps(case()), cfg), InputError)
        for field, value in (
            ("timeout_seconds", True),
            ("timeout_seconds", float("inf")),
            ("output_dir", ""),
            ("entry_url", "file:///tmp/page"),
        ):
            cfg = config("/tmp/runs")
            cfg[field] = value
            self.assertIsInstance(prepare(json.dumps(case()), cfg), InputError)
        for value in (
            [],
            {},
            {
                "execution": {"goal": "ok", "instructions": [], "extra": 1},
                "assertions": [],
            },
        ):
            self.assertIsInstance(
                prepare(json.dumps(value), config("/tmp/runs")), InputError
            )


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_error_artifacts_and_no_external_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            browser, agent, verifier = Mock(), Mock(), Mock()
            session = Session(
                browser_factory=browser, agent=agent, verification=verifier
            )
            first = await session.run('{"secret-value":', config(directory))
            second = await session.run("{}", config(directory))
            self.assertNotEqual(first.session_id, second.session_id)
            self.assertEqual(first.status, "error")
            self.assertIsNone(first.test_case)
            self.assertEqual(first.action_count, 0)
            self.assertIsNone(first.verdict)
            browser.assert_not_called()
            agent.assert_not_called()
            verifier.assert_not_called()
            for path in first.artifact_paths:
                self.assertTrue(Path(path).exists())
                self.assertNotIn("secret-value", Path(path).read_text())
            saved = json.loads(
                (Path(directory) / first.session_id / "result.json").read_text()
            )
            self.assertEqual(saved["artifact_paths"], first.artifact_paths)
            events = [
                json.loads(line)
                for line in (Path(directory) / first.session_id / "events.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertTrue(
                all(
                    e["session_id"] == first.session_id and e["timestamp"]
                    for e in events
                )
            )

    async def test_invalid_directory_and_unwritable_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "file"
            parent.write_text("keep")
            for output in ("", str(parent)):
                result = await Session().run("{}", config(output))
                self.assertEqual(result.status, "error")
                self.assertEqual(result.artifact_paths, [])
            self.assertEqual(parent.read_text(), "keep")

    async def test_conflict_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Recorder().begin("fixed", directory)
            marker = record.directory / "keep"
            marker.write_text("original")
            with patch("uiprobe.session.uuid4") as identifier:
                identifier.return_value.hex = "fixed"
                result = await Session().run("{}", config(directory))
            self.assertEqual(marker.read_text(), "original")
            self.assertEqual(result.artifact_paths, [])
            self.assertIn("begin_failed", [e.code for e in result.errors])

    async def test_finish_failure_returns_only_existing_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("pathlib.Path.replace", side_effect=OSError("secret-value")):
                result = await Session().run("{}", config(directory))
            self.assertIn("finish_failed", [e.code for e in result.errors])
            self.assertTrue(all(Path(p).exists() for p in result.artifact_paths))
            self.assertFalse(
                any(Path(p).name == "result.json" for p in result.artifact_paths)
            )
            self.assertNotIn("secret-value", repr(result))
            self.assertFalse(
                (Path(directory) / result.session_id / ".result.tmp").exists()
            )

    async def test_missing_record_directory_returns_memory_result(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(SessionRecord, "finish", side_effect=OSError()),
                patch("pathlib.Path.iterdir", side_effect=OSError()),
            ):
                result = await Session().run("{}", config(directory))
            self.assertEqual(result.artifact_paths, [])
            self.assertIn("finish_failed", [e.code for e in result.errors])

    async def test_oversized_timeout_returns_input_error(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(directory)
            cfg["timeout_seconds"] = 10**1000
            result = await Session().run("{}", cfg)
            self.assertIn("config.timeout_seconds", repr(result.errors))

    async def test_append_failure_still_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                SessionRecord, "append", side_effect=OSError("secret-value")
            ):
                result = await Session().run("{}", config(directory))
            self.assertIn("append_failed", [e.code for e in result.errors])
            saved = json.loads(
                (Path(directory) / result.session_id / "result.json").read_text()
            )
            self.assertIn("append_failed", [e["code"] for e in saved["errors"]])
