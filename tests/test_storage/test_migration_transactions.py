# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""DDL, stable-ID backfill and version publication must roll back as one upgrade."""

import sqlite3
from contextlib import closing

import pytest
from filelock import FileLock
from verboisy.storage.ledger_schema import initialize_ledger
from verboisy.storage.research import DB_VERSION, ResearchStore, _stable_row_id
from verboisy.utils.exceptions import VerboisyError


def legacy_database(path, version, *, stable=False):
    if version is None:
        return
    store = ResearchStore(path)
    store.close()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE research_meta SET version=?", (version,))
        if version == 2:
            db.execute("DROP TABLE dataset_assets")
            db.execute("DROP TABLE dataset_blobs")
            db.execute("DROP TABLE records")
            field = ",stable_id TEXT" if stable else ""
            db.execute(
                "CREATE TABLE records(id INTEGER PRIMARY KEY,run_id TEXT,identity TEXT,"
                f"payload TEXT,candidate_id INTEGER{field},UNIQUE(run_id,identity))"
            )
            db.executemany(
                "INSERT INTO records(run_id,identity,payload) VALUES(?,?,?)",
                [("run", "first", "{}"), ("run", "second", "{}")],
            )


def state(db):
    schema = [
        tuple(row)
        for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")
    ]
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return schema, {
        table: [tuple(row) for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
        for table in tables
    }


def initialize(db, helper=_stable_row_id):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    initialize_ledger(db, tables, current_version=DB_VERSION, stable_row_id=helper)


@pytest.mark.parametrize("version", [None, 2, 3, 4])
@pytest.mark.parametrize(
    "denied", ["dataset_blobs", "dataset_assets", "pages", "candidates", "events"]
)
def test_schema_creation_fault_rolls_back_and_can_retry(tmp_path, version, denied):
    path = tmp_path / "schema.db"
    legacy_database(path, version)
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        before = state(db)
        db.set_authorizer(
            lambda action, name, *_rest: sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_CREATE_TABLE and name == denied
            else sqlite3.SQLITE_OK
        )
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            initialize(db)
        assert not db.in_transaction
        db.set_authorizer(None)
        assert state(db) == before
    with closing(sqlite3.connect(path)) as reopened:
        reopened.row_factory = sqlite3.Row
        assert state(reopened) == before
        initialize(reopened)
        assert reopened.execute("SELECT version FROM research_meta").fetchone()[0] == DB_VERSION
        assert not reopened.in_transaction


@pytest.mark.parametrize("stable", [False, True])
@pytest.mark.parametrize("position", [1, 2])
@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt, sqlite3.OperationalError])
def test_backfill_failure_rolls_back_column_ids_and_version(tmp_path, stable, position, failure):
    path = tmp_path / "backfill.db"
    legacy_database(path, 2, stable=stable)
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        before = state(db)
        calls = 0

        def fail(rid, identity):
            nonlocal calls
            calls += 1
            if calls == position:
                raise failure("injected backfill failure")
            return _stable_row_id(rid, identity)

        with pytest.raises(failure, match="injected backfill"):
            initialize(db, fail)
        assert calls == position
        assert not db.in_transaction
        assert state(db) == before
    with closing(ResearchStore(path)) as store:
        assert store.db.execute("SELECT version FROM research_meta").fetchone()[0] == DB_VERSION
        rows = store.db.execute("SELECT identity,stable_id FROM records ORDER BY id").fetchall()
        assert [(row[0], row[1]) for row in rows] == [
            (key, _stable_row_id("run", key)) for key in ("first", "second")
        ]


@pytest.mark.parametrize("version,stable", [(2, False), (2, True), (3, False)])
def test_version_publication_sql_fault_preserves_schema_and_releases_writer(
    tmp_path, version, stable
):
    path = tmp_path / "version.db"
    legacy_database(path, version, stable=stable)
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TRIGGER reject_version BEFORE UPDATE ON research_meta "
            "BEGIN SELECT RAISE(ABORT,'injected version failure'); END"
        )
        before = state(db)
    with pytest.raises(VerboisyError, match="readable research ledger"):
        ResearchStore(path)
    # The failed constructor must release its lease as well as roll back SQLite.
    lock = FileLock(str(path.resolve()) + ".lock")
    with lock.acquire(timeout=0), sqlite3.connect(path) as db:
        assert state(db) == before
        db.execute("DROP TRIGGER reject_version")
    with closing(ResearchStore(path)) as store:
        assert store.db.execute("SELECT version FROM research_meta").fetchone()[0] == DB_VERSION


@pytest.mark.parametrize(
    "version,stable", [(None, False), (2, False), (2, True), (3, False), (4, False)]
)
def test_supported_initialization_commits_and_repeated_open_is_stable(tmp_path, version, stable):
    path = tmp_path / "valid.db"
    legacy_database(path, version, stable=stable)
    with closing(ResearchStore(path)) as store:
        assert not store.db.in_transaction
        assert store.db.execute("SELECT version FROM research_meta").fetchone()[0] == DB_VERSION
        before = state(store.db)
    with closing(ResearchStore(path)) as store:
        assert state(store.db) == before
    with closing(ResearchStore(path, read_only=True)) as reader:
        assert state(reader.db) == before


def test_metadata_change_between_identity_read_and_initialization_is_rejected(
    tmp_path, monkeypatch
):
    import verboisy.storage.ledger_schema as schema

    path = tmp_path / "version-race.db"
    store = ResearchStore(path)
    store.close()
    original = schema.validate_ledger_identity

    def interleave(db, tables):
        original(db, tables)
        with sqlite3.connect(path) as writer:
            writer.execute("INSERT INTO research_meta VALUES(999)")

    monkeypatch.setattr(schema, "validate_ledger_identity", interleave)
    with closing(sqlite3.connect(path)) as db, pytest.raises(VerboisyError, match="version"):
        db.row_factory = sqlite3.Row
        initialize(db)
