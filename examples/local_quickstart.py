# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Run the actual CLI on two synthetic local records without a model or browser."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "example-runs"
    output.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="local-", dir=output))
    records = [
        {"name": "Synthetic Research North", "country": "Italy"},
        {"name": "Synthetic Research South", "country": "France"},
    ]
    source = work / "institutions.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    schema = work / "schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {key: {"type": "string"} for key in ("name", "country")},
                    "required": ["name", "country"],
                },
            }
        ),
        encoding="utf-8",
    )
    destination = work / "institutions.json"
    environment = {
        **os.environ,
        "DATASET_LOCAL_ROOTS": json.dumps([str(work)]),
        "SQLITE_DB_PATH": str(work / "research.db"),
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "verboisy",
            "run",
            "--goal",
            "Prepare the two explicitly supplied synthetic institution records",
            "--schema",
            str(schema),
            "--maxrows",
            "2",
            "--dataset-file",
            f"jsonl={source}",
            "--export",
            str(destination),
        ],
        cwd=work,
        env=environment,
        check=True,
    )
    exported = json.loads(destination.read_text(encoding="utf-8"))
    actual = {(row["name"], row["country"]) for row in exported}
    expected = {(row["name"], row["country"]) for row in records}
    if len(exported) != 2 or actual != expected:
        raise SystemExit("Local quickstart output did not match its synthetic inputs")
    print(f"Verified two synthetic records. Output and evidence: {work}")


if __name__ == "__main__":
    main()
