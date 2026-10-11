# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Generate distinct synthetic station observations with bounded write memory.

Metadata padding controls record width for a scale workload. These observations
exercise storage and replay; they are not retrieved measurements or training data.
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--metadata-bytes", type=int, default=1024)
    args = parser.parse_args()
    if not 1 <= args.rows <= 10_000_000 or not 0 <= args.metadata_bytes <= 100_000:
        parser.error("Choose 1-10,000,000 rows and 0-100,000 metadata padding bytes")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    start = datetime(2026, 1, 1, tzinfo=UTC)
    # Exclusive creation prevents an example run from replacing an acquired dataset.
    with args.output.open("xb") as stream:
        padding = "x" * args.metadata_bytes
        for ordinal in range(args.rows):
            row = {
                "observation_id": ordinal,
                "station_id": f"station-{ordinal % 128:03d}",
                "observed_at": (start + timedelta(seconds=ordinal)).isoformat(),
                "power_kw": round(10 + (ordinal % 1000) / 10, 1),
                "unit": "kW",
                "quality": "synthetic",
                "metadata": {"stream": "generated-example", "padding": padding},
            }
            encoded = (json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8")
            stream.write(encoded)
            digest.update(encoded)
            size += len(encoded)
    print(
        json.dumps(
            {
                "source": str(args.output.resolve()),
                "rows": args.rows,
                "bytes": size,
                "sha256": digest.hexdigest(),
                "data_origin": "synthetic",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
