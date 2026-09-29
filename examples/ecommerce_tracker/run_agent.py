"""Run this example with a user-owned task policy and real source goal."""

import argparse
from pathlib import Path

from verboisy import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--export", required=True)
    args = parser.parse_args()
    result = run(
        goal=args.goal,
        schema=Path(__file__).with_name("schema.json"),
        task=args.task,
        export=args.export,
    )
    print(result.status, result.stop_reason, result.manifest_path)
    raise SystemExit(0 if result.completed else 1 if result.status == "FAILED" else 2)
