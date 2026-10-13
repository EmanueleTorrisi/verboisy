# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Measure ordinary local acquisition through verified export and proof publication."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import platform
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

import verboisy
from verboisy import arun
from verboisy.utils.config import Settings


def positive(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 10000:
        raise argparse.ArgumentTypeError("Use an integer between 1 and 10000")
    return parsed


async def measure(counts: list[int], repeats: int) -> dict[str, object]:
    """Time capture, admission, result shaping, portable export and text proof.

    Each repetition uses a fresh ledger. Fixture generation is untimed; output
    validation follows timing. No browser, search or model request is made.
    """
    results = []
    for count in counts:
        observations = [{"name": f"Entity {index}", "value": index} for index in range(count)]
        raw = json.dumps(observations).encode()
        samples = []
        for _ in range(repeats):
            with tempfile.TemporaryDirectory(prefix="verboisy-ingestion-") as directory:
                root = Path(directory)
                source = root / "rows.json"
                source.write_bytes(raw)
                config = Settings(
                    _env_file=None,
                    sqlite_db_path=str(root / "run.db"),
                    dataset_local_roots=[str(root)],
                    search_provider="disabled",
                )
                cpu_start, wall_start = time.process_time(), time.perf_counter()
                result = await arun(
                    goal="Capture observed entities",
                    schema={
                        "type": "object",
                        "properties": {"name": {"type": "string"}, "value": {"type": "integer"}},
                        "required": ["name", "value"],
                        "additionalProperties": False,
                    },
                    dataset_sources=[{"format": "json", "url": source.as_uri()}],
                    task={"target_records": count},
                    export=root / "result.json",
                    proof=True,
                    config=config,
                )
                elapsed = time.perf_counter() - wall_start
                cpu = time.process_time() - cpu_start
                if result.status != "COMPLETED" or len(result.records) != count:
                    raise RuntimeError("Benchmark did not complete its declared row contract")
                output = json.loads((root / "result.json").read_text())
                values = [{key: row[key] for key in ("name", "value")} for row in output]
                if values != observations or not (root / "result.proof.txt").is_file():
                    raise RuntimeError("Benchmark output differs from finite source expectations")
                samples.append({"wall_seconds": elapsed, "cpu_seconds": cpu})
        median = statistics.median(sample["wall_seconds"] for sample in samples)
        results.append(
            {
                "records": count,
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "samples": samples,
                "median_wall_seconds": median,
                "median_records_per_second": count / median,
                "output_values_checked": True,
            }
        )
    # Fingerprint the imported implementation, allowing the same driver to measure
    # an isolated baseline selected with PYTHONPATH. Never assume the driver and
    # measured application are in the same checkout.
    source_root = Path(verboisy.__file__).resolve().parents[2]
    inputs = [source_root / "pyproject.toml", source_root / "poetry.lock"]
    inputs.extend(sorted((source_root / "src").rglob("*.py")))
    inputs.extend(sorted((source_root / "native").glob("*.[ch]pp")))
    report: dict[str, object] = {
        "benchmark_version": "ingestion-1",
        "python": sys.version,
        "platform": platform.platform(),
        "sqlite_version": sqlite3.sqlite_version,
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("pydantic", "jsonschema", "litellm", "httpx")
        },
        "source_hashes": {
            path.relative_to(source_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in inputs
        },
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "repeats": repeats,
        "method": "fresh ledgers; local JSON capture, admission, export and proof; no model work",
        "results": results,
    }
    if sys.platform in {"linux", "darwin"}:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report["process_peak_rss_bytes"] = rss * 1024 if sys.platform == "linux" else rss
        report["memory_scope"] = "process lifetime high-water RSS, including imports and all cases"
    else:
        report["memory_scope"] = "process RSS unavailable on this platform"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=positive, nargs="+", default=[50, 100, 200, 400])
    parser.add_argument("--repeats", type=positive, default=3)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(measure(args.counts, args.repeats)), indent=2))


if __name__ == "__main__":
    main()
