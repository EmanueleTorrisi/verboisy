# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Ambiguous version metadata must fail before schema or migration writes."""

import sqlite3
from contextlib import closing

import pytest
from filelock import FileLock
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError


def persisted_state(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        return (
            db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall(),
            db.execute("SELECT rowid,version FROM research_meta ORDER BY rowid").fetchall(),
            db.execute("SELECT value FROM sentinel").fetchall(),
        )


@pytest.mark.parametrize("versions", [(4, 4), (3, 4), (2, 4), (4, 999), (999, 4), ()])
def test_writable_open_rejects_ambiguous_or_missing_version_before_schema_writes(
    tmp_path, versions
):
    path = tmp_path / "versions.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE research_meta(version INTEGER NOT NULL)")
        db.executemany("INSERT INTO research_meta VALUES(?)", [(version,) for version in versions])
        db.execute("CREATE TABLE sentinel(value TEXT)")
        db.execute("INSERT INTO sentinel VALUES('preserve this data')")
    before = persisted_state(path)
    retained = []

    class RetainedStore(ResearchStore):
        def __new__(cls, *_args, **_kwargs):
            instance = super().__new__(cls)
            # Constructor cleanup must release the lease explicitly, rather than
            # relying on collection of a discarded failed instance.
            retained.append(instance)
            return instance

    try:
        with (
            pytest.raises(VerboisyError, match="Unsupported research database version"),
            closing(RetainedStore(path)),
        ):
            pass
        assert persisted_state(path) == before
        assert not retained[0].lock.is_locked
        with FileLock(str(path) + ".lock", timeout=0):
            pass
    finally:
        for store in retained:
            store.db.close()
            store.lock.release()
