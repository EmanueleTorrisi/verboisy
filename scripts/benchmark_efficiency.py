# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Small, reproducible JSONL preparation/resume/export measurement; no model calls.

Each invocation uses a fresh process and disposable files. The same eight-column
typed workload is independently regenerated when checking every exported row and
proof. Performance measurements exclude imports, generation and verification;
those phases are reported separately by the qualification driver.
"""

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from time import perf_counter


class BenchmarkError(RuntimeError):
    """A measured result failed an independent correctness check."""


def require(condition, message):
    if not condition:
        raise BenchmarkError(message)


def record(index):
    return {
        "sequence": index,
        "name": "Pécsi-東京-" + str(index),
        "price": index / 10,
        "available": index % 2 == 0,
        "missing": None,
        "features": [index % 7, index % 13],
        "group": "g" + str(index % 4),
        "padding": "x" * 64,
    }


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
    )


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            value.update(chunk)
    return value.hexdigest()


def verify_bundle(output, rows, input_hash):
    manifest = json.loads(output.with_name(output.name + ".manifest.json").read_text())
    require(manifest["source_sha256"] == input_hash, "Source digest changed")
    expected_files = {output.name, output.name + ".evidence.jsonl", output.name + ".source.bin"}
    require(set(manifest["files"]) == expected_files, "Incomplete portable bundle")
    for name, expected in manifest["files"].items():
        require(Path(name).name == name and name not in {".", ".."}, "Invalid bundle filename")
        require(digest(output.parent / name) == expected, "Bundle digest mismatch")
    require(
        digest(output.with_name(output.name + ".source.bin")) == input_hash,
        "Captured bytes changed",
    )
    count = 0
    with (
        output.open(encoding="utf-8") as data,
        output.with_name(output.name + ".evidence.jsonl").open(encoding="utf-8") as evidence,
    ):
        for index, (line, proof_line) in enumerate(zip(data, evidence, strict=True)):
            expected = canonical(record(index))
            proof = json.loads(proof_line)
            require(canonical(json.loads(line)) == expected, "Exported typed values changed")
            require(canonical(proof["source_values"]) == expected, "Proof source values changed")
            require(proof["source_row"] == proof["output_row"] == index + 1, "Row identity changed")
            require(
                proof["line_start"] == proof["line_end"] == index + 1, "Source location changed"
            )
            require(proof["output_is_source"] is True, "Unexpected transformation")
            count += 1
    require(count == rows, "Output count differs from the declared workload")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10000)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    if sys.platform != "linux" or not 1000 <= args.rows <= 50000:
        parser.error("This bounded measurement requires Linux and 1,000 to 50,000 rows")
    if args.source_root is not None:
        sys.path.insert(0, str(args.source_root.resolve() / "src"))
    import resource

    from verboisy.streaming import StreamLimits, stream_dataset
    from verboisy.utils.config import Settings

    start = perf_counter()
    with tempfile.TemporaryDirectory(prefix="efficiency-", dir=args.work_dir) as temporary:
        root = Path(temporary)
        source, database, output = root / "input.jsonl", root / "stream.db", root / "rows.jsonl"
        with source.open("w", encoding="utf-8", newline="\n") as stream:
            for index in range(args.rows):
                stream.write(
                    json.dumps(record(index), ensure_ascii=False, separators=(",", ":")) + "\n"
                )
        input_bytes, input_hash = source.stat().st_size, digest(source)
        generated = perf_counter()
        schema = {
            "type": "object",
            "properties": {
                "sequence": {"type": "integer"},
                "name": {"type": "string"},
                "price": {"type": "number"},
                "available": {"type": "boolean"},
                "missing": {"type": "null"},
                "features": {"type": "array", "items": {"type": "integer"}},
                "group": {"type": "string"},
                "padding": {"type": "string"},
            },
            "required": list(record(0)),
            "additionalProperties": False,
        }
        first = stream_dataset(
            database=database,
            source=source,
            dataset_format="jsonl",
            schema=schema,
            config=Settings(_env_file=None, dataset_local_roots=[str(root)]),
            rows_per_invocation=args.rows // 3,
            limits=StreamLimits(
                max_rows=args.rows,
                max_input_bytes=16_777_216,
                max_record_bytes=8192,
                max_storage_bytes=134_217_728,
            ),
        )
        require(
            first.status == "PAUSED" and first.processed_rows == args.rows // 3,
            "Pause checkpoint failed",
        )
        source.unlink()
        result = stream_dataset(
            database=database, resume=first.job_id, config=Settings(_env_file=None), export=output
        )
        prepared = perf_counter()
        require(
            result.status == "COMPLETED" and result.processed_rows == args.rows,
            "Resume did not complete",
        )
        require(
            result.input_bytes == input_bytes and result.source_sha256 == input_hash,
            "Capture metadata changed",
        )
        verify_bundle(output, args.rows, input_hash)
        verified = perf_counter()
        report = {
            "measurement_version": "efficiency-1",
            "rows": args.rows,
            "input_bytes": input_bytes,
            "input_sha256": input_hash,
            "output_sha256": digest(output),
            "generation_seconds": generated - start,
            "prepare_resume_export_seconds": prepared - generated,
            "independent_verification_seconds": verified - prepared,
            "rows_per_second": args.rows / (prepared - generated),
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "temporary_files_bytes": sum(
                path.stat().st_size for path in root.iterdir() if path.is_file()
            ),
            "all_output_rows_and_proofs_checked": True,
            "resume_after_source_deletion": True,
            "model_requests": 0,
            "python": sys.version,
            "platform": sys.platform,
            "scope": (
                "Deterministic synthetic JSONL regression; "
                "not live research or independent acceptance"
            ),
        }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
