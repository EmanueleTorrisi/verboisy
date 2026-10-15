# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Connection setup failures must close the handle before constructor exit."""

import sqlite3
from contextlib import closing

import pytest
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError


@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize(
    "failure_kind", [RuntimeError, KeyboardInterrupt, sqlite3.OperationalError]
)
def test_row_factory_failure_closes_connection_and_releases_owned_lock(
    tmp_path, monkeypatch, read_only, failure_kind
):
    path = tmp_path / "setup.db"
    with closing(ResearchStore(path)):
        pass
    original_connect = sqlite3.connect
    connections = []
    stores = []
    failure = failure_kind("row factory setup fault")

    class RetainedStore(ResearchStore):
        def __new__(cls, *_args, **_kwargs):
            instance = super().__new__(cls)
            # Retention prevents garbage collection from hiding a leaked lease.
            stores.append(instance)
            return instance

    class FailingSetupConnection(sqlite3.Connection):
        close_calls = 0

        @property
        def row_factory(self):
            return sqlite3.Connection.row_factory.__get__(self)

        @row_factory.setter
        def row_factory(self, _value):
            raise failure

        def close(self):
            self.close_calls += 1
            super().close()

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs, factory=FailingSetupConnection)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    try:
        expected = VerboisyError if issubclass(failure_kind, sqlite3.Error) else failure_kind
        with pytest.raises(expected) as caught:
            RetainedStore(path, read_only=read_only)
        if expected is VerboisyError:
            assert "readable" in str(caught.value) and "ledger" in str(caught.value)
        else:
            assert caught.value is failure
        assert len(connections) == 1
        assert connections[0].close_calls == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connections[0].execute("SELECT 1")
        assert not stores[0].lock.is_locked
        monkeypatch.setattr(sqlite3, "connect", original_connect)
        with closing(ResearchStore(path)) as replacement:
            assert replacement.lock.is_locked
    finally:
        for connection in connections:
            sqlite3.Connection.close(connection)
        for store in stores:
            store.lock.release()


def test_sqlite_open_failure_releases_writer_lock(tmp_path, monkeypatch):
    path = tmp_path / "open.db"
    original_connect = sqlite3.connect
    with monkeypatch.context() as fault:

        def fail_open(*_args, **_kwargs):
            raise sqlite3.OperationalError("storage unavailable")

        fault.setattr(sqlite3, "connect", fail_open)
        with pytest.raises(VerboisyError, match="Cannot open research ledger"):
            ResearchStore(path)
    assert sqlite3.connect is original_connect
    with closing(ResearchStore(path)) as replacement:
        assert replacement.lock.is_locked
