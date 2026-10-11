# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Measure snapshot decode and isolated-copy components without provider requests.

These local component timings exclude ledger queries, grounding and browser work;
they are not an end-to-end performance promise. Compare medians on the same host.
"""

import argparse
import json
from statistics import median
from time import perf_counter

from verboisy.evidence.models import Snapshot, Source
from verboisy.extractor.range_changes import _copy_snapshot
from verboisy.storage.json_payload import copy_saved_json, decode_saved_json


def positive(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("Use a positive integer")
    return parsed


def measure(action, iterations: int, repeats: int) -> float:
    samples = []
    for _ in range(repeats):
        start = perf_counter()
        for _ in range(iterations):
            action()
        samples.append(perf_counter() - start)
    return median(samples)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=positive, nargs="+", default=[20, 200, 1000])
    parser.add_argument("--iterations", type=positive, default=100)
    parser.add_argument("--repeats", type=positive, default=3)
    args = parser.parse_args()
    results = []
    for size in args.sources:
        page = Snapshot(
            id="benchmark",
            url="https://example.test/",
            fetched_at="fixture",
            content_hash="fixture",
            truncated=False,
            sources=[
                Source(id=f"e{index}", scope="s1", kind="text", text="Evidence text " * 20)
                for index in range(size)
            ],
        )
        raw = page.model_dump_json()
        decoded = decode_saved_json(raw)
        results.append(
            {
                "sources": size,
                "iterations": args.iterations,
                "repeats": args.repeats,
                "validated_decode_seconds": measure(
                    lambda raw=raw: Snapshot.model_validate(decode_saved_json(raw)),
                    args.iterations,
                    args.repeats,
                ),
                "isolated_model_copy_seconds": measure(
                    lambda page=page: _copy_snapshot(page), args.iterations, args.repeats
                ),
                "isolated_json_copy_seconds": measure(
                    lambda decoded=decoded: copy_saved_json(decoded), args.iterations, args.repeats
                ),
            }
        )
    print(json.dumps({"scope": "local_components", "results": results}, indent=2))


if __name__ == "__main__":
    main()
