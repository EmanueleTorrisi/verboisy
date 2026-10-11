# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Measure a real disk-backed JSONL job, interrupted resume and portable export on Linux.

The workload contains distinct records, not a sparse file or repeated row ID.
Generation, capture/preparation, resume/export and independent bundle verification
are timed separately. Temporary inputs, ledger and exports are removed afterward.
"""

import argparse
import hashlib
import json
import resource
import sys
import tempfile
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from verboisy.streaming import StreamLedger, StreamLimits, stream_dataset
from verboisy.utils.config import Settings


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--padding-bytes", type=int, default=1080)
    parser.add_argument("--work-dir", type=Path, default=Path())
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "linux" or args.rows < 2 or not 0 <= args.padding_bytes <= 100_000:
        parser.error("This measurement requires Linux, at least two rows and bounded padding")
    started = perf_counter()
    with tempfile.TemporaryDirectory(
        prefix="verboisy-stream-bench-", dir=args.work_dir
    ) as temporary:
        root = Path(temporary)
        source = root / "input.jsonl"
        database = root / "stream.db"
        output = root / "rows.jsonl"
        padding = "x" * args.padding_bytes
        with source.open("wb") as file:
            for start in range(0, args.rows, 1000):
                file.write(
                    b"".join(
                        (
                            json.dumps({"n": index, "padding": padding}, separators=(",", ":"))
                            + "\n"
                        ).encode()
                        for index in range(start, min(start + 1000, args.rows))
                    )
                )
        source_bytes = source.stat().st_size
        source_digest = digest(source)
        generated = perf_counter()
        limits = StreamLimits()
        schema = {
            "type": "object",
            "properties": {"n": {"type": "integer"}, "padding": {"type": "string"}},
            "required": ["n", "padding"],
            "additionalProperties": False,
        }
        first = stream_dataset(
            database=database,
            source=source,
            dataset_format="jsonl",
            schema=schema,
            config=Settings(_env_file=None, dataset_local_roots=[str(root)]),
            limits=limits,
            rows_per_invocation=args.rows // 2,
        )
        captured = perf_counter()
        assert first.status == "PAUSED" and first.processed_rows == args.rows // 2
        source.unlink()
        result = stream_dataset(
            database=database, resume=first.job_id, config=Settings(_env_file=None), export=output
        )
        prepared = perf_counter()
        assert result.status == "COMPLETED" and result.processed_rows == args.rows
        manifest = json.loads((root / "rows.jsonl.manifest.json").read_text())
        assert manifest["source_sha256"] == source_digest and result.input_bytes == source_bytes
        for name, expected in manifest["files"].items():
            assert digest(root / name) == expected
        with output.open() as records, (root / "rows.jsonl.evidence.jsonl").open() as evidence:
            count = 0
            for index, (line, proof_line) in enumerate(zip(records, evidence, strict=True)):
                value = json.loads(line)
                proof = json.loads(proof_line)
                assert value == {"n": index, "padding": padding}
                assert proof["output_row"] == proof["source_row"] == index + 1
                assert proof["source_values"] == value and proof["output_is_source"]
                count += 1
            assert count == args.rows
        with closing(StreamLedger(database, read_only=True)) as ledger:
            assert (
                ledger.page(result.job_id, after=args.rows - 1, limit=1)[0]["record"]["n"]
                == args.rows - 1
            )
        verified = perf_counter()
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        preparation_seconds = prepared - generated
        repository = Path(__file__).resolve().parents[1]
        implementation_files = [
            *sorted((repository / "src/verboisy/streaming").glob("*.py")),
            repository / "src/verboisy/cli/streaming.py",
            repository / "src/verboisy/cli/main.py",
            repository / "src/verboisy/__init__.py",
            Path(__file__).resolve(),
        ]
        report = {
            "copyright": "Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms.",
            "implementation_sha256": {
                str(path.relative_to(repository)): digest(path) for path in implementation_files
            },
            "measurement_version": "1",
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "workload": "distinct_jsonl_records_with_padding",
            "rows": args.rows,
            "input_bytes": source_bytes,
            "source_sha256": source_digest,
            "peak_rss_bytes": peak,
            "rss_ceiling_bytes": 201_326_592,
            "preparation_and_export_seconds": preparation_seconds,
            "end_to_end_rows_per_second": args.rows / preparation_seconds,
            "generation_seconds": generated - started,
            "initial_capture_and_half_admission_seconds": captured - generated,
            "resume_and_export_seconds": prepared - captured,
            "independent_verification_seconds": verified - prepared,
            "ledger_bytes": database.stat().st_size,
            "total_bundle_bytes": sum((root / name).stat().st_size for name in manifest["files"]),
            "resume_after_source_deletion": True,
            "all_output_rows_and_evidence_verified": True,
            "provider_requests": 0,
            "limits": asdict(limits),
            "qualification_passed": args.rows >= 1_000_000
            and source_bytes >= 1_073_741_824
            and peak <= 201_326_592
            and args.rows / preparation_seconds >= 5000,
        }
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["qualification_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
