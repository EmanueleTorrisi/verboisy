# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Strict boundaries reject ambiguous JSON and unsafe file reads without coercion."""

import os

import pytest
from verboisy.storage.json_payload import decode_saved_json
from verboisy.utils.json_payload import decode_json, read_bytes, read_json_object


@pytest.mark.parametrize(
    "text",
    [
        '{"x":1,"x":2}',
        '{"x":1,"\\u0078":2}',
        '{"a":[{"x":0,"x":1}]}',
        '{"x":1e999}',
        "NaN",
        "Infinity",
        "-Infinity",
        '"\\ud800"',
        '{"\\udfff":0}',
        b'"\xff"',
        "",
        "{",
    ],
)
def test_strict_boundaries(text):
    with pytest.raises(ValueError):
        decode_json(text)
    with pytest.raises(ValueError):
        decode_saved_json(text)


def test_native_json_order_unicode_integer_and_omission():
    value = decode_json('{"z":1000000000000000000000000,"a":"Anaïs","n":null}')
    assert list(value) == ["z", "a", "n"]
    assert value["z"] == 10**24 and value["a"] == "Anaïs" and "missing" not in value
    assert decode_json(bytearray(b'{"a":true}')) == {"a": True}


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_limits(tmp_path, limit):
    with pytest.raises(ValueError):
        read_json_object(tmp_path / "file", max_bytes=limit)


def test_file_limits_shapes_and_nonregular(tmp_path):
    path = tmp_path / "file"
    path.write_text('{"ok":1}')
    before = path.read_bytes()
    assert read_json_object(path, max_bytes=len(before)) == {"ok": 1}
    with pytest.raises(ValueError):
        read_json_object(path, max_bytes=len(before) - 1)
    path.write_text("[]")
    with pytest.raises(ValueError):
        read_json_object(path)
    assert read_bytes(path, max_bytes=2) == b"[]"
    if hasattr(os, "mkfifo"):
        pipe = tmp_path / "pipe"
        os.mkfifo(pipe)
        with pytest.raises(ValueError):
            read_json_object(pipe)


def test_changed_opened_metadata_rejected(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from verboisy.utils import json_payload

    path = tmp_path / "file"
    path.write_text("{}")
    real = json_payload.os.fstat
    calls = 0

    def changed(fd):
        nonlocal calls
        info = real(fd)
        calls += 1
        return SimpleNamespace(
            st_mode=info.st_mode,
            st_size=info.st_size,
            st_mtime_ns=info.st_mtime_ns + (calls > 1),
            st_ctime_ns=info.st_ctime_ns,
        )

    monkeypatch.setattr(json_payload.os, "fstat", changed)
    with pytest.raises(ValueError, match="changed"):
        read_json_object(path)


@pytest.mark.parametrize("payload", [None, False, 123])
def test_invalid_runtime_payload_type_is_safe(payload):
    with pytest.raises(ValueError):
        decode_json(payload)


def test_nonregular_opened_descriptor_without_fifo(tmp_path, monkeypatch):
    import stat
    from types import SimpleNamespace

    from verboisy.utils import json_payload

    path = tmp_path / "source.json"
    path.write_bytes(b"{}")

    original_fstat = json_payload.os.fstat

    def nonregular(fd):
        info = original_fstat(fd)
        return SimpleNamespace(
            st_mode=stat.S_IFIFO,
            st_size=info.st_size,
            st_mtime_ns=info.st_mtime_ns,
            st_ctime_ns=info.st_ctime_ns,
        )

    monkeypatch.setattr(json_payload.os, "fstat", nonregular)

    with pytest.raises(ValueError, match="regular file"):
        read_bytes(path, max_bytes=2)
