# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Foreign and incomplete SQLite files retain bytes, schema and journal mode."""

import sqlite3
from contextlib import closing

import pytest
from verboisy.storage.research import ResearchStore
from verboisy.streaming import StreamLedger
from verboisy.utils.exceptions import VerboisyError


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE unrelated(value)",
        "CREATE TABLE records(id INTEGER)",
        "CREATE TABLE research_meta(version); INSERT INTO research_meta VALUES(4)",
    ],
)
def test_foreign_database_unchanged(tmp_path, sql):
    path = tmp_path / "foreign.db"
    with sqlite3.connect(path) as db:
        db.executescript(sql)
    before = path.read_bytes()
    with pytest.raises(VerboisyError):
        ResearchStore(path)
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    with pytest.raises(VerboisyError):
        StreamLedger(path)
    assert path.read_bytes() == before


def test_symlink_ledger_rejected(tmp_path):
    target = tmp_path / "target.db"
    with closing(ResearchStore(target)):
        pass
    alias = tmp_path / "alias.db"
    alias.symlink_to(target)
    with pytest.raises(VerboisyError, match="symlink"):
        ResearchStore(alias)
    with pytest.raises(VerboisyError, match="symlink"):
        StreamLedger(alias)


def test_partial_columns_and_duplicate_meta_rejected(tmp_path):
    path = tmp_path / "ledger.db"
    with closing(ResearchStore(path)):
        pass
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE research_runs DROP COLUMN goal")
    before = path.read_bytes()
    with pytest.raises(VerboisyError, match="columns"):
        ResearchStore(path)
    assert path.read_bytes() == before


def test_directory_is_not_a_research_ledger(tmp_path):
    with pytest.raises(VerboisyError, match="regular file"):
        ResearchStore(tmp_path)
    assert list(tmp_path.iterdir()) == []
