# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Exercise quality rules and the bounded index with real streamed observations."""

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from verboisy.streaming.contract import StreamError
from verboisy.streaming.quality_checks import _Row, assess
from verboisy.streaming.quality_contract import compile_contract, validate_index_limit


class QualityEngineTests(unittest.TestCase):
    def setUp(self):
        work = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(work)

    def assess(self, values, policy, *, folder=None, expected=None, index_bytes=65536):
        rows = (_Row(i, i + 1, i + 1, row) for i, row in enumerate(values, 1))
        return assess(
            rows,
            compile_contract({"version": "1", **policy}),
            expected_rows=len(values) if expected is None else expected,
            folder=self.root if folder is None else folder,
            max_index_bytes=index_bytes,
        )

    def test_contract_fingerprint_includes_defaults_and_rule_values(self):
        default = compile_contract(
            {"version": "1", "completeness": [{"field": "/nested/a~1b"}], "unique": [["/sku"]]}
        )
        explicit = compile_contract(
            {
                "unique": [["/sku"]],
                "max_rows": None,
                "min_rows": 1,
                "completeness": [{"min_present_percent": 100, "field": "/nested/a~1b"}],
                "version": "1",
            }
        )
        changed = compile_contract(
            {
                "version": "1",
                "completeness": [{"field": "/nested/a~1b", "min_present_percent": 99}],
                "unique": [["/sku"]],
            }
        )
        self.assertEqual(default.sha256, explicit.sha256)
        self.assertNotEqual(default.sha256, changed.sha256)
        self.assertEqual(default.completeness[0].path, ("nested", "a/b"))

    def test_malformed_contracts_are_refused(self):
        cases = [
            ([], "version 1"),
            ({"version": "2"}, "version 1"),
            ({"extra": False}, "supported"),
            ({"min_rows": True}, "min_rows"),
            ({"min_rows": 2.0}, "min_rows"),
            ({"min_rows": -1}, "min_rows"),
            ({"min_rows": 5, "max_rows": 4}, "max_rows"),
            ({"min_rows": 0}, "effective check"),
            ({"completeness": {}}, "completeness must be an array"),
            ({"completeness": [{"field": "/a"}] * 65}, "at most 64"),
            ({"completeness": ["a"]}, "Completeness rules"),
            ({"completeness": [{}]}, "Completeness rules"),
            ({"completeness": [{"field": "/a", "bogus": 1}]}, "Completeness rules"),
            ({"completeness": [{"field": ""}]}, "non-root JSON pointer"),
            ({"completeness": [{"field": "/a", "min_present_percent": 0}]}, "min_present_percent"),
            ({"completeness": [{"field": "/a"}, {"field": "/a"}]}, "distinct"),
            ({"unique": ["/a"]}, "array of key pointers"),
            ({"unique": [["/a"]] * 9}, "at most 8"),
            ({"unique": [[]]}, "one to eight"),
            ({"unique": [["/a", "/a"]]}, "distinct"),
            ({"unique": [["/a", "/b"], ["/b", "/a"]]}, "distinct field groups"),
        ]
        for supplied, message in cases:
            with self.subTest(supplied=supplied), self.assertRaisesRegex(StreamError, message):
                data = {"version": "1", **supplied} if isinstance(supplied, dict) else supplied
                compile_contract(data)

    def test_completeness_separates_missing_null_blank_and_populated(self):
        values = [
            {},
            {"note": None},
            {"note": " \t "},
            {"note": False},
            {"note": 0},
            {"note": []},
        ]
        rule = {"field": "/note", "min_present_percent": 50}
        checked = self.assess(
            values,
            {"min_rows": 6, "max_rows": 6, "completeness": [rule]},
            folder=self.root / "not-created",
        )
        self.assertTrue(checked.passed)
        result = checked.completeness[0]
        self.assertEqual((result.present, result.missing, result.null, result.blank), (3, 1, 1, 1))
        self.assertEqual(
            [(e.reason, e.ordinal, e.first_line) for e in result.examples],
            [("missing", 1, 2), ("null", 2, 3), ("blank", 3, 4)],
        )
        rule["min_present_percent"] = 51
        checked = self.assess(values, {"completeness": [rule]})
        self.assertFalse(checked.passed)
        self.assertFalse(checked.completeness[0].passed)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_composite_keys_preserve_types_and_bound_duplicate_examples(self):
        values = [
            {"site": "source value", "id": 1},
            {"site": "source value", "id": "1"},
            {"site": "other site", "id": 1},
            *({"site": "source value", "id": 1} for _ in range(5)),
            {"id": 1},
            {"site": "source value", "id": True},
        ]
        for i, value in enumerate(values):
            value["sku"] = i
        result = self.assess(values, {"unique": [["/site", "/id"], ["/sku"]]})
        self.assertFalse(result.passed)
        composite, sku = result.uniqueness
        self.assertEqual((composite.invalid, composite.duplicates, composite.passed), (2, 5, False))
        self.assertEqual(
            [(e.ordinal, e.first_ordinal) for e in composite.examples], [(4, 1), (5, 1), (6, 1)]
        )
        self.assertTrue(sku.passed)
        self.assertNotIn("source value", json.dumps(asdict(result)))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_keys_report_locations_without_values(self):
        values = [{"id": "x" * 4097}, {"id": None}, {"id": ""}]
        result = self.assess(values, {"unique": [["/id"]]})
        self.assertEqual(result.uniqueness[0].invalid, 3)
        self.assertEqual(
            [(e.reason, e.ordinal) for e in result.uniqueness[0].examples],
            [("invalid", 1), ("invalid", 2), ("invalid", 3)],
        )

    def test_count_bounds_distinguish_expected_empty_input(self):
        self.assertFalse(self.assess([], {}).passed)
        self.assertTrue(self.assess([], {"min_rows": 0, "max_rows": 0}).passed)
        result = self.assess([{"id": 1}, {"id": 2}], {"max_rows": 1})
        self.assertFalse(result.row_count.passed)
        self.assertEqual(result.rows, 2)

    def test_truncated_replay_does_not_produce_a_quality_report(self):
        with self.assertRaisesRegex(StreamError, "declared row count"):
            self.assess([{"id": 1}], {"unique": [["/id"]]}, expected=2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_disk_and_index_limits_stop_instead_of_ignoring_violations(self):
        values = [{"id": f"{i}-" + "x" * 1024} for i in range(200)]
        with self.assertRaisesRegex(StreamError, "quality index"):
            self.assess(values, {"unique": [["/id"]]})
        with self.assertRaisesRegex(StreamError, "quality index"):
            self.assess([{"id": 1}], {"unique": [["/id"]]}, folder=self.root / "absent")
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(validate_index_limit(65536), 65536)
        for invalid in (True, 0, 65536.0, 17 * 1024**4):
            with (
                self.subTest(invalid=invalid),
                self.assertRaisesRegex(StreamError, "max_index_bytes"),
            ):
                validate_index_limit(invalid)

    def test_duplicate_detection_retains_identity_across_index_batches(self):
        count = 8300
        records = (_Row(i + 1, i + 1, i + 1, {"id": i % (count - 1)}) for i in range(count))
        result = assess(
            records,
            compile_contract({"version": "1", "unique": [["/id"]]}),
            expected_rows=count,
            folder=self.root,
            max_index_bytes=2 * 1024**2,
        )
        self.assertEqual(result.rows, count)
        self.assertEqual(result.uniqueness[0].duplicates, 1)
        (example,) = result.uniqueness[0].examples
        self.assertEqual((example.ordinal, example.first_ordinal), (count, 1))
