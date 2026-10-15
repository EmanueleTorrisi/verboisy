# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Prepare, pause and resume local observations under a fixed streaming contract.

The result contains counts and a job ID. Cursor paging reads only a small committed
sample; it never turns the full dataset into a Python list.
"""

import argparse
import json
import sys
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from verboisy import StreamLedger, StreamLimits, stream_dataset
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--source", type=Path)
    selection.add_argument("--resume")
    parser.add_argument("--rows-per-invocation", type=int)
    parser.add_argument("--export", type=Path)
    args = parser.parse_args()
    result = None
    try:
        args.database.parent.mkdir(parents=True, exist_ok=True)
        if args.export is not None:
            args.export.parent.mkdir(parents=True, exist_ok=True)
        config = Settings()
        kwargs = {}
        if args.source is not None:
            source = args.source.resolve()
            # Demonstration grants are explicit and restricted to the chosen directory.
            config = config.model_copy(update={"dataset_local_roots": [str(source.parent)]})
            kwargs = {
                "source": source,
                "dataset_format": "jsonl",
                "schema": json.loads(
                    Path(__file__).with_name("schema.json").read_text(encoding="utf-8")
                ),
                "limits": StreamLimits(),
            }
        result = stream_dataset(
            database=args.database,
            resume=args.resume,
            config=config,
            rows_per_invocation=args.rows_per_invocation,
            export=args.export,
            **kwargs,
        )
        sample = []
        if result.source_sha256 is not None:
            with closing(StreamLedger(args.database, read_only=True)) as ledger:
                sample = ledger.page(result.job_id, after=0, limit=5)
    except KeyboardInterrupt:
        print("Preparation interrupted", file=sys.stderr)
        return 130
    except (VerboisyError, OSError, ValueError) as error:
        if result is not None:
            print(json.dumps({"result": asdict(result)}, indent=2))
        print(f"Preparation failed ({type(error).__name__})", file=sys.stderr)
        return 1
    print(json.dumps({"result": asdict(result), "first_committed_rows": sample}, indent=2))
    return (
        130
        if result.reason == "interrupted"
        else 0
        if result.status == "COMPLETED"
        else 2
        if result.status == "PAUSED"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
