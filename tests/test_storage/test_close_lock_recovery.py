# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Closing faults must not strand the ledger's application writer lease."""

import sqlite3
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("close fault"), sqlite3.OperationalError("close fault"), KeyboardInterrupt()],
)
def test_database_close_failure_releases_real_writer_lock(tmp_path, failure):
    path = tmp_path / "close.db"
    store = ResearchStore(path)
    connection = store.db
    store.db = SimpleNamespace(close=Mock(side_effect=failure))
    try:
        with pytest.raises(type(failure)) as caught:
            store.close()
        assert caught.value is failure
        assert not store.lock.is_locked
        # A different FileLock instance must acquire the same path immediately,
        # even while the failed connection remains alive but idle.
        with closing(ResearchStore(path)) as replacement:
            assert replacement.lock.is_locked
    finally:
        connection.close()
        store.lock.release()


def test_read_only_close_fault_cannot_release_another_writer_lock(tmp_path):
    path = tmp_path / "close.db"
    with closing(ResearchStore(path)) as writer:
        reader = ResearchStore(path, read_only=True)
        connection = reader.db
        reader.db = SimpleNamespace(close=Mock(side_effect=RuntimeError("reader close fault")))
        try:
            with pytest.raises(RuntimeError, match="reader close fault"):
                reader.close()
            assert writer.lock.is_locked
            with pytest.raises(VerboisyError, match="in use by another run"):
                ResearchStore(path)
        finally:
            connection.close()
            reader.lock.release()


def test_initialization_close_fault_releases_writer_lock(tmp_path, monkeypatch):
    path = tmp_path / "close.db"
    original_connect = sqlite3.connect
    original_initialize = ResearchStore._initialize_or_migrate
    captured = []
    failure = RuntimeError("initialization cleanup fault")

    class FailingCloseConnection(sqlite3.Connection):
        def close(self):
            raise failure

    def connect(*args, **kwargs):
        return original_connect(*args, **kwargs, factory=FailingCloseConnection)

    def fail_initialization(store, tables):
        # Retain the failed store so garbage collection cannot release its lock
        # and conceal a missing explicit cleanup attempt.
        captured.append(store)
        raise RuntimeError("initialization fault")

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(ResearchStore, "_initialize_or_migrate", fail_initialization)
    try:
        with pytest.raises(RuntimeError, match="initialization cleanup fault") as caught:
            ResearchStore(path)
        assert caught.value is failure
        assert not captured[0].lock.is_locked
        monkeypatch.setattr(sqlite3, "connect", original_connect)
        monkeypatch.setattr(ResearchStore, "_initialize_or_migrate", original_initialize)
        with closing(ResearchStore(path)) as replacement:
            assert replacement.lock.is_locked
    finally:
        for store in captured:
            sqlite3.Connection.close(store.db)
            store.lock.release()
