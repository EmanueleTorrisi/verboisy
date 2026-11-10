# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Verify coherent, bounded operational reporting against local SQLite ledgers."""

import json
import sqlite3
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from verboisy import operational_report, operations
from verboisy.storage import operations_journal
from verboisy.storage.ledger_schema import initialize_ledger
from verboisy.streaming.ledger import StreamLedger
from verboisy.utils.exceptions import VerboisyError

PRIVATE = "PRIVATE operational test content"


@contextmanager
def writer(path):
    with closing(sqlite3.connect(path)) as connection, connection:
        yield connection


def event(db, rid, kind, payload, when="2026-03-01 09:10:11"):
    db.execute(
        "INSERT INTO events(run_id,kind,payload,created_at) VALUES(?,?,?,?)",
        (rid, kind, json.dumps(payload), when),
    )


def run(db, status, reason=None, *, tokens=0, reserved=0):
    rid = str(uuid4())
    db.execute(
        "INSERT INTO research_runs(id,goal,schema_json,task_json,status,reason,tokens,reserved,"
        "export_path) VALUES(?,?,?,?,?,?,?,?,?)",
        (rid, PRIVATE, "{}", "{}", status, reason, tokens, reserved, PRIVATE),
    )
    return rid


def search(db, rid, attempt, status):
    event(db, rid, "search_request", {"attempt_id": attempt, "status": status, "query": PRIVATE})


def cache(db, rid, operation, outcome):
    event(
        db,
        rid,
        "persistent_cache",
        {"version": 1, "stage": "source_assessment", "operation": operation, "outcome": outcome},
    )


class TestOperationalReport(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.database = self.root / "private-input.db"
        with writer(self.database) as db:
            initialize_ledger(db, set(), current_version=4, stable_row_id=lambda *_: "unused")

    def test_latest_selection_and_value_free_totals(self):
        with writer(self.database) as db:
            excluded = run(db, "COMPLETED", "target_met", tokens=1000, reserved=2000)
            done = run(db, "COMPLETED", "target_met", tokens=23, reserved=137)
            stopped = run(db, PRIVATE, PRIVATE, tokens=0, reserved=3)
            db.execute(
                "INSERT INTO records(run_id,identity,payload) VALUES(?,?,?)",
                (done, PRIVATE, PRIVATE),
            )
            db.execute(
                "INSERT INTO candidates(run_id,payload,accepted) VALUES(?,?,0)", (done, PRIVATE)
            )
            db.execute("INSERT INTO snapshots(id,run_id,html) VALUES(?,?,?)", ("s", done, PRIVATE))
            db.execute(
                "INSERT INTO dataset_assets(id,run_id,sha256,metadata) VALUES(?,?,?,?)",
                ("a", done, "hash", PRIVATE),
            )
            db.execute("INSERT INTO conflicts(run_id,identity) VALUES(?,?)", (done, PRIVATE))
            db.executemany(
                "INSERT INTO pages(run_id,url,status) VALUES(?,?,?)",
                [(done, PRIVATE, "done"), (done, "other", PRIVATE)],
            )
            event(db, done, "coverage_gap", PRIVATE, "2026-03-01 09:00:00")
            event(db, done, "unrelated", PRIVATE, "2026-03-01 09:30:00")
            for attempt, status in (
                ("one", "reserved"),
                ("one", "reserved"),
                ("one", "succeeded"),
                ("one", "succeeded"),
                ("two", "reserved"),
                ("two", "failed"),
                ("three", "reserved"),
                ("three", "cancelled"),
                ("four", "reserved"),
                ("five", "blocked"),
                ("five", "blocked"),
            ):
                search(db, done, attempt, status)
            search(db, stopped, "one", "reserved")
            search(db, stopped, "one", "succeeded")
            for operation, outcome in (
                ("lookup", "hit"),
                ("lookup", "miss"),
                ("lookup", PRIVATE),
                ("store", "stored"),
                ("store", "unavailable"),
            ):
                cache(db, done, operation, outcome)
        before = self.database.read_bytes()
        report = operational_report(self.database, limit=2)
        self.assertEqual(report["report_version"], "operations-1")
        self.assertEqual(report["selection"], {"run_id": None, "limit": 2, "truncated": True})
        self.assertEqual([row["run_id"] for row in report["runs"]], [stopped, done])
        self.assertEqual(report["status_counts"]["UNKNOWN"], 1)
        self.assertEqual(report["stop_reason_counts"], {"other": 1, "target_met": 1})
        self.assertEqual(
            report["totals"],
            {
                "accepted_records": 1,
                "rejected_candidates": 1,
                "snapshots": 1,
                "captured_assets": 1,
                "identity_conflicts": 1,
                "coverage_gap_events": 1,
                "reserved_request_units": 140,
                "provider_reported_tokens": 23,
            },
        )
        self.assertEqual(report["runs"][1]["page_outcomes"]["done"], 1)
        self.assertEqual(report["runs"][1]["page_outcomes"]["other"], 1)
        self.assertEqual(
            report["runs"][1]["journal_activity"],
            {
                "first_event_at": "2026-03-01T09:00:00Z",
                "last_event_at": "2026-03-01T09:30:00Z",
            },
        )
        self.assertEqual(
            report["journal_totals"],
            {
                "search_attempts_reserved": 5,
                "search_attempts_succeeded": 2,
                "search_attempts_failed": 1,
                "search_attempts_cancelled": 1,
                "search_attempts_unconfirmed": 1,
                "search_attempts_blocked": 1,
                "cache_lookup_hits": 1,
                "cache_lookup_misses": 1,
                "cache_lookup_other": 1,
                "cache_stores": 1,
                "cache_store_other": 1,
            },
        )
        self.assertFalse(report["billing_recorded"])
        self.assertFalse(report["source_evidence_replayed"])
        self.assertNotIn(PRIVATE, json.dumps(report))
        self.assertNotIn(excluded, json.dumps(report))
        self.assertNotIn(str(self.database), json.dumps(report))
        self.assertEqual(self.database.read_bytes(), before)

    def test_empty_and_explicit_selection(self):
        empty = operational_report(self.database)
        self.assertEqual(empty["run_count"], 0)
        self.assertEqual(empty["journal_state"], "complete")
        self.assertEqual(sum(empty["totals"].values()), 0)
        with writer(self.database) as db:
            rid = run(db, "PAUSED")
            run(db, "RUNNING", "running")
            event(db, rid, "diagnostic", PRIVATE, "2026-90-99 00:00:00")
            event(db, rid, "diagnostic", PRIVATE, "invalid")
        report = operational_report(self.database, run_id=rid)
        self.assertEqual(report["selection"], {"run_id": rid, "limit": 1, "truncated": False})
        self.assertEqual(report["stop_reason_counts"], {"not_recorded": 1})
        self.assertEqual(
            report["runs"][0]["journal_activity"],
            {
                "first_event_at": None,
                "last_event_at": None,
            },
        )
        with self.assertRaisesRegex(VerboisyError, "No unique saved"):
            operational_report(self.database, run_id=str(uuid4()))

    def test_journal_limits_and_invalid_events_never_become_zero_usage(self):
        with writer(self.database) as db:
            rid = run(db, "RUNNING", "running", reserved=10)
            search(db, rid, "one", "reserved")
            search(db, rid, "one", "succeeded")
        with patch.object(operations_journal, "MAX_EVENTS", 1):
            report = operational_report(self.database)
        self.assertEqual(report["journal_state"], "event_limit")
        self.assertIsNone(report["journal_totals"])
        self.assertIsNone(report["runs"][0]["journal"])
        self.assertEqual(report["totals"]["reserved_request_units"], 10)
        for kind, payload in (
            ("search_request", "[]"),
            ("search_request", '{"status":"reserved","attempt_id":"a","attempt_id":"b"}'),
            ("search_request", json.dumps({"attempt_id": "one", "status": "failed"})),
            ("search_request", json.dumps({"attempt_id": None, "status": "reserved"})),
            ("search_request", json.dumps({"attempt_id": "new", "status": "succeeded"})),
            ("persistent_cache", json.dumps({"operation": "lookup", "outcome": "x", "version": 2})),
            (
                "persistent_cache",
                json.dumps(
                    {
                        "operation": PRIVATE,
                        "outcome": "hit",
                        "version": 1,
                        "stage": "source_assessment",
                    }
                ),
            ),
            ("search_request", '"' + PRIVATE * 3000 + '"'),
        ):
            with self.subTest(kind=kind, length=len(payload)):
                with writer(self.database) as db:
                    row = db.execute(
                        "INSERT INTO events(run_id,kind,payload) VALUES(?,?,?)",
                        (rid, kind, payload),
                    ).lastrowid
                report = operational_report(self.database)
                self.assertEqual(report["journal_state"], "invalid_event")
                self.assertIsNone(report["journal_totals"])
                self.assertNotIn(PRIVATE, json.dumps(report))
                with writer(self.database) as db:
                    db.execute("DELETE FROM events WHERE id=?", (row,))

    def test_accounting_and_status_share_one_snapshot(self):
        with writer(self.database) as db:
            db.execute("PRAGMA journal_mode=WAL").fetchone()
            rid = run(db, "RUNNING", "running", reserved=10)
            search(db, rid, "one", "reserved")
        summarize = operations.summarize_journal

        def complete_in_other_connection(db, ids):
            with writer(self.database) as other:
                other.execute("UPDATE research_runs SET reserved=15 WHERE id=?", (rid,))
                search(other, rid, "one", "succeeded")
            return summarize(db, ids)

        with patch.object(operations, "summarize_journal", complete_in_other_connection):
            before = operational_report(self.database)
        after = operational_report(self.database)
        self.assertEqual(before["totals"]["reserved_request_units"], 10)
        self.assertEqual(before["journal_totals"]["search_attempts_unconfirmed"], 1)
        self.assertEqual(after["totals"]["reserved_request_units"], 15)
        self.assertEqual(after["journal_totals"]["search_attempts_succeeded"], 1)

    def test_stream_reports_saved_large_checkpoints_without_reading_rows(self):
        path = self.root / "stream.db"
        job_id = uuid4().hex
        with closing(StreamLedger(path)) as ledger, ledger.connection as db:
            db.execute(
                "INSERT INTO stream_jobs(id,contract,status,reason,captured,byte_count,processed) "
                "VALUES(?,?,?,?,?,?,?)",
                (job_id, PRIVATE, "PAUSED", "invocation_row_budget", 1, 100 * 1024**3, 30_000_000),
            )
        before = path.read_bytes()
        report = operational_report(path, kind="stream", run_id=job_id)
        self.assertEqual(report["ledger_kind"], "stream")
        self.assertEqual(
            report["totals"],
            {
                "processed_rows": 30_000_000,
                "captured_bytes": 100 * 1024**3,
                "completed_captures": 1,
            },
        )
        self.assertEqual(report["journal_state"], "not_applicable")
        self.assertIsNone(report["journal_totals"])
        self.assertNotIn(PRIVATE, json.dumps(report))
        self.assertEqual(path.read_bytes(), before)
        with writer(path) as db:
            db.execute("UPDATE stream_jobs SET captured=2 WHERE id=?", (job_id,))
        with self.assertRaisesRegex(VerboisyError, "capture indicator"):
            operational_report(path, kind="stream")
        with writer(path) as db:
            db.execute("UPDATE stream_jobs SET captured=0 WHERE id=?", (job_id,))
        with self.assertRaisesRegex(VerboisyError, "requires a completed capture"):
            operational_report(path, kind="stream")
        with writer(path) as db:
            db.execute(
                "UPDATE stream_jobs SET byte_count=0,processed=0,status='FAILED' WHERE id=?",
                (job_id,),
            )
        self.assertEqual(operational_report(path, kind="stream")["totals"]["completed_captures"], 0)

    def test_rejects_bad_selection_or_invalid_ledgers_without_payloads(self):
        for kwargs in (
            {"kind": "unknown"},
            {"limit": True},
            {"limit": "2"},
            {"limit": 0},
            {"limit": 501},
            {"run_id": "short"},
            {"run_id": 123},
            {"run_id": "z" * 32},
            {"run_id": "A" * 32},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(VerboisyError):
                operational_report(self.database, **kwargs)
        with self.assertRaisesRegex(VerboisyError, "Choose an existing"):
            operational_report(self.root / "missing.db")
        with (
            patch.object(type(self.database), "is_symlink", return_value=True),
            self.assertRaises(VerboisyError),
        ):
            operational_report(self.database)
        corrupted = self.root / "wrong.db"
        corrupted.write_text(PRIVATE, encoding="utf-8")
        with self.assertRaisesRegex(VerboisyError, "Cannot read the selected"):
            operational_report(corrupted)
        with writer(self.database) as db:
            rid = run(db, "RUNNING", tokens=-1)
        with self.assertRaisesRegex(VerboisyError, "Saved operational counters are invalid"):
            operational_report(self.database)
        with writer(self.database) as db:
            db.execute("UPDATE research_runs SET tokens=? WHERE id=?", (PRIVATE, rid))
        with self.assertRaisesRegex(VerboisyError, "Saved operational counters are invalid"):
            operational_report(self.database)
        with writer(self.database) as db:
            db.execute("UPDATE research_meta SET version=3")
        with self.assertRaisesRegex(VerboisyError, "requires a current research ledger"):
            operational_report(self.database)
