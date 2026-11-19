import json
import unittest

from input_fixtures import case, config

from uiprobe.case_input import prepare_suite


class SuiteInputTests(unittest.TestCase):
    def test_prepares_ordered_entries_and_merges_only_the_matching_override(self):
        cases = [
            {**case(), "id": "a"},
            {"id": "broken"},
            {**case(), "id": "b"},
        ]
        defaults = {
            **config("runs"),
            "data_values": {"one": "default", "two": "shared"},
        }
        suite = prepare_suite(
            json.dumps({"cases": cases}),
            {
                "defaults": defaults,
                "case_overrides": {"a": {"data_values": {"one": "override"}}},
            },
        )
        self.assertFalse(suite.errors)
        self.assertEqual(
            [entry.source.case_index for entry in suite.entries], [0, 1, 2]
        )
        first, broken, last = suite.entries
        assert first.prepared and last.prepared
        self.assertIsNone(broken.prepared)
        self.assertTrue(broken.error)
        self.assertEqual(
            first.prepared.session_config.data_values,
            {"one": "override", "two": "shared"},
        )
        self.assertEqual(
            last.prepared.session_config.data_values, defaults["data_values"]
        )
        self.assertEqual(defaults["data_values"]["one"], "default")

    def test_duplicate_cases_are_all_invalid_and_assertion_ids_are_checkpoint_local(
        self,
    ):
        alpha = {**case(), "id": "duplicate"}
        beta = {**case(), "id": "duplicate"}
        gamma = {**case(), "id": "unique"}
        other = {**gamma["checkpoints"][0], "id": "other"}
        gamma["checkpoints"].append(other)
        suite = prepare_suite(
            json.dumps({"cases": [alpha, beta, gamma]}), {"defaults": config("runs")}
        )
        self.assertFalse(suite.errors)
        for entry in suite.entries[:2]:
            assert entry.error is not None
            self.assertEqual(entry.error.errors[0].reason, "duplicate_id")
            self.assertIsNone(entry.prepared)
        self.assertIsNotNone(suite.entries[2].prepared)

    def test_bad_matching_overrides_are_local_and_do_not_echo_values(self):
        for override in (
            {"entry_url": None},
            {"data_values": None},
            {"data_values": {"secret-key": 7}},
            {"secret-field": "secret-value"},
            {"max_actions": 1},
        ):
            with self.subTest(override=override):
                suite = prepare_suite(
                    json.dumps(
                        {"cases": [{**case(), "id": "a"}, {**case(), "id": "b"}]}
                    ),
                    {
                        "defaults": config("runs"),
                        "case_overrides": {"a": override, "b": {"data_values": {}}},
                    },
                )
                self.assertFalse(suite.errors)
                self.assertIsNotNone(suite.entries[0].error)
                self.assertIsNone(suite.entries[0].prepared)
                self.assertNotIn("secret", repr(suite))
                prepared = suite.entries[1].prepared
                assert prepared is not None
                self.assertEqual(
                    prepared.session_config.data_values, {"password": "secret-value"}
                )
