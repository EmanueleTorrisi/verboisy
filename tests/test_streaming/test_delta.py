# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Exercise the real disk index and atomic JSONL patch writer."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from verboisy.streaming.contract import StreamError
from verboisy.streaming.delta import UpdateLimits, _Record, _Version, _write_delta


def version(name, rows, *, count=None):
    return _Version(
        name,
        hashlib.sha256(name.encode()).hexdigest(),
        len(rows) if count is None else count,
        (_Record(i, i + 1, i + 1, row) for i, row in enumerate(rows, 1)),
    )


def row_digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class DeltaTests(unittest.TestCase):
    def setUp(self):
        work = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(work)
        self.output = self.root / "changes.jsonl"

    def write(self, before, after, *, keys=("/id",), complete=False, limits=None):
        return _write_delta(
            before,
            after,
            keys=keys,
            contract_sha256="c" * 64,
            output=self.output,
            complete_snapshot=complete,
            limits=limits or UpdateLimits(),
        )

    def failure(self, message, before, after, **kwargs):
        with self.assertRaisesRegex(StreamError, message):
            self.write(before, after, **kwargs)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_delta_applies_exactly_and_preserves_typed_identity_and_evidence(self):
        before = [
            {"id": 1, "value": 1},
            {"id": "1", "value": {"z": None, "a": True}},
            {"id": "retired", "value": 9},
            {"id": "earlier", "value": 10},
        ]
        after = [
            {"value": {"a": True, "z": None}, "id": "1"},
            {"id": "日本", "value": [False, "line\nend"]},
            {"value": 1.0, "id": 1},
        ]
        result = self.write(version("baseline", before), version("current", after), complete=True)
        self.assertEqual(
            (result.inserted, result.updated, result.removed, result.unchanged, result.unobserved),
            (1, 1, 2, 1, 0),
        )
        lines = self.output.read_bytes().splitlines(keepends=True)
        header, *changes, summary = map(json.loads, lines)
        self.assertEqual(header["version"], "stream-update-1")
        self.assertEqual(header["baseline"]["source_sha256"], version("baseline", []).source_sha256)
        self.assertEqual(header["current"]["rows"], len(after))
        self.assertEqual(
            [(row["op"], row["key"]) for row in changes],
            [
                ("insert", ["日本"]),
                ("update", [1]),
                ("delete", ["earlier"]),
                ("delete", ["retired"]),
            ],
        )
        applied = {row["id"]: row for row in before}
        for event in changes:
            key = event["key"][0]
            if event["op"] in {"update", "delete"}:
                self.assertEqual(event["before"]["row_sha256"], row_digest(applied[key]))
            if event["op"] == "delete":
                del applied[key]
                continue
            self.assertEqual(event["after"]["row_sha256"], row_digest(event["row"]))
            applied[key] = event["row"]
        self.assertEqual(changes[1]["before"]["ordinal"], 1)
        self.assertEqual(changes[1]["after"]["first_line"], 4)
        self.assertIs(applied["1"], before[1])
        self.assertEqual(
            {k: row_digest(v) for k, v in applied.items()}, {v["id"]: row_digest(v) for v in after}
        )
        self.assertEqual(summary["body_sha256"], hashlib.sha256(b"".join(lines[:-1])).hexdigest())
        self.assertEqual(summary["body_sha256"], result.body_sha256)
        self.assertEqual(list(self.root.iterdir()), [self.output])

    def test_missing_records_are_retained_by_default(self):
        result = self.write(version("old", [{"id": 1}, {"id": 2}]), version("new", []))
        lines = [json.loads(line) for line in self.output.read_bytes().splitlines()]
        self.assertEqual([line["kind"] for line in lines], ["manifest", "summary"])
        self.assertFalse(lines[0]["complete_snapshot"])
        self.assertEqual((result.removed, result.unobserved), (0, 2))

    def test_composite_pointer_keys_preserve_escape_semantics(self):
        rows = [
            {"a/b": {"~code": "001"}, "market": "EU", "price": 4},
            {"a/b": {"~code": "001"}, "market": "UK", "price": 5},
        ]
        self.write(
            version("old", rows),
            version("new", [rows[1], dict(rows[0], price=6)]),
            keys=("/a~1b/~0code", "/market"),
        )
        _, change, _ = map(json.loads, self.output.read_bytes().splitlines())
        self.assertEqual(change["key"], ["001", "EU"])
        self.assertEqual(change["row"]["price"], 6)

    def test_invalid_key_declarations_cannot_publish(self):
        for pointers in ("/id", (), ("/id",) * 9, (None,), ("id",), ("/~2",), ("/" + "x" * 1024,)):
            with self.subTest(pointers=pointers):
                self.failure(
                    "record key|Record key", version("old", []), version("new", []), keys=pointers
                )
        self.failure("distinct", version("old", []), version("new", []), keys=("/id", "/id"))

    def test_invalid_keys_cannot_publish(self):
        for key in (False, None, 3.0, "", {}, []):
            with self.subTest(key=key):
                self.failure(
                    "nonempty string or integer", version("old", [{"id": key}]), version("new", [])
                )
        for key in ("x" * 4097, "é" * 2049):
            with self.subTest(key_bytes=len(key.encode())):
                self.failure("4096", version("old", []), version("new", [{"id": key}]))
        self.failure(
            "Missing record key", version("old", [{"id": []}]), version("new", []), keys=("/id/0",)
        )
        self.failure("Missing record key", version("old", []), version("new", [{"other": 1}]))

    def test_duplicates_fail_for_existing_and_new_keys(self):
        self.failure(
            "Duplicate baseline", version("old", [{"id": 1}, {"id": 1}]), version("new", [])
        )
        for baseline in ([], [{"id": 1}]):
            with self.subTest(baseline=baseline):
                self.failure(
                    "Duplicate current",
                    version("old", baseline),
                    version("new", [{"id": 1}, {"id": 1}]),
                )

    def test_truncated_replay_cannot_publish_any_removals(self):
        self.failure(
            "Baseline replay", version("old", [], count=2), version("new", []), complete=True
        )
        self.failure(
            "Current replay",
            version("old", [{"id": 1}]),
            version("new", [{"id": 2}], count=3),
            complete=True,
        )

    def test_index_and_output_limits_leave_no_visible_partial_file(self):
        self.failure(
            "index within",
            version("old", [{"id": f"{i}-" + "x" * 1024} for i in range(200)]),
            version("new", []),
            limits=UpdateLimits(index_bytes=65536),
        )
        self.failure(
            "output byte limit",
            version("old", []),
            version("new", [{"id": 1, "description": "x" * 2048}]),
            limits=UpdateLimits(output_bytes=1024),
        )
        for kwargs in ({"index_bytes": True}, {"index_bytes": 0}, {"output_bytes": 1.5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(StreamError):
                UpdateLimits(**kwargs)

    def test_file_created_during_comparison_is_preserved(self):
        def concurrent_records():
            yield _Record(1, 1, 1, {"id": 1})
            self.output.write_bytes(b"another writer")

        with self.assertRaisesRegex(StreamError, "Cannot publish"):
            self.write(version("old", []), _Version("new", "a" * 64, 1, concurrent_records()))
        self.assertEqual(self.output.read_bytes(), b"another writer")
        self.assertEqual(list(self.root.iterdir()), [self.output])

    def test_streaming_batches_do_not_drop_unchanged_keys(self):
        count = 8300
        old = (_Record(i + 1, i + 1, i + 1, {"id": i, "value": 1}) for i in range(count))
        new = (
            _Record(i + 1, i + 1, i + 1, {"id": count - i - 1, "value": 2 if i == 4000 else 1})
            for i in range(count)
        )
        result = self.write(
            _Version("old", "a" * 64, count, old),
            _Version("new", "b" * 64, count, new),
            complete=True,
        )
        self.assertEqual((result.updated, result.unchanged, result.removed), (1, count - 1, 0))
        _, change, _ = map(json.loads, self.output.read_bytes().splitlines())
        self.assertEqual(change["key"], [4299])
