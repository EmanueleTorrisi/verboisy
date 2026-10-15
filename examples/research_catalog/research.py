# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Build a bounded, multi-source facility catalogue with inspectable record evidence.

The default validates and prints the task. --live explicitly starts browser/model
execution against caller-selected sources; no synthetic results are substituted.
"""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from verboisy import run
from verboisy.evidence.models import TaskSpec
from verboisy.research_contract import validate_research_contract
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError


def source_hosts(seeds: list[str]) -> list[str]:
    """Keep credentials out of the persisted task and make host scope explicit."""
    hosts = []
    for seed in seeds:
        parsed = urlsplit(seed)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("Seeds must be HTTP(S) URLs without credentials or fragments")
        hosts.append(parsed.hostname)
    return sorted(set(hosts))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="append", default=[])
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument("--target", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--request-units", type=int, default=300_000)
    parser.add_argument("--output", type=Path, default=Path("example-runs/research-catalog"))
    parser.add_argument("--live", action="store_true", help="Start real, potentially paid research")
    args = parser.parse_args()
    selected = json.loads(Path(__file__).with_name("sources.json").read_text(encoding="utf-8"))
    seeds = args.seed or selected["seed_urls"]
    extra_hosts = args.allow_host if args.seed else selected["allowed_hosts"] + args.allow_host
    try:
        if args.steps < 1 or args.request_units < 1:
            raise ValueError("Steps and request units must be positive")
        task = TaskSpec(
            seed_urls=seeds,
            allowed_hosts=sorted(set(source_hosts(seeds) + extra_hosts)),
            target_records=args.target,
            identity_fields=["/organization", "/facility_name"],
            max_pages=args.max_pages,
            max_depth=4,
            max_links_per_page=100,
        )
    except ValueError as error:
        parser.error(str(error))
    validate_research_contract(
        json.loads(Path(__file__).with_name("schema.json").read_text()), task
    )
    if not args.live:
        print(json.dumps(task.model_dump(mode="json"), indent=2))
        print("Contract preview only. --live starts browser and model requests.")
        return 0
    output = args.output.resolve()
    database = output / "research.db"
    if database.exists():
        parser.error(
            "Output already has a ledger; resume that run or choose a new output directory"
        )
    output.mkdir(parents=True, exist_ok=True)
    config = Settings(
        sqlite_db_path=str(database),
        model_request_budget=args.request_units,
        search_request_budget=0,
    )
    try:
        result = run(
            goal=(
                "Build a catalogue of publicly documented scientific research facilities from "
                "the declared sources and their permitted linked pages. One facility per row. "
                "Copy the owning organization and facility name exactly. Include type, country, "
                "city, homepage and services only when explicitly supported for that facility; "
                "otherwise use null. Do not infer location from a domain or merge distinct sites."
            ),
            schema=Path(__file__).with_name("schema.json"),
            task=task,
            config=config,
            max_steps=args.steps,
            export=[output / "facilities.json", output / "facilities.csv"],
            proof=True,
        )
    except VerboisyError as error:
        print(str(error))
        return 1
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "status": result.status,
                "accepted_rows": len(result.records),
                "stop_reason": result.stop_reason,
                "database": str(database),
                "manifest": str(result.manifest_path),
            },
            indent=2,
        )
    )
    return 0 if result.completed else 1 if result.status == "FAILED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
