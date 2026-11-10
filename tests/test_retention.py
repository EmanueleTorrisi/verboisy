# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Exercise private paths and transactional retention with disposable SQLite ledgers."""

import json
import sqlite3
import stat
import sys
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from filelock import FileLock
from verboisy import retention, workspace
from verboisy.storage.ledger_schema import initialize_ledger
from verboisy.streaming.contract import StreamError
from verboisy.streaming.ledger import StreamLedger
from verboisy.streaming.ledger_schema import validate_stream_ledger
from verboisy.utils.exceptions import VerboisyError


@contextmanager
def connect(path):
    with closing(sqlite3.connect(path)) as db, db:
        yield db


def metadata(info, **overrides):
    fields = {
        key: getattr(info, key)
        for key in (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
            "st_mode",
            "st_nlink",
            "st_uid",
        )
    }
    return SimpleNamespace(**{**fields, **overrides})


def insert_research(db, status="COMPLETED"):
    rid = str(uuid4())
    db.execute("INSERT INTO research_runs(id,status,goal) VALUES(?,?,?)", (rid, status, "private"))
    return rid


def insert_stream(db, status="COMPLETED"):
    rid = uuid4().hex
    db.execute("INSERT INTO stream_jobs(id,contract,status) VALUES(?,?,?)", (rid, "{}", status))
    return rid


class TestWorkspacePlatform(unittest.TestCase):
    def test_linux_owner_identity_or_controlled_unsupported_platform(self):
        with (
            patch.object(workspace, "sys", SimpleNamespace(platform="win32")),
            self.assertRaisesRegex(VerboisyError, "require Linux or WSL"),
        ):
            workspace._owner_uid()
        with patch.object(workspace, "sys", SimpleNamespace(platform="linux")):
            with patch.object(workspace, "os", SimpleNamespace()), self.assertRaises(VerboisyError):
                workspace._owner_uid()
            with patch.object(workspace, "os", SimpleNamespace(geteuid=lambda: 101)):
                self.assertEqual(workspace._owner_uid(), 101)


class TestStreamLayout(unittest.TestCase):
    def test_requires_stream_identity_version_columns_and_keys(self):
        with connect(":memory:") as db:
            with self.assertRaisesRegex(StreamError, "Not a streaming ledger"):
                validate_stream_ledger(db)
            db.execute("CREATE TABLE stream_meta(version INTEGER NOT NULL)")
            for versions in ((), (2,), (1, 1)):
                db.execute("DELETE FROM stream_meta")
                db.executemany("INSERT INTO stream_meta VALUES(?)", ((n,) for n in versions))
                with self.assertRaisesRegex(StreamError, "Unsupported streaming ledger version"):
                    validate_stream_ledger(db)
            db.execute("DELETE FROM stream_meta")
            db.execute("INSERT INTO stream_meta VALUES(1)")
            with self.assertRaisesRegex(StreamError, "Incomplete streaming ledger schema"):
                validate_stream_ledger(db)
            db.execute(
                "CREATE TABLE stream_jobs(id,contract,status,captured,"
                "byte_count,sha256,processed,reason)"
            )
            with self.assertRaisesRegex(StreamError, "Invalid streaming ledger primary key"):
                validate_stream_ledger(db)


class TestRetention(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        fixture = Path(temporary.name).resolve()
        self.external_ancestors = frozenset(fixture.parents)
        self.root = fixture / "parent" / "project"
        self.root.parent.mkdir(mode=0o700)
        self.root.mkdir(mode=0o700)
        self.db = self.root / "run.db"
        self.uid = self.root.stat().st_uid
        self.read_metadata = workspace._lstat
        # The network sandbox may leave host UIDs unmapped. Keep the test's
        # own Linux filesystem metadata and simulate only the ancestry above it.
        self.enterContext(patch.object(workspace, "_lstat", self.fixture_metadata))
        if sys.platform != "linux":
            # Other platforms run the SQLite cases with simulated Linux mode bits.
            self.enterContext(patch.object(workspace, "_owner_uid", return_value=self.uid))

    def fixture_metadata(self, path):
        info = self.read_metadata(path)
        if path in self.external_ancestors or sys.platform != "linux":
            mode = stat.S_IFDIR | 0o700 if stat.S_ISDIR(info.st_mode) else info.st_mode
            return metadata(info, st_mode=mode, st_uid=self.uid)
        return info

    def plan(self, **kwargs):
        return retention.retain_completed(self.root, self.db.name, **kwargs)

    def research(self):
        with connect(self.db) as db:
            initialize_ledger(db, set(), current_version=4, stable_row_id=lambda *_: "unused")

    def stream(self):
        with closing(StreamLedger(self.db)):
            pass

    def test_workspace_rejects_unsafe_names_and_paths(self):
        self.research()
        for name in (None, "", ".", "..", "../run.db", "a\\run.db", "C:run.db", "bad\nname"):
            with self.subTest(name=name), self.assertRaisesRegex(VerboisyError, "single ledger"):
                workspace.workspace_ledger(self.root, name)
        with self.assertRaisesRegex(VerboisyError, "existing private workspace"):
            workspace.workspace_ledger(self.root / "missing", self.db.name)
        alternate = SimpleNamespace(
            resolve=lambda **_kw: self.root, absolute=lambda: self.root / "link"
        )
        with self.assertRaisesRegex(VerboisyError, "canonical workspace"):
            workspace.workspace_ledger(alternate, self.db.name)
        with self.assertRaisesRegex(VerboisyError, "existing ledger"):
            workspace.workspace_ledger(self.root, "missing.db")
        self.assertEqual(workspace.workspace_ledger(self.root, self.db.name).path, self.db)

    def test_workspace_rejects_aliases_wrong_owners_and_shared_ancestors(self):
        self.research()
        baseline = workspace._lstat
        for path, overrides, error in (
            (self.root, {"st_mode": stat.S_IFREG | 0o600}, "owned directory"),
            (self.root, {"st_uid": self.uid + 1}, "owned directory"),
            (self.root, {"st_mode": stat.S_IFDIR | 0o755}, "mode 0700"),
            (self.root.parent, {"st_mode": stat.S_IFLNK | 0o777}, "unsafe ancestor"),
            (self.root.parent, {"st_uid": self.uid + 1}, "unsafe ancestor"),
            (self.root.parent, {"st_mode": stat.S_IFDIR | 0o777}, "unsafe ancestor"),
            (self.db, {"st_mode": stat.S_IFLNK | 0o777}, "without links"),
            (self.db, {"st_uid": self.uid + 1}, "owned regular files"),
            (self.db, {"st_nlink": 2}, "without links"),
        ):

            def lstat(candidate, selected=path, changes=overrides):
                info = baseline(candidate)
                return metadata(info, **changes) if candidate == selected else info

            with (
                patch.object(workspace, "_lstat", lstat),
                self.assertRaisesRegex(VerboisyError, error),
            ):
                workspace.workspace_ledger(self.root, self.db.name)
        with (
            patch.object(workspace, "_lstat", side_effect=PermissionError),
            self.assertRaisesRegex(VerboisyError, "Cannot inspect"),
        ):
            workspace.workspace_ledger(self.root, self.db.name)

    def test_linux_workspace_refuses_actual_filesystem_links(self):
        if sys.platform != "linux":
            return
        self.research()
        shortcut = self.root.parent / "shortcut"
        shortcut.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(VerboisyError, "canonical workspace"):
            workspace.workspace_ledger(shortcut, self.db.name)
        alias = self.root / "alias.db"
        alias.hardlink_to(self.db)
        with self.assertRaisesRegex(VerboisyError, "without links"):
            workspace.workspace_ledger(self.root, self.db.name)

    def test_linux_workspace_checks_actual_parent_permissions(self):
        if sys.platform != "linux":
            return
        self.research()
        parent = self.root.parent
        try:
            parent.chmod(0o770)
            with self.assertRaisesRegex(VerboisyError, "unsafe ancestor"):
                workspace.workspace_ledger(self.root, self.db.name)
            parent.chmod(0o1770)
            self.assertEqual(workspace.workspace_ledger(self.root, self.db.name).path, self.db)
        finally:
            parent.chmod(0o700)

    def test_workspace_refuses_unsafe_sidecars_and_handles_empty_wal(self):
        self.research()
        target = workspace.workspace_ledger(self.root, self.db.name)
        first = target.stamp()
        wal = self.root / "run.db-wal"
        wal.touch()
        self.assertEqual(target.stamp(), first)
        wal.write_bytes(b"synthetic changed WAL")
        self.assertNotEqual(target.stamp(), first)
        baseline = workspace._lstat

        def linked(path):
            info = baseline(path)
            return metadata(info, st_nlink=2) if path == wal else info

        with (
            patch.object(workspace, "_lstat", linked),
            self.assertRaisesRegex(VerboisyError, "without links"),
        ):
            target.stamp()
        (self.root / "run.db-journal").write_bytes(b"pending")
        with self.assertRaisesRegex(VerboisyError, "rollback journal"):
            target.stamp()

    def test_apply_cannot_overwrite_an_unexpected_file_at_the_lock_path(self):
        self.research()
        with connect(self.db) as db:
            insert_research(db)
        plan = self.plan(keep_last=0)
        lock_path = self.root / "run.db.lock"
        lock_path.write_bytes(b"Keep this unrelated data")
        before = self.db.read_bytes()
        with self.assertRaisesRegex(VerboisyError, "lock path contains data"):
            self.plan(keep_last=0, apply_plan=plan["plan_sha256"])
        self.assertEqual(lock_path.read_bytes(), b"Keep this unrelated data")
        self.assertEqual(self.db.read_bytes(), before)

    def test_research_preserves_recent_protected_active_and_shared_evidence(self):
        self.research()
        output = self.root / "output.csv"
        output.write_bytes(b"published bytes")
        with connect(self.db) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
            held, selected, next_eligible, newest = (insert_research(db) for _ in range(4))
            unfinished = tuple(
                insert_research(db, s) for s in ("RUNNING", "PAUSED", "FAILED", "EXHAUSTED")
            )
            db.execute("INSERT INTO pages(id,run_id,url) VALUES(1,?,?)", (selected, "private-url"))
            db.execute("INSERT INTO snapshots(id,run_id,page_id) VALUES('s',?,1)", (selected,))
            db.execute("INSERT INTO candidates(id,run_id,snapshot_id) VALUES(1,?,'s')", (selected,))
            db.execute("INSERT INTO records(run_id,candidate_id) VALUES(?,1)", (selected,))
            db.execute("INSERT INTO conflicts(run_id,identity) VALUES(?,?)", (selected, "private"))
            db.execute(
                "INSERT INTO events(run_id,kind,payload) VALUES(?,?,?)", (selected, "x", "{}")
            )
            db.executemany(
                "INSERT INTO dataset_blobs VALUES(?,?)",
                [(key, b"fixture") for key in ("shared", "only-selected", "existing-orphan")],
            )
            db.executemany(
                "INSERT INTO dataset_assets(id,run_id,sha256,metadata) VALUES(?,?,?,'{}')",
                [
                    ("one", selected, "shared"),
                    ("two", selected, "only-selected"),
                    ("three", held, "shared"),
                ],
            )
        before = self.db.read_bytes()
        settings = {"keep_last": 1, "protect": (held, held), "limit": 1}
        preview = self.plan(**settings)
        self.assertEqual(preview["selected_ids"], (selected,))
        self.assertEqual(preview["protected_ids"], (held,))
        self.assertTrue(preview["truncated"])
        self.assertEqual(preview["rows"]["dataset_blobs"], 1)
        self.assertEqual(preview["rows"]["dataset_assets"], 2)
        self.assertFalse(preview["applied"])
        self.assertNotIn("private", json.dumps(preview))
        self.assertEqual(before, self.db.read_bytes())
        self.assertFalse((self.root / "run.db.lock").exists())
        result = self.plan(**settings, apply_plan=preview["plan_sha256"])
        self.assertEqual(result, {**preview, "applied": True})
        with connect(self.db) as db:
            self.assertEqual(
                {rid for (rid,) in db.execute("SELECT id FROM research_runs")},
                {held, next_eligible, newest, *unfinished},
            )
            self.assertEqual(
                {sha for (sha,) in db.execute("SELECT sha256 FROM dataset_blobs")},
                {"shared", "existing-orphan"},
            )
            self.assertEqual(db.execute("SELECT run_id FROM dataset_assets").fetchall(), [(held,)])
            for table in ("pages", "snapshots", "candidates", "records", "conflicts", "events"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.assertEqual(output.read_bytes(), b"published bytes")
        with self.assertRaisesRegex(VerboisyError, "plan changed"):
            self.plan(**settings, apply_plan=preview["plan_sha256"])

    def test_stream_wal_changes_invalidate_plans_even_without_count_changes(self):
        self.stream()
        with connect(self.db) as db:
            db.execute("PRAGMA journal_mode=WAL").fetchone()
            completed, paused = insert_stream(db), insert_stream(db, "PAUSED")
            db.execute("INSERT INTO stream_chunks VALUES(?,0,'hash',?)", (completed, b"private"))
            db.execute(
                "INSERT INTO stream_rows(job_id,ordinal,source_json) VALUES(?,1,'{}')", (completed,)
            )
            db.commit()
            options = {"kind": "stream", "keep_last": 0}
            plan = self.plan(**options)
            self.assertEqual(plan["selected_ids"], (completed,))
            self.assertEqual(plan["rows"], {"stream_rows": 1, "stream_chunks": 1, "stream_jobs": 1})
            db.execute("UPDATE stream_jobs SET reason='new' WHERE id=?", (completed,))
            db.commit()
            with self.assertRaisesRegex(VerboisyError, "plan changed"):
                self.plan(**options, apply_plan=plan["plan_sha256"])
            fresh = self.plan(**options)
            self.assertTrue(self.plan(**options, apply_plan=fresh["plan_sha256"])["applied"])
            self.assertEqual(db.execute("SELECT id FROM stream_jobs").fetchall(), [(paused,)])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM stream_chunks").fetchone()[0], 0)

    def test_refuses_active_writer_empty_batch_and_ledger_change_during_plan(self):
        self.research()
        empty = self.plan()
        with self.assertRaisesRegex(VerboisyError, "no completed entries"):
            self.plan(apply_plan=empty["plan_sha256"])
        with connect(self.db) as db:
            insert_research(db)
        plan = self.plan(keep_last=0)
        with (
            FileLock(str(self.db) + ".lock", timeout=0),
            self.assertRaisesRegex(VerboisyError, "another Verboisy writer"),
        ):
            self.plan(keep_last=0, apply_plan=plan["plan_sha256"])
        target = SimpleNamespace(path=self.db, stamp=Mock(side_effect=[1, 2]))
        with (
            patch.object(retention, "workspace_ledger", return_value=target),
            self.assertRaisesRegex(VerboisyError, "changed while planning"),
        ):
            self.plan(keep_last=0)

    def test_rejects_unknown_holds_invalid_options_and_unapproved_layouts(self):
        self.research()
        for options in (
            {"kind": "other"},
            {"keep_last": True},
            {"keep_last": "1"},
            {"keep_last": -1},
            {"keep_last": 100_001},
            {"limit": False},
            {"limit": 1.0},
            {"limit": 0},
            {"limit": 101},
            {"protect": []},
            {"protect": ("a",) * 101},
            {"protect": ("bad",)},
            {"protect": ("z" * 32,)},
            {"protect": ("A" * 32,)},
            {"apply_plan": "not-a-hash"},
            {"apply_plan": 3},
        ):
            with self.subTest(options=options), self.assertRaises(VerboisyError):
                self.plan(**options)
        with self.assertRaisesRegex(VerboisyError, "protected run or job ID does not exist"):
            self.plan(protect=(str(uuid4()),))
        with self.assertRaisesRegex(VerboisyError, "stream ledger layout"):
            self.plan(kind="stream")
        with connect(self.db) as db:
            db.execute("CREATE TABLE unexpected(x)")
        with self.assertRaisesRegex(VerboisyError, "research ledger layout"):
            self.plan()
        with connect(self.db) as db:
            db.execute("DROP TABLE unexpected")
            db.execute("UPDATE research_meta SET version=3")
        with self.assertRaisesRegex(VerboisyError, "current research ledger version"):
            self.plan()
        with connect(self.db) as db:
            db.execute("CREATE VIEW another AS SELECT id FROM research_runs")
        with self.assertRaisesRegex(VerboisyError, "triggers or views"):
            self.plan()
        self.db.write_bytes(b"not a database")
        with self.assertRaisesRegex(VerboisyError, "no deletion committed"):
            self.plan()

    def test_cross_run_links_are_not_deleted(self):
        self.research()
        with connect(self.db) as db:
            selected, kept = insert_research(db), insert_research(db)
            db.execute("INSERT INTO candidates(id,run_id) VALUES(1,?)", (selected,))
            db.execute("INSERT INTO records(run_id,candidate_id) VALUES(?,1)", (kept,))
        with self.assertRaisesRegex(VerboisyError, "cross-run evidence links"):
            self.plan(keep_last=1)

    def test_row_or_blob_mismatch_rolls_back_the_complete_deletion(self):
        self.research()
        with connect(self.db) as db:
            rid = insert_research(db)
            db.execute("INSERT INTO records(run_id) VALUES(?)", (rid,))
        count = retention.planned_counts
        for key, error in (("records", "planned rows"), ("dataset_blobs", "blob deletion")):

            def wrong(*args, metric=key):
                result = count(*args)
                result[metric] += 1
                return result

            before = self.db.read_bytes()
            with patch.object(retention, "planned_counts", wrong):
                plan = self.plan(keep_last=0)
                with self.assertRaisesRegex(VerboisyError, error):
                    self.plan(keep_last=0, apply_plan=plan["plan_sha256"])
            self.assertEqual(before, self.db.read_bytes())

    def test_unplanned_cascade_is_detected_and_rolled_back(self):
        self.stream()
        with connect(self.db) as db:
            db.execute(
                "ALTER TABLE stream_jobs ADD COLUMN extra TEXT REFERENCES stream_jobs(id) "
                "ON DELETE SET NULL"
            )
            selected, kept = insert_stream(db), insert_stream(db, "PAUSED")
            db.execute("UPDATE stream_jobs SET extra=? WHERE id=?", (selected, kept))
        plan = self.plan(kind="stream", keep_last=0)
        before = self.db.read_bytes()
        with self.assertRaisesRegex(VerboisyError, "outside its approved rows"):
            self.plan(kind="stream", keep_last=0, apply_plan=plan["plan_sha256"])
        self.assertEqual(before, self.db.read_bytes())
