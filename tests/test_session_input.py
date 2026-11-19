import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from input_fixtures import case, config

from uiprobe.case_input import prepare_suite
from uiprobe.recording import Recorder, SuiteRecord
from uiprobe.suite_runner import SuiteRunner


class InputTests(unittest.TestCase):
    def test_valid_input(self):
        prepared = prepare_suite(json.dumps(case()), {"defaults": config("/tmp/runs")})
        entry = prepared.entries[0].prepared
        assert entry is not None
        self.assertEqual(entry.test_case.checkpoints[0].assertions[0].id, "home")

    def test_aggregate_and_safe_errors(self):
        value = case()
        checkpoint = value["checkpoints"][0]
        checkpoint["execution"]["goal"] = " "
        checkpoint["assertions"].append({"id": "home", "expected": ""})
        value["secret-field"] = "secret-value"
        cfg = config("/tmp/runs")
        cfg["max_actions"] = True
        result = prepare_suite(json.dumps(value), {"defaults": cfg})
        error = result.entries[0].error
        assert error is not None
        self.assertEqual(
            {item.path for item in [*error.errors, *result.errors]},
            {
                "cases[0]",
                "cases[0].checkpoints[0].execution.goal",
                "cases[0].checkpoints[0].assertions[0].id",
                "cases[0].checkpoints[0].assertions[1].expected",
                "cases[0].checkpoints[0].assertions[1].id",
                "config.defaults.max_actions",
            },
        )
        self.assertNotIn("secret", repr(result))

    def test_data_reference_names_are_not_echoed_on_failure(self):
        cfg = config("/tmp/runs")
        cfg["data_values"] = {"secret-key": 123}
        result = prepare_suite("{}", {"defaults": cfg})
        self.assertNotIn("secret-key", repr(result))
        self.assertEqual(result.errors[0].path, "config.defaults.data_values")

    def test_unknown_field_with_dots_is_not_echoed(self):
        value = case()
        value["checkpoints"][0]["execution"]["secret.value"] = 1
        result = prepare_suite(json.dumps(value), {"defaults": config("/tmp/runs")})
        self.assertNotIn("secret", repr(result))
        self.assertIsNotNone(result.entries[0].error)

    def test_invalid_json_does_not_echo_input(self):
        result = prepare_suite('{"secret-value":', {"defaults": config("/tmp/runs")})
        self.assertEqual(
            [(e.path, e.reason) for e in result.errors],
            [("source", "invalid_json_source")],
        )

    def test_strict_config_and_nested_fields(self):
        for field in (
            "max_actions",
            "execution_request_limit",
            "verification_request_limit",
            "tool_call_limit",
            "tool_retry_limit",
            "verification_retry_limit",
            "verification_concurrency",
        ):
            for value in (True, "2", 0, -1):
                with self.subTest(field=field, value=value):
                    cfg = config("/tmp/runs")
                    cfg[field] = value
                    self.assertTrue(
                        prepare_suite(json.dumps(case()), {"defaults": cfg}).errors
                    )
        for field, value in (
            ("timeout_seconds", True),
            ("timeout_seconds", float("inf")),
            ("output_dir", ""),
            ("entry_url", "file:///tmp/page"),
            ("entry_url", "http://%"),
            ("entry_url", "http://999.999.999.999"),
        ):
            cfg = config("/tmp/runs")
            cfg[field] = value
            self.assertTrue(prepare_suite(json.dumps(case()), {"defaults": cfg}).errors)
        self.assertTrue(prepare_suite("[]", {"defaults": config("/tmp/runs")}).errors)
        for value in (
            {},
            {
                "execution": {"goal": "ok", "instructions": [], "extra": 1},
                "assertions": [],
            },
        ):
            result = prepare_suite(json.dumps(value), {"defaults": config("/tmp/runs")})
            self.assertIsNotNone(result.entries[0].error)

    def test_escaped_surrogates_cannot_form_case_identifiers(self):
        value = {**case(), "id": chr(0xD800)}
        result = prepare_suite(json.dumps(value), {"defaults": config("/tmp/runs")})
        entry = result.entries[0]
        self.assertIsNone(entry.case_id)
        self.assertIsNone(entry.prepared)
        self.assertIsNotNone(entry.error)


class SuiteRecordTests(unittest.IsolatedAsyncioTestCase):
    async def test_error_artifacts_and_no_external_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            browser, service = Mock(), Mock()
            runner = SuiteRunner(service, browser_factory=browser)
            cfg = {"defaults": config(directory)}
            first = await runner.run('{"secret-value":', cfg)
            second = await runner.run("{}", cfg)
            self.assertNotEqual(first.suite_id, second.suite_id)
            self.assertEqual(first.status, "error")
            self.assertEqual(first.cases, [])
            self.assertIsNone(second.cases[0].session_result)
            browser.assert_not_called()
            service.assert_not_called()
            for path in first.artifact_paths:
                self.assertTrue(Path(path).exists())
                files = (
                    Path(path).rglob("*.json") if Path(path).is_dir() else [Path(path)]
                )
                for artifact in files:
                    self.assertNotIn("secret-value", artifact.read_text())
            run = Path(directory) / first.suite_id
            saved = json.loads((run / "result.json").read_text())
            self.assertEqual(saved["artifact_paths"], first.artifact_paths)
            events = [
                json.loads(line)
                for line in (run / "events.jsonl").read_text().splitlines()
            ]
            self.assertTrue(
                all(e["suite_id"] == first.suite_id and e["timestamp"] for e in events)
            )

    async def test_invalid_directory_and_unwritable_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "file"
            parent.write_text("keep")
            for output in ("", str(parent)):
                result = await SuiteRunner(Mock()).run(
                    "{}", {"defaults": config(output)}
                )
                self.assertEqual(result.status, "error")
                self.assertEqual(result.artifact_paths, [])
            self.assertEqual(parent.read_text(), "keep")

    async def test_conflict_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Recorder().begin_suite("fixed", directory)
            marker = record.directory / "keep"
            marker.write_text("original")
            with patch("uiprobe.suite_runner.uuid4") as identifier:
                identifier.return_value.hex = "fixed"
                result = await SuiteRunner(Mock()).run(
                    "{}", {"defaults": config(directory)}
                )
            self.assertEqual(marker.read_text(), "original")
            self.assertEqual(result.artifact_paths, [])
            self.assertIn("begin_failed", [e.code for e in result.errors])

    async def test_finish_failure_returns_only_existing_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("pathlib.Path.replace", side_effect=OSError("secret-value")):
                result = await SuiteRunner(Mock()).run(
                    "{}", {"defaults": config(directory)}
                )
            self.assertIn("finish_failed", [e.code for e in result.errors])
            self.assertTrue(all(Path(p).exists() for p in result.artifact_paths))
            self.assertFalse(
                any(Path(p).name == "result.json" for p in result.artifact_paths)
            )
            self.assertNotIn("secret-value", repr(result))
            self.assertFalse(
                (Path(directory) / result.suite_id / ".result.tmp").exists()
            )

    async def test_missing_record_directory_returns_memory_result(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(SuiteRecord, "save_result", side_effect=OSError()),
                patch("pathlib.Path.iterdir", side_effect=OSError()),
            ):
                result = await SuiteRunner(Mock()).run(
                    "{}", {"defaults": config(directory)}
                )
            self.assertEqual(result.artifact_paths, [])
            self.assertIn("finish_failed", [e.code for e in result.errors])

    async def test_oversized_timeout_returns_input_error(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(directory)
            cfg["timeout_seconds"] = 10**1000
            result = await SuiteRunner(Mock()).run("{}", {"defaults": cfg})
            self.assertIn("config.defaults.timeout_seconds", repr(result.errors))

    async def test_append_failure_still_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                SuiteRecord, "append", side_effect=OSError("secret-value")
            ):
                result = await SuiteRunner(Mock()).run(
                    "{}", {"defaults": config(directory)}
                )
            self.assertIn("append_failed", [e.code for e in result.errors])
            saved = json.loads(
                (Path(directory) / result.suite_id / "result.json").read_text()
            )
            self.assertIn("append_failed", [e["code"] for e in saved["errors"]])
