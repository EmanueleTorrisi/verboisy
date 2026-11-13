# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Sealed segment contracts, bounded intake, and durability."""

import hashlib
import importlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from verboisy.streaming import JSONLSegmentResult, SealedJSONL, prepare_jsonl_segments, segments
from verboisy.streaming.contract import StreamError

module = segments
_OWNER_UID = module._uid


@pytest.fixture(autouse=True)
def private_metadata():
    # The production path enforces POSIX ownership/modes on Linux; elsewhere
    # use synthetic metadata while exercising the same I/O and catalog logic.
    if sys.platform == "linux":
        yield
        return
    real_lstat = module._lstat

    def metadata(path):
        result = real_lstat(path)
        values = list(result)
        if stat.S_ISDIR(result.st_mode):
            values[0] = stat.S_IFDIR | 0o700
        values[4] = 1  # st_uid
        return type(result)(values)

    with (
        patch.object(module, "_uid", return_value=1),
        patch.object(module, "_lstat", metadata),
        patch.object(module, "_entry_stat", lambda entry: metadata(Path(entry.path))),
        patch.object(module, "_stamp", lambda info: (info.st_dev, info.st_ino, info.st_size)),
    ):
        yield


def workspace(tmp_path):
    root = tmp_path / "segments"
    root.mkdir(mode=0o700)
    return root


def source(tmp_path, sequence, raw=None):
    path = tmp_path / f"{sequence}.jsonl"
    if raw is None:
        raw = f'{{"sequence":{sequence},"present":false}}\n'.encode()
    path.write_bytes(raw)
    return SealedJSONL(sequence, path, hashlib.sha256(raw).hexdigest())


def test_order_independent_workers_and_bounded_intake(tmp_path):
    root = workspace(tmp_path)
    specs = [
        source(
            tmp_path, 1, '\ufeff{"sequence":1,"text":"東京"}\r\n\r\n{"sequence":1}\r\n'.encode()
        ),
        source(tmp_path, 2),
        source(tmp_path, 3),
        source(tmp_path, 4),
    ]
    finished_second = Event()
    pulled = []
    original = module._prepare

    def prepare(segment, *args):
        if segment.sequence == 1:
            assert finished_second.wait(5), "Second worker could not prepare independently"
        value = original(segment, *args)
        if segment.sequence == 2:
            finished_second.set()
        return value

    def producer():
        for item in specs:
            pulled.append(item.sequence)
            yield item

    with (
        patch.object(module, "_prepare", prepare),
        closing(prepare_jsonl_segments(producer(), workspace=root, workers=2)) as results,
    ):
        first = next(results)
        assert pulled == [1, 2]
        assert first.sequence == 1 and isinstance(first, JSONLSegmentResult)
        assert first.rows == 2
        assert not first.reused
        captured = first.directory / "rows.jsonl.source.bin"
        assert captured.read_bytes() == specs[0].path.read_bytes()
        proof_file = first.directory / "rows.jsonl.evidence.jsonl"
        lines = proof_file.read_text(encoding="utf-8").splitlines()
        proofs = [json.loads(line) for line in lines]
        assert [proof["line_start"] for proof in proofs] == [1, 3]
        assert [proof["source_values"] for proof in proofs] == [
            {"sequence": 1, "text": "東京"},
            {"sequence": 1},
        ]
        assert [result.sequence for result in results] == [2, 3, 4]
    assert pulled == [1, 2, 3, 4]
    assert list((root / ".segment-staging").iterdir()) == [root / ".segment-staging" / ".format"]


def test_streaming_exports_resolve_on_reload():
    api = importlib.import_module("verboisy.streaming")
    importlib.reload(api)
    assert api.SealedJSONL is SealedJSONL
    assert api.JSONLSegmentResult is JSONLSegmentResult
    assert api.prepare_jsonl_segments is prepare_jsonl_segments


def test_local_settings_ignore_dotenv_and_provider_environment(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENAI_API_KEY=fixture-from-file\nMAX_STEPS=invalid\n", encoding="utf-8")
    cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-from-env", "MAX_STEPS": "invalid"}):
            settings = module._LocalSettings(dataset_local_roots=[str(tmp_path)])
    finally:
        os.chdir(cwd)
    assert settings.openai_api_key is None and settings.max_steps > 0
    assert settings.input_files() == ()
    assert settings.dataset_local_roots == [str(tmp_path)]


def test_later_failure_and_retry_reuse_only_committed_work(tmp_path):
    root = workspace(tmp_path)
    first, invalid, later = (
        source(tmp_path, 1),
        source(tmp_path, 2, b'{"broken":}\n'),
        source(tmp_path, 3),
    )
    results = prepare_jsonl_segments([first, invalid, later], workspace=root, workers=3)
    committed = next(results)
    with pytest.raises(StreamError, match="segment 2 did not complete"):
        next(results)
    assert not (root / "segment-0000000000000000002").exists()
    assert not (root / "segment-0000000000000000003").exists()
    with closing(sqlite3.connect(root / "segments.db")) as db:
        assert db.execute("SELECT sequence FROM segments ORDER BY sequence").fetchall() == [(1,)]
    first.path.unlink()
    second = source(tmp_path, 2)
    replay, repaired, final = prepare_jsonl_segments([first, second, later], workspace=root)
    assert (replay.reused, repaired.reused, final.reused) == (True, False, False)
    assert replay.receipt_sha256 == committed.receipt_sha256
    conflict = SealedJSONL(first.sequence, first.path, "0" * 64)
    with pytest.raises(StreamError, match="different identity"):
        list(prepare_jsonl_segments([conflict], workspace=root))
    record = replay.directory / "rows.jsonl"
    record.write_bytes(record.read_bytes().replace(b"false", b"true "))
    with pytest.raises(StreamError, match="committed segment file changed"):
        list(prepare_jsonl_segments([first], workspace=root))


def test_retry_after_bundle_rename_before_catalog_commit(tmp_path):
    root = workspace(tmp_path)
    one, two = source(tmp_path, 1), source(tmp_path, 2)
    (prior,) = prepare_jsonl_segments([one], workspace=root)
    stable = (prior.directory / "segment.json").stat().st_ino

    def after_rename(_db, target, stage, _segment, _receipt):
        (stage / "bundle").rename(target)
        raise OSError("interrupted before commit")

    with (
        patch.object(module, "_commit", after_rename),
        pytest.raises(StreamError, match="interrupted before commit"),
    ):
        list(prepare_jsonl_segments([two], workspace=root))
    orphan = root / "segment-0000000000000000002"
    assert orphan.is_dir()
    with closing(sqlite3.connect(root / "segments.db")) as db:
        assert db.execute("SELECT sequence FROM segments ORDER BY sequence").fetchall() == [(1,)]
    stale = root / ".segment-staging" / (".stage-" + "a" * 32)
    stale.mkdir(mode=0o700)
    (stale / "incomplete").write_text("old scratch", encoding="utf-8")
    (result,) = prepare_jsonl_segments([two], workspace=root)
    assert result.directory == orphan and not result.reused and not stale.exists()
    assert (prior.directory / "segment.json").stat().st_ino == stable
    (reused,) = prepare_jsonl_segments([two], workspace=root)
    assert reused.reused


def test_stop_early_and_competing_writer_do_not_leave_uncommitted_segments(tmp_path):
    root = workspace(tmp_path)
    one, two = source(tmp_path, 1), source(tmp_path, 2)
    with closing(prepare_jsonl_segments([one, two], workspace=root, workers=2)) as results:
        assert next(results).sequence == 1
        with pytest.raises(StreamError, match="workspace is already in use"):
            list(prepare_jsonl_segments([two], workspace=root))
    assert not (root / "segment-0000000000000000002").exists()
    (second,) = prepare_jsonl_segments([two], workspace=root)
    assert second.sequence == 2


def test_limits_contract_and_alias_checks(tmp_path):
    root = workspace(tmp_path)
    one, two = source(tmp_path, 1), source(tmp_path, 2)
    with pytest.raises(StreamError, match="one to four"):
        list(prepare_jsonl_segments([one], workspace=root, workers=True))
    with pytest.raises(StreamError, match="byte, record or row limit"):
        list(prepare_jsonl_segments([one], workspace=root, max_record_bytes=0))
    with pytest.raises(StreamError, match="Schema must be"):
        list(prepare_jsonl_segments([one], workspace=root, schema=[]))
    with pytest.raises(StreamError, match="numbers must be contiguous"):
        list(prepare_jsonl_segments([two], workspace=root))
    with pytest.raises(StreamError, match="must increase"):
        list(prepare_jsonl_segments([one, one], workspace=root, workers=2))
    with pytest.raises(StreamError, match="positive segment number"):
        list(prepare_jsonl_segments([SealedJSONL(True, one.path, one.sha256)], workspace=root))
    with pytest.raises(StreamError, match="SHA-256"):
        list(prepare_jsonl_segments([SealedJSONL(1, one.path, "0" * 64)], workspace=root))
    alias = root / "input.jsonl"
    alias.write_bytes(one.path.read_bytes())
    with pytest.raises(StreamError, match="outside the output workspace"):
        list(prepare_jsonl_segments([SealedJSONL(1, alias, one.sha256)], workspace=root))
    linked = tmp_path / "linked.jsonl"
    os.link(one.path, linked)
    with pytest.raises(StreamError, match="unlinked regular"):
        list(prepare_jsonl_segments([SealedJSONL(1, linked, one.sha256)], workspace=root))
    linked.unlink()
    (committed,) = prepare_jsonl_segments([one], workspace=root)
    assert committed.rows == 1
    with pytest.raises(StreamError, match="saved sealed JSONL contract differs"):
        list(prepare_jsonl_segments([two], workspace=root, schema={"required": ["sequence"]}))


def test_private_catalog_and_staging_preserve_unrelated_files(tmp_path):
    root = workspace(tmp_path)
    one = source(tmp_path, 1)
    with (
        patch.object(module, "_private_dir", return_value=False),
        pytest.raises(StreamError, match="owner-only workspace"),
    ):
        list(prepare_jsonl_segments([one], workspace=root))
    with closing(sqlite3.connect(root / "segments.db")) as db, db:
        db.execute("CREATE TABLE other(value)")
    before = (root / "segments.db").read_bytes()
    with pytest.raises(StreamError, match="unrelated database"):
        list(prepare_jsonl_segments([one], workspace=root))
    assert (root / "segments.db").read_bytes() == before
    (root / "segments.db").unlink()
    staging = root / ".segment-staging"
    staging.mkdir(mode=0o700)
    unrelated = staging / "unrelated"
    unrelated.write_bytes(b"keep")
    with pytest.raises(StreamError, match="sealed JSONL staging directory"):
        list(prepare_jsonl_segments([one], workspace=root))
    assert unrelated.read_bytes() == b"keep"


def test_segment_byte_record_and_row_ceilings_are_distinct(tmp_path):
    one = source(tmp_path, 1, b'{"value":"large"}\n')
    root = workspace(tmp_path)
    with pytest.raises(StreamError, match="file exceeds its byte limit"):
        list(prepare_jsonl_segments([one], workspace=root, max_segment_bytes=8))
    other = tmp_path / "record-limit"
    other.mkdir(mode=0o700)
    with pytest.raises(StreamError, match="record byte limit"):
        list(prepare_jsonl_segments([one], workspace=other, max_record_bytes=8))
    row_limited = tmp_path / "row-limit"
    row_limited.mkdir(mode=0o700)
    two_rows = source(tmp_path, 1, b"{}\n{}\n")
    with pytest.raises(StreamError, match="row limit"):
        list(prepare_jsonl_segments([two_rows], workspace=row_limited, max_segment_rows=1))


def test_empty_catalog_and_interrupted_marker_creation_resume(tmp_path):
    root = workspace(tmp_path)
    (root / "segments.db").touch()
    scratch = root / ".segment-staging"
    scratch.mkdir(mode=0o700)
    pending = scratch / ".marker-123abcde"
    pending.write_bytes(b"verboisy sealed")
    one = source(tmp_path, 1)
    (committed,) = prepare_jsonl_segments([one], workspace=root)
    assert committed.rows == 1
    assert list(scratch.iterdir()) == [scratch / ".format"]


def test_platform_refusal():
    with (
        patch.object(module, "sys", SimpleNamespace(platform="win32")),
        pytest.raises(StreamError, match="require Linux or WSL"),
    ):
        _OWNER_UID()


def test_ancestor_refusal(tmp_path):
    root = workspace(tmp_path)
    metadata = module._lstat

    def unsafe(path):
        info = metadata(path)
        if path == root.parent:
            values = list(info)
            values[0] = stat.S_IFDIR | 0o777
            return type(info)(values)
        return info

    with (
        patch.object(module, "_lstat", unsafe),
        pytest.raises(StreamError, match="unsafe ancestor"),
    ):
        list(prepare_jsonl_segments([], workspace=root))


@pytest.mark.skipif(sys.platform != "linux", reason="Linux hard stop")
def test_forced_process_exit_preserves_committed_prefix(tmp_path):
    root = workspace(tmp_path)
    one, two = source(tmp_path, 1), source(tmp_path, 2)
    (first,) = prepare_jsonl_segments([one], workspace=root)
    before = (first.directory / "segment.json").read_bytes()
    source_root = Path(module.__file__).resolve().parents[2]
    code = """
import os
import sys
from pathlib import Path
from unittest.mock import patch

root, path, sha, source_root = sys.argv[1:]
sys.path.insert(0, source_root)

from verboisy.streaming import SealedJSONL, prepare_jsonl_segments
from verboisy.streaming import segments

assert Path(segments.__file__).resolve() == Path(source_root) / "verboisy/streaming/segments.py"

def stop(_db, target, stage, _segment, _receipt):
    (stage / "bundle").rename(target)
    os._exit(73)

with patch.object(segments, "_commit", stop):
    list(prepare_jsonl_segments([SealedJSONL(2, Path(path), sha)], workspace=Path(root)))
"""
    result = subprocess.run(
        [sys.executable, "-IB", "-c", code, str(root), str(two.path), two.sha256, str(source_root)],
        check=False,
        timeout=10,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 73
    (second,) = prepare_jsonl_segments([two], workspace=root)
    assert second.rows == 1
    assert (first.directory / "segment.json").read_bytes() == before
