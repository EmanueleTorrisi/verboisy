# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Every captured chunk remains verified before any export generation is published."""

import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest
from verboisy.streaming import StreamLedger, StreamLimits, stream_dataset
from verboisy.streaming.contract import CHUNK_BYTES, StreamError
from verboisy.streaming.export import bundle_paths, export_stream
from verboisy.utils.config import Settings


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            value.update(chunk)
    return value.hexdigest()


@pytest.mark.parametrize("source_format", ["jsonl", "asset"])
@pytest.mark.parametrize("suffix", ["jsonl", "json", "csv"])
@pytest.mark.parametrize("position", ["first", "middle", "last"])
def test_corrupt_source_chunk_preserves_the_previous_export_generation(
    tmp_path, source_format, suffix, position
):
    with tempfile.TemporaryDirectory(dir=tmp_path) as temporary:
        root = Path(temporary)
        source = root / "source.bin"
        with source.open("wb") as stream:
            for index in range(4):
                record = {"ordinal": index, "payload": "x" * 600000}
                stream.write((json.dumps(record) + "\n").encode())
        source_hash = digest(source)
        database = root / "stream.db"
        result = stream_dataset(
            database=database,
            source=source,
            dataset_format=source_format,
            config=Settings(_env_file=None, dataset_local_roots=[str(root)]),
            limits=StreamLimits(
                max_input_bytes=4 * CHUNK_BYTES, max_storage_bytes=16 * CHUNK_BYTES
            ),
            csv_mode="json",
        )
        assert result.status == "COMPLETED"
        assert result.processed_rows == (4 if source_format == "jsonl" else 1)
        output = root / ("rows." + suffix)
        with closing(StreamLedger(database, read_only=True)) as ledger:
            export_stream(ledger, ledger.job(result.job_id), output)
        paths = bundle_paths(output)
        before = {path.name: digest(path) for path in paths}
        manifest = json.loads(paths[3].read_text(encoding="utf-8"))
        assert manifest["source_sha256"] == source_hash
        for name, expected in manifest["files"].items():
            assert digest(root / name) == expected
        with closing(sqlite3.connect(database)) as connection, connection:
            chunks = connection.execute("SELECT seq FROM stream_chunks ORDER BY seq").fetchall()
            assert len(chunks) >= 3
            index = {"first": 0, "middle": len(chunks) // 2, "last": len(chunks) - 1}[position]
            sequence = chunks[index][0]
            raw = connection.execute(
                "SELECT content FROM stream_chunks WHERE seq=?", (sequence,)
            ).fetchone()[0]
            corrupted = bytes([raw[0] ^ 1]) + raw[1:]
            connection.execute(
                "UPDATE stream_chunks SET content=? WHERE seq=?", (corrupted, sequence)
            )
        with (
            closing(StreamLedger(database, read_only=True)) as ledger,
            pytest.raises(StreamError),
        ):
            export_stream(ledger, ledger.job(result.job_id), output)
        assert {path.name: digest(path) for path in paths} == before
        assert not list(root.glob(".verboisy-stream-*"))
