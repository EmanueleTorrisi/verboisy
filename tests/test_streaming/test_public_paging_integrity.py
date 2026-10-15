# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Paging stamps bind a coherent snapshot and invalidate on both connection revisions."""

import sqlite3
from contextlib import closing
from unittest.mock import Mock

import pytest
from verboisy.streaming import StreamLedger
from verboisy.streaming.contract import StreamError

from tests.test_streaming.test_streaming import prepare as _prepare_fixture

prepare = _prepare_fixture


@pytest.mark.parametrize("external", [False, True])
def test_page_cache_invalidates_on_commits(prepare, tmp_path, monkeypatch, external):
    result = prepare()
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger:
        import verboisy.streaming.integrity as integrity

        real = integrity.verified_resume_rows
        scan = Mock(wraps=real)
        monkeypatch.setattr(integrity, "verified_resume_rows", scan)
        for _ in range(10):
            assert ledger.page(result.job_id, limit=1)[0]["record"] == {"name": "Anaïs"}
        assert scan.call_count == 1
        if external:
            with sqlite3.connect(tmp_path / "stream.db") as writer:
                writer.execute("UPDATE stream_rows SET output_json='{}'")
        else:
            with ledger.connection:
                ledger.connection.execute("UPDATE stream_rows SET output_json='{}'")
        with pytest.raises(StreamError):
            ledger.page(result.job_id)
        assert scan.call_count == 2


def test_caller_transaction_remains_owned(prepare, tmp_path):
    result = prepare()
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger:
        ledger.connection.execute("BEGIN")
        assert ledger.page(result.job_id)
        assert ledger.connection.in_transaction
        assert not ledger.verification_cache
        ledger.connection.rollback()


def test_concurrent_commit_between_revision_and_snapshot_cannot_certify_page(prepare, tmp_path):
    result = prepare()
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger:
        ledger.page(result.job_id)
        original = ledger.connection

        class Interleaved:
            changed = False

            def __getattr__(self, name):
                return getattr(original, name)

            def execute(self, sql, *args):
                if sql.startswith("SELECT * FROM stream_jobs") and not self.changed:
                    self.changed = True
                    with sqlite3.connect(tmp_path / "stream.db") as writer:
                        writer.execute("UPDATE stream_rows SET output_json='{}'")
                return original.execute(sql, *args)

        ledger.db = Interleaved()
        with pytest.raises(StreamError):
            ledger.page(result.job_id)


def test_verification_cache_has_a_32_job_ceiling(tmp_path):
    from verboisy.streaming import stream_dataset
    from verboisy.utils.config import Settings

    source = tmp_path / "source"
    source.write_text('{"n":1}\n')
    ids = []
    for _ in range(33):
        ids.append(
            stream_dataset(
                database=tmp_path / "stream.db",
                source=source,
                dataset_format="jsonl",
                config=Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
            ).job_id
        )
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger:
        for job in ids:
            assert ledger.page(job) == [{"ordinal": 1, "record": {"n": 1}}]
        cache = ledger.verification_cache
        assert len(cache) == 32 and ids[0] not in cache
    assert not cache


def test_repeated_revision_changes_fail_safely(prepare, tmp_path):
    result = prepare()
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger:
        ledger.connection.execute("PRAGMA journal_mode=WAL")
        original = ledger.connection

        class Busy:
            def __getattr__(self, name):
                return getattr(original, name)

            def execute(self, sql, *args):
                if sql.startswith("SELECT * FROM stream_jobs"):
                    with sqlite3.connect(tmp_path / "stream.db") as writer:
                        writer.execute("UPDATE stream_jobs SET reason=COALESCE(reason,'')||'x'")
                return original.execute(sql, *args)

        ledger.db = Busy()
        with pytest.raises(StreamError, match="changed during paging"):
            ledger.page(result.job_id)
        assert not ledger.verification_cache


def test_page_sql_read_failure_has_safe_category(prepare, tmp_path):
    result = prepare()
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger:
        ledger.page(result.job_id)
        ledger.connection.set_authorizer(
            lambda action, table, column, *_rest: sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_READ and table == "stream_rows" and column == "output_json"
            else sqlite3.SQLITE_OK
        )
        with pytest.raises(StreamError, match="verified streaming records"):
            ledger.page(result.job_id)
