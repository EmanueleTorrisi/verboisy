# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Read real SQLite pages under an aggregate byte budget without changing replay."""

import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from verboisy.evidence.models import ProjectionPlan
from verboisy.streaming import StreamLedger, integrity, paging, stream_dataset
from verboisy.streaming.contract import StreamError
from verboisy.utils.config import Settings


def encode(record):
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class TestPageByteBudget(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.database = self.root / "stream.db"

    def prepare(self, records, **kwargs):
        source = self.root / "input.jsonl"
        source.write_bytes(b"".join(encode(row) + b"\n" for row in records))
        result = stream_dataset(
            database=self.database,
            source=source,
            dataset_format="jsonl",
            config=Settings(_env_file=None, dataset_local_roots=[str(self.root)]),
            **kwargs,
        )
        self.assertEqual(result.status, "COMPLETED")
        return result.job_id

    def test_exact_utf8_boundary_returns_contiguous_pages(self):
        records = [{"text": "é" * 8}, {"text": "xyz"}, {"text": "😀"}, {"text": "last"}]
        job = self.prepare(records)
        budget = len(encode(records[0])) + len(encode(records[1]))
        with (
            closing(StreamLedger(self.database, read_only=True)) as ledger,
            patch.object(paging, "decode_json", wraps=paging.decode_json) as decode,
        ):
            first = ledger.page(job, max_bytes=budget)
            self.assertEqual(
                first,
                [
                    {"ordinal": 1, "record": records[0]},
                    {"ordinal": 2, "record": records[1]},
                ],
            )
            self.assertEqual(decode.call_count, 2)
            second = ledger.page(job, after=first[-1]["ordinal"], max_bytes=budget)
            self.assertEqual(
                second,
                [
                    {"ordinal": 3, "record": records[2]},
                    {"ordinal": 4, "record": records[3]},
                ],
            )
            self.assertEqual(ledger.page(job, after=second[-1]["ordinal"], max_bytes=budget), [])
            self.assertEqual(ledger.page(job, after=2**63 - 1), [])

    def test_oversized_next_row_does_not_skip_to_a_smaller_row(self):
        wide = {"text": "🧪" * 16}
        narrow = {"text": "small"}
        job = self.prepare([wide, narrow])
        character_count = len(encode(wide).decode("utf-8"))
        with closing(StreamLedger(self.database, read_only=True)) as ledger:
            with self.assertRaisesRegex(StreamError, "Next verified record exceeds max_bytes"):
                ledger.page(job, max_bytes=character_count)
            self.assertEqual(
                ledger.page(job, max_bytes=len(encode(wide))),
                [
                    {"ordinal": 1, "record": wide},
                ],
            )
            self.assertEqual(
                ledger.page(job, after=1, max_bytes=len(encode(narrow))),
                [
                    {"ordinal": 2, "record": narrow},
                ],
            )

    def test_default_page_refuses_a_silent_short_read(self):
        self.assertEqual(paging.page_budget(None), 16 * 1024**2)
        row = {"text": "a" * 16}
        job = self.prepare([row, row])
        budget = len(encode(row))
        with (
            closing(StreamLedger(self.database, read_only=True)) as ledger,
            patch.object(paging, "MAX_PAGE_BYTES", budget),
        ):
            with self.assertRaisesRegex(StreamError, "reduce limit or pass max_bytes"):
                ledger.page(job)
            one = [{"ordinal": 1, "record": row}]
            self.assertEqual(ledger.page(job, limit=1), one)
            self.assertEqual(ledger.page(job, max_bytes=budget), one)

    def test_budget_counts_the_served_projection(self):
        plan = ProjectionPlan(fields=[{"source": "/label", "target": "/out"}])
        projected = {"out": "é"}
        job = self.prepare([{"label": "é", "large": "x" * 4096}], projection=plan)
        with closing(StreamLedger(self.database, read_only=True)) as ledger:
            self.assertEqual(
                ledger.page(job, max_bytes=len(encode(projected))),
                [
                    {"ordinal": 1, "record": projected},
                ],
            )

    def test_invalid_budget_and_out_of_range_cursor_do_not_trigger_replay(self):
        job = self.prepare([{"id": 1}])
        with (
            closing(StreamLedger(self.database, read_only=True)) as ledger,
            patch.object(integrity, "verified_resume_rows") as replay,
        ):
            for invalid in (True, False, 0, -1, "16", 1.5, 16 * 1024**2 + 1):
                with (
                    self.subTest(invalid=invalid),
                    self.assertRaisesRegex(StreamError, "Page max_bytes"),
                ):
                    ledger.page(job, max_bytes=invalid)
            with self.assertRaisesRegex(StreamError, "64-bit cursor"):
                ledger.page(job, after=2**63)
            replay.assert_not_called()

    def test_page_still_rejects_tampered_records_outside_its_range(self):
        job = self.prepare([{"id": 1}, {"id": 2}, {"id": 3}])
        with closing(StreamLedger(self.database, read_only=True)) as ledger:
            self.assertEqual(ledger.page(job, limit=1, max_bytes=64)[0]["record"], {"id": 1})
            with closing(sqlite3.connect(self.database)) as writer, writer:
                writer.execute(
                    "UPDATE stream_rows SET output_json=? WHERE job_id=? AND ordinal=3",
                    ('{"id":42}', job),
                )
            with self.assertRaisesRegex(StreamError, "row evidence differs"):
                ledger.page(job, limit=1, max_bytes=64)

    def test_size_probe_and_payload_read_share_a_snapshot(self):
        row = {"text": "small"}
        job = self.prepare([row, row])
        budget = len(encode(row))
        with closing(sqlite3.connect(self.database)) as writer:
            writer.execute("PRAGMA journal_mode=WAL").fetchone()
        path = self.database
        with closing(StreamLedger(path, read_only=True)) as ledger:
            ledger.page(job, limit=1)
            original = ledger.connection

            class Interleaved:
                changed = False

                def __getattr__(self, name):
                    return getattr(original, name)

                def execute(self, sql, *args):
                    if sql.startswith("SELECT ordinal,COALESCE") and not self.changed:
                        self.changed = True
                        with closing(sqlite3.connect(path)) as writer, writer:
                            writer.execute(
                                "UPDATE stream_rows SET output_json=? WHERE job_id=? AND ordinal=1",
                                (encode({"text": "x" * 1024}).decode("utf-8"), job),
                            )
                    return original.execute(sql, *args)

            with (
                patch.object(ledger, "db", Interleaved()),
                patch.object(paging, "decode_json", wraps=paging.decode_json) as decode,
            ):
                with self.assertRaisesRegex(StreamError, "row evidence differs"):
                    ledger.page(job, max_bytes=budget)
                decode.assert_called_once_with(encode(row).decode("utf-8"))
            self.assertFalse(ledger.connection.in_transaction)

    def test_page_size_probe_refuses_non_text_and_invalid_size(self):
        with closing(sqlite3.connect(":memory:")) as db, db:
            db.execute(
                "CREATE TABLE stream_rows(job_id TEXT, ordinal INTEGER, source_json TEXT, "
                "output_json TEXT, PRIMARY KEY(job_id,ordinal))"
            )
            db.execute("INSERT INTO stream_rows VALUES('fixture',1,'{}',NULL)")
            for value in (b"{}", "", "x" * 65):
                db.execute("UPDATE stream_rows SET output_json=?", (value,))
                with self.assertRaisesRegex(StreamError, "record violates its byte limit"):
                    paging.read_page_rows(
                        db,
                        "fixture",
                        after=0,
                        limit=2,
                        record_ceiling=64,
                        budget=128,
                        allow_short=True,
                    )
