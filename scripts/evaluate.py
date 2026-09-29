"""Paid, opt-in model evaluation on fixed cross-domain evidence; not a browser test."""

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

from verboisy.evidence.models import TaskSpec
from verboisy.evidence.snapshot import chunks, snapshot
from verboisy.extractor.evidenced import EvidenceExtractor
from verboisy.llm.client import LLMClient
from verboisy.utils.config import Settings


async def evaluate(args):
    cases = json.loads((Path(__file__).resolve().parents[1] / "evals/cases.json").read_text())
    selected = [c for c in cases if not args.case or c["id"] in args.case]
    if not selected:
        raise SystemExit("No matching cases")
    report = {
        "schema_version": 1,
        "model": args.model,
        "repetitions": args.repetitions,
        "results": [],
    }
    for repeat in range(args.repetitions):
        for case in selected:
            for mode in args.mode:
                config = Settings(
                    litellm_model=args.model, llm_retries=0, model_request_budget=150000
                )
                client = LLMClient(config=config)
                page = snapshot(case["html"], case["url"])
                start = time.monotonic()
                rows = []
                diagnostics = []
                error = None
                try:
                    if mode == "evidence":
                        engine = EvidenceExtractor(client, case["schema"], TaskSpec(), case["goal"])
                        for batch in chunks(page, config.max_dom_chars):
                            proposed = await engine.propose(page, batch)
                            detail = {
                                "sources": [s.model_dump() for s in batch],
                                "proposal": proposed.model_dump(),
                                "checks": [],
                            }
                            diagnostics.append(detail)
                            supplied = page.model_copy(update={"sources": batch})
                            for candidate in proposed.candidates:
                                errors = await engine.check(candidate, supplied)
                                detail["checks"].append(
                                    {
                                        "record": candidate.record,
                                        "errors": errors,
                                    }
                                )
                                if not errors and candidate.record not in rows:
                                    rows.append(candidate.record)
                    else:
                        result = await client.complete_json(
                            "Extract facts matching the goal and JSON Schema. "
                            'Return {"records":[...]}. '
                            "Use only provided page evidence; do not invent missing facts.",
                            json.dumps(
                                {
                                    "goal": case["goal"],
                                    "schema": case["schema"],
                                    "sources": [s.model_dump() for s in page.sources],
                                }
                            ),
                        )
                        rows = result.get("records", [])
                        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                            raise ValueError("Baseline must return a list of objects")
                except Exception as exc:
                    error = type(exc).__name__
                exact = error is None and sorted(
                    [json.dumps(r, sort_keys=True) for r in rows]
                ) == sorted([json.dumps(r, sort_keys=True) for r in case["expected"]])
                report["results"].append(
                    {
                        "case": case["id"],
                        "repeat": repeat,
                        "mode": mode,
                        "exact_match": exact,
                        "records": rows,
                        "diagnostics": diagnostics,
                        "expected": case["expected"],
                        "error": error,
                        "tokens": client.total_tokens,
                        "request_units": client.reserved_tokens,
                        "seconds": round(time.monotonic() - start, 3),
                        "snapshot_sha256": hashlib.sha256(case["html"].encode()).hexdigest(),
                    }
                )
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                print(case["id"], mode, "PASS" if exact else "FAIL", flush=True)
    raise SystemExit(
        0
        if all(
            r["exact_match"]
            for r in report["results"]
            if r["mode"] == ("evidence" if "evidence" in args.mode else "baseline")
        )
        else 1
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Permit paid model calls")
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument(
        "--mode", nargs="+", choices=["evidence", "baseline"], default=["evidence", "baseline"]
    )
    parser.add_argument("--case", action="append")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.live or not 1 <= args.repetitions <= 10:
        parser.error("--live is required; repetitions must be 1..10")
    asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
