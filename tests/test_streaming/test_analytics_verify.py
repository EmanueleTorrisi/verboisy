# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""A recipient can verify analytics without trusting the manifest or owning the ledger."""

import gzip
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from verboisy.streaming import verify_stream_analytics
from verboisy.streaming.contract import StreamError

JOB = "b" * 32


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _record(path, raw):
    path.write_bytes(raw)
    return {"name": path.name, "bytes": len(raw), "sha256": _sha(raw)}


def _gzip(lines):
    return gzip.compress(b"".join(line + b"\n" for line in lines), mtime=0)


class AnalyticsVerificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "bundle"
        self.directory.mkdir()
        self.manifest_path = self.directory / "manifest.json"

    def _bundle(self, *, parquet=False, groups=((b'{"n":1}', b'{"n":false}'), (b'{"n":null}',))):
        fmt = "parquet" if parquet else "jsonl.gz"
        ordinal = 0
        shards = []
        for index, rows in enumerate(groups):
            start = ordinal + 1
            proof = []
            for row in rows:
                ordinal += 1
                proof.append(
                    _json(
                        {
                            "output_row": ordinal,
                            "source_row": ordinal,
                            "line_start": ordinal * 2,
                            "line_end": ordinal * 2,
                            "record_id": _sha(f"verboisy:stream:{JOB}:{ordinal}".encode()),
                            "output_sha256": _sha(row),
                        }
                    )
                )
            stem = f"part-{index:05d}"
            # The verifier treats the Parquet payload as opaque bytes.
            data = _record(
                self.directory / f"{stem}.{fmt}",
                b"opaque columnar fixture" if parquet else _gzip(rows),
            )
            evidence = _record(self.directory / f"{stem}.evidence.jsonl.gz", _gzip(proof))
            shards.append(
                {"first_output_row": start, "rows": len(rows), "data": data, "evidence": evidence}
            )
        self.manifest = {
            "version": "stream-analytics-1",
            "job_id": JOB,
            "format": fmt,
            "compression": "zstd" if parquet else "gzip",
            "rows": ordinal,
            "schema": {"type": "object"},
            "column_contract": {
                "version": "1",
                "columns": [{"name": "n", "type": "json", "nullable": True}],
            }
            if parquet
            else None,
            "source": {
                "bytes": 217,
                "sha256": "0" * 64,
                "contract_sha256": "1" * 64,
                "format": "jsonl",
                "capture_included": False,
            },
            "row_digest": "sha256_of_verified_utf8_json_before_encoding",
            "shards": shards,
            "truth_verified": False,
            "global_completeness_claimed": False,
        }
        return self._save()

    def _save(self):
        raw = _json(self.manifest) + b"\n"
        self.manifest_path.write_bytes(raw)
        return _sha(raw)

    def _change(self, entry, raw):
        path = self.directory / entry["name"]
        entry.update(_record(path, raw))
        self._save()

    def _verify(self, **options):
        return verify_stream_analytics(self.directory, **options)

    def test_pinned_gzip_binds_every_row_proof_and_file(self):
        pin = self._bundle(groups=((_json({"n": "Café 東京"}),), (b'{"n":null}',)))
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        result = self._verify(expected_manifest_sha256=pin, require_row_checks=True)
        self.assertTrue(result.manifest_pinned)
        self.assertEqual(result.manifest_sha256, pin)
        self.assertEqual(
            (result.shards, result.rows, result.proof_rows_verified, result.data_rows_verified),
            (2, 2, 2, 2),
        )
        self.assertEqual(result.bundle_bytes, sum(map(len, before.values())))
        self.assertGreater(result.decoded_bytes, 0)
        self.assertFalse(result.source_replayed)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.iterdir()})
        with self.assertRaisesRegex(StreamError, "expected digest"):
            self._verify(expected_manifest_sha256="f" * 64)

    def test_parquet_reports_only_what_was_verified(self):
        self._bundle(parquet=True, groups=((b'{"n":1}',),))
        result = self._verify()
        self.assertEqual((result.format, result.proof_rows_verified), ("parquet", 1))
        self.assertIsNone(result.data_rows_verified)
        self.assertFalse(result.manifest_pinned)
        with self.assertRaisesRegex(StreamError, "only for gzip JSONL"):
            self._verify(require_row_checks=True)
        path = self.directory / self.manifest["shards"][0]["data"]["name"]
        path.write_bytes(b"x" + path.read_bytes()[1:])
        with self.assertRaisesRegex(StreamError, "SHA-256"):
            self._verify()

    def test_empty_bundle_is_an_explicit_zero_row_shard(self):
        self._bundle(groups=((),))
        result = self._verify()
        self.assertEqual(
            (result.rows, result.data_rows_verified, result.proof_rows_verified), (0, 0, 0)
        )

    def test_same_size_replacement_and_self_consistent_hashes_do_not_hide_row_change(self):
        self._bundle(groups=((b'{"n":1}',),))
        shard = self.manifest["shards"][0]["data"]
        self._change(shard, _gzip((b'{"n":2}',)))
        with self.assertRaisesRegex(StreamError, "digest differs from its proof"):
            self._verify()

    def test_proof_must_keep_original_row_identity_and_sequence(self):
        self._bundle()
        entry = self.manifest["shards"][0]["evidence"]
        path = self.directory / entry["name"]
        valid = gzip.decompress(path.read_bytes()).splitlines()
        proof = json.loads(valid[0])
        for key, value in (
            ("output_row", 2),
            ("source_row", 2),
            ("record_id", "f" * 64),
            ("line_end", 3),
            ("line_start", True),
        ):
            with self.subTest(key=key):
                self._change(entry, _gzip((_json({**proof, key: value}), valid[1])))
                with self.assertRaises(StreamError):
                    self._verify()

    def test_byte_and_record_limits_stop_before_unbounded_decode(self):
        self._bundle()
        good = self._verify()
        for limits, detail in (
            ({"max_bundle_bytes": good.bundle_bytes - 1}, "bundle exceeds its byte limit"),
            ({"max_decoded_bytes": good.decoded_bytes - 1}, "decoded byte limit"),
            ({"max_row_bytes": 3}, "oversized row"),
            ({"max_row_bytes": True}, "must be an integer"),
            ({"require_row_checks": 1}, "must be a boolean"),
        ):
            with self.subTest(limits=limits), self.assertRaisesRegex(StreamError, detail):
                self._verify(**limits)

    def test_shards_must_match_count_and_have_no_hidden_rows(self):
        self._bundle(groups=((b'{"n":1}',),))
        data = self.manifest["shards"][0]["data"]
        for raw, detail in (
            (_gzip((b'{"n":1}', b'{"n":2}')), "extra rows"),
            (gzip.compress(b'{"n":1}', mtime=0), "final newline"),
            (_gzip((b'{"n":1}',))[:-3], "complete, valid"),
        ):
            with self.subTest(detail=detail):
                self._change(data, raw)
                with self.assertRaisesRegex(StreamError, detail):
                    self._verify()

    def test_invalid_json_with_matching_hash_is_rejected(self):
        for raw in (b'{"n":1,"n":2}', b'{"n":1e999}', b'["not an object"]'):
            with self.subTest(raw=raw):
                self._bundle(groups=((raw,),))
                with self.assertRaises(StreamError):
                    self._verify()

    def test_manifest_cannot_name_external_or_unlisted_files(self):
        self._bundle()
        entry = self.manifest["shards"][0]["data"]
        name = entry["name"]
        entry["name"] = "../other.jsonl.gz"
        self._save()
        with self.assertRaisesRegex(StreamError, "canonical"):
            self._verify()
        entry["name"] = name
        self._save()
        extra = self.directory / "unlisted.jsonl"
        extra.write_bytes(b"{}\n")
        with self.assertRaisesRegex(StreamError, "unlisted"):
            self._verify()
        extra.unlink()
        (self.directory / name).unlink()
        with self.assertRaisesRegex(StreamError, "missing"):
            self._verify()

    def test_linked_shard_is_rejected_even_if_the_hash_matches(self):
        self._bundle()
        path = self.directory / self.manifest["shards"][0]["data"]["name"]
        outside = self.directory.parent / "outside.gz"
        os.link(path, outside)
        with self.assertRaisesRegex(StreamError, "unlinked regular"):
            self._verify()

    def test_claims_and_counts_cannot_be_promoted_by_the_manifest(self):
        self._bundle()
        for key, value, detail in (
            ("truth_verified", True, "Unsupported analytical manifest contract"),
            ("rows", True, "must be an integer"),
            ("rows", 200, "counts differ"),
            ("compression", "none", "format or compression"),
            ("shards", [], "invalid shard inventory"),
        ):
            with self.subTest(key=key, value=value):
                old = self.manifest[key]
                self.manifest[key] = value
                self._save()
                with self.assertRaisesRegex(StreamError, detail):
                    self._verify()
                self.manifest[key] = old

    def test_real_export_can_be_verified_after_source_and_ledger_are_removed(self):
        from verboisy import stream_dataset
        from verboisy.streaming import export_stream_analytics
        from verboisy.utils.config import Settings

        root = self.directory.parent
        dataset = root / "source.csv"
        dataset.write_bytes(b'id,note\n0001,"first\nsecond"\n0002,ordinary\n')
        database = root / "test.db"
        result = stream_dataset(
            database=database,
            source=dataset,
            dataset_format="csv",
            config=Settings(_env_file=None, dataset_local_roots=[str(root)]),
        )
        self.assertEqual((result.status, result.processed_rows), ("COMPLETED", 2))
        exported = export_stream_analytics(
            database=database,
            job_id=result.job_id,
            output_dir=root / "original",
            shard_rows=1,
        )
        shutil.rmtree(self.directory)
        shutil.move(str(exported.manifest.parent), str(self.directory))
        dataset.unlink()
        database.unlink()
        verified = self._verify(
            expected_manifest_sha256=_sha(self.manifest_path.read_bytes()),
            require_row_checks=True,
        )
        self.assertEqual((verified.shards, verified.data_rows_verified), (2, 2))
