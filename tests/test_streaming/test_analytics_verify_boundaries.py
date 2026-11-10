# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""A failed or changing bundle must never produce a successful verification."""

import gzip
import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from verboisy.streaming import analytics_verify, verify_stream_analytics
from verboisy.streaming.analytics_verify_io import CheckedReader, regular_file, stable_directory
from verboisy.streaming.contract import StreamError


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _metadata(value, **changes):
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    return SimpleNamespace(**({key: getattr(value, key) for key in fields} | changes))


class BundleBoundaries(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = self.root / "manifest.json"
        self.data = self.root / "part-00000.jsonl.gz"
        proof = self.root / "part-00000.evidence.jsonl.gz"
        empty = gzip.compress(b"", mtime=0)
        self.data.write_bytes(empty)
        proof.write_bytes(empty)
        self.info = {
            "version": "stream-analytics-1",
            "job_id": "a" * 32,
            "format": "jsonl.gz",
            "compression": "gzip",
            "rows": 0,
            "schema": {},
            "column_contract": None,
            "source": {
                "bytes": 0,
                "sha256": _sha(b""),
                "format": "jsonl",
                "contract_sha256": _sha(b"contract"),
                "capture_included": False,
            },
            "row_digest": "sha256_of_verified_utf8_json_before_encoding",
            "shards": [
                {
                    "first_output_row": 1,
                    "rows": 0,
                    "data": {"name": self.data.name, "bytes": len(empty), "sha256": _sha(empty)},
                    "evidence": {"name": proof.name, "bytes": len(empty), "sha256": _sha(empty)},
                }
            ],
            "truth_verified": False,
            "global_completeness_claimed": False,
        }
        self._save(self.info)

    def _save(self, info):
        self.manifest.write_text(json.dumps(info) + "\n", encoding="utf-8")

    def test_missing_and_unknown_manifest_fields_fail(self):
        missing = dict(self.info)
        del missing["schema"]
        for manifest in ([], missing, {**self.info, "extra": True}):
            with (
                self.subTest(manifest=type(manifest)),
                self.assertRaisesRegex(StreamError, "Invalid analytical manifest fields"),
            ):
                self._save(manifest)
                verify_stream_analytics(self.root)

    def test_invalid_digest_and_source_claims_fail_before_files_are_read(self):
        for pin in (1, "not-a-digest"):
            with self.subTest(pin=pin), self.assertRaisesRegex(StreamError, "64 lowercase"):
                verify_stream_analytics(self.root, expected_manifest_sha256=pin)
        source = self.info["source"]
        for changes in ({"format": "asset"}, {"capture_included": True}):
            with (
                self.subTest(changes=changes),
                self.assertRaisesRegex(StreamError, "Unsupported analytical source"),
            ):
                self._save({**self.info, "source": {**source, **changes}})
                verify_stream_analytics(self.root)

    def test_shard_cannot_claim_a_gap_or_extra_empty_shard(self):
        shard = self.info["shards"][0]
        for ranges in ([{**shard, "first_output_row": 2}], [shard, shard]):
            with self.subTest(ranges=ranges), self.assertRaisesRegex(StreamError, "not contiguous"):
                self._save({**self.info, "shards": ranges})
                verify_stream_analytics(self.root)

    def test_truncated_file_is_rejected_against_original_manifest(self):
        raw = self.data.read_bytes()
        self.data.write_bytes(raw[:-1])
        with self.assertRaisesRegex(StreamError, "byte count differs"):
            verify_stream_analytics(self.root)
        self.data.write_bytes(raw + b"x")
        with self.assertRaisesRegex(StreamError, "size limit"):
            verify_stream_analytics(self.root)

    def test_manifest_short_read_is_not_a_complete_result(self):
        raw = self.manifest.read_bytes()

        @contextmanager
        def interrupted_read(_path, _ceiling):
            with io.BytesIO(raw[:-1]) as stream:
                yield stream, len(raw)

        with (
            patch.object(analytics_verify, "regular_file", interrupted_read),
            self.assertRaisesRegex(StreamError, "manifest changed while reading"),
        ):
            verify_stream_analytics(self.root)

    def test_extra_proof_cannot_be_hidden_behind_zero_declared_rows(self):
        entry = self.info["shards"][0]["evidence"]
        raw = gzip.compress(b"{}\n", mtime=0)
        (self.root / entry["name"]).write_bytes(raw)
        entry.update(bytes=len(raw), sha256=_sha(raw))
        self._save(self.info)
        with self.assertRaisesRegex(StreamError, "extra rows"):
            verify_stream_analytics(self.root)

    def test_directory_and_special_file_checks_are_read_only(self):
        with self.assertRaisesRegex(StreamError, "real analytical bundle directory"):
            verify_stream_analytics(self.manifest)
        with self.assertRaisesRegex(StreamError, "unlinked regular"), regular_file(self.root, 100):
            self.fail("A directory must not be opened as a file")
        directory = self.root.stat()
        linked = _metadata(directory, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        with (
            patch.object(Path, "lstat", return_value=linked),
            self.assertRaisesRegex(StreamError, "real analytical bundle directory"),
        ):
            verify_stream_analytics(self.root)
        symlink = _metadata(self.data.stat(), st_mode=stat.S_IFLNK | 0o777)
        with (
            patch.object(Path, "lstat", return_value=symlink),
            self.assertRaisesRegex(StreamError, "unlinked regular"),
            regular_file(self.data, 100),
        ):
            self.fail("A link must not be opened as a file")

    def test_directory_membership_change_is_detected(self):
        before = self.root.stat()
        with self.assertRaisesRegex(StreamError, "directory changed"), stable_directory(self.root):
            (self.root / "late-arrival").write_bytes(b"data")
            # Use a distinct mtime even on filesystems with coarse timestamps.
            os.utime(self.root, ns=(before.st_atime_ns, before.st_mtime_ns - 10_000_000_000))

    def test_replacement_between_stat_and_open_is_refused(self):
        replacement = self.root / "replacement"
        replacement.write_bytes(b"Replacement file")
        original_open = os.open

        def replace(path, flags):
            replacement.replace(self.data)
            return original_open(path, flags)

        with (
            patch.object(os, "open", replace),
            self.assertRaisesRegex(StreamError, "file changed before reading"),
            regular_file(self.data, 100),
        ):
            self.fail("An inode that changed before open must not be read")

    def test_file_change_during_read_is_detected(self):
        before = self.data.stat()
        with (
            self.assertRaisesRegex(StreamError, "file changed during verification"),
            regular_file(self.data, 100) as (stream, size),
        ):
            self.assertEqual(len(stream.read()), size)
            os.utime(self.data, ns=(before.st_atime_ns, before.st_mtime_ns - 10_000_000_000))

    def test_pathname_is_checked_again_after_read(self):
        original = self.data.lstat()
        replacement = _metadata(original, st_ino=original.st_ino + 1)
        with (
            patch.object(Path, "lstat", side_effect=[original, replacement]),
            self.assertRaisesRegex(StreamError, "file changed during verification"),
            regular_file(self.data, 100) as (stream, size),
        ):
            self.assertEqual(len(stream.read()), size)

    def test_reader_hashes_buffered_bytes_and_refuses_growth_or_short_read(self):
        raw = b"012345"
        with (
            CheckedReader(io.BytesIO(raw), len(raw)) as reader,
            io.BufferedReader(reader) as stream,
        ):
            self.assertEqual(stream.read(), raw)
            reader.finish(_sha(raw))
        with (
            CheckedReader(io.BytesIO(raw + b"x"), len(raw)) as reader,
            self.assertRaisesRegex(StreamError, "grew while reading"),
        ):
            reader.read()
        with CheckedReader(io.BytesIO(raw[:-1]), len(raw)) as reader:
            self.assertEqual(reader.read(), raw[:-1])
            with self.assertRaisesRegex(StreamError, "SHA-256"):
                reader.finish(_sha(raw))
