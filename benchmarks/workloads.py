# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Deterministic, synthetic workloads using the production implementations."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verboisy.evidence.models import Candidate, Proof, Snapshot, Source, TaskSpec
from verboisy.evidence.quote_batch import quotes_observed
from verboisy.evidence.quote_match import quote_observed
from verboisy.evidence.verify import leaves, verify
from verboisy.extractor.dataset import parse_dataset
from verboisy.product import SortKey, transform_rows
from verboisy.storage.lineage import build_cell_lineage
from verboisy.storage.research import ResearchStore

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "amount": {"type": "integer"},
        "group": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["name", "amount", "group", "note"],
    "additionalProperties": False,
}
FIELDS = list(SCHEMA["properties"])
CASE_NAMES = (
    "parse_csv",
    "parse_json",
    "parse_jsonl",
    "verify",
    "group",
    "sort",
    "lineage_scalar",
    "lineage_grouped",
)

OPTIONAL_CASE_NAMES = (
    "quote_regex",
    "quote_python",
    "quote_native",
    "quote_batch_python",
    "quote_batch_native",
)


class BenchmarkError(RuntimeError):
    """A workload output violated its independently checked fixture contract."""


def require(condition: bool, message: str) -> None:
    # Do not use assert: python -O must not disable benchmark correctness checks.
    if not condition:
        raise BenchmarkError(message)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class Workload:
    name: str
    rows: int
    domain: str
    operation: Callable[[], Any]
    validate: Callable[[Any], Any]


def records(count: int) -> list[dict[str, Any]]:
    return [
        {
            "name": f"Entity {i:06} Anaïs",
            "amount": i % 97,
            "group": f"group-{i % 8}",
            "note": 'Unicode 李雷\nquoted "text"; literal =1+1',
        }
        for i in range(count)
    ]


def evidence(row: dict[str, Any], index: int) -> tuple[Snapshot, Candidate]:
    scope = f"entity-{index}"
    page = Snapshot(
        id=f"fixture-{index}",
        url="https://benchmark.invalid/data",
        fetched_at="2026-10-08T00:00:00Z",
        content_hash=digest(row),
        truncated=False,
        sources=[
            Source(id=key, kind="text", text=str(value), scope=scope) for key, value in row.items()
        ],
    )
    candidate = Candidate(
        scope=scope,
        record=row,
        evidence={
            "/" + key: Proof(
                source=key, quote=str(value), transform="integer" if key == "amount" else "text"
            )
            for key, value in row.items()
        },
    )
    return page, candidate


def quote_cases(count: int) -> list[tuple[str, str, bool, bool]]:
    """Unique literals expose compilation cost; negative cases check boundaries."""
    result = []
    for index in range(count):
        name, number = f"Entity {index:06} Anaïs", str(index)
        result.extend(
            [
                (f"prefix {name}; suffix", name, False, True),
                (f"X{name}Y", name, False, False),
                (f"X{name}Y; {name}", name, False, True),
                (f"total {number} persons", number, True, True),
                ("-" + number, number, True, False),
                (number + ".\u0665", number, True, False),
                (number + ", people", number, True, True),
                (f"literal [breed-{index}]+(x).", f"[breed-{index}]+(x)", False, True),
            ]
        )
    return result


def make_workloads(
    count: int,
    lineage_count: int,
    directory: Path,
    selected: list[str],
    *,
    batch_quotes: bool = True,
) -> tuple[list[Workload], ResearchStore | None]:
    """Prepare all inputs outside measurement; callers own the temporary ledger."""
    rows = records(count)
    task = TaskSpec(identity_fields=["/name"])
    cases = []
    for fmt in ("csv", "json", "jsonl"):
        name = "parse_" + fmt
        if name not in selected:
            continue
        if fmt == "csv":
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            body = buffer.getvalue().encode()
            expected = [{k: str(v) for k, v in row.items()} for row in rows]
        else:
            body = (
                json.dumps(rows, ensure_ascii=False)
                if fmt == "json"
                else "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
            ).encode()
            expected = rows

        def validate_parsed(parsed, body=body, expected=expected):
            require(parsed.original_bytes == body, "Parser changed captured bytes")
            require(parsed.sha256 == hashlib.sha256(body).hexdigest(), "Parser hash differs")
            values = [row.values for row in parsed.rows]
            require(values == expected, "Parser values, types or order differ")
            return values

        cases.append(
            Workload(
                name,
                count,
                "in_memory",
                lambda body=body, fmt=fmt: parse_dataset(body, fmt),
                validate_parsed,
            )
        )
    if "verify" in selected:
        observations = [evidence(row, i) for i, row in enumerate(rows)]

        def validate_verified(errors):
            require(errors == [[] for _ in rows], "Verified fixture was rejected")
            return errors

        cases.append(
            Workload(
                "verify",
                count,
                "in_memory",
                lambda: [
                    verify(candidate, page, SCHEMA, task, batch_quotes=batch_quotes)
                    for page, candidate in observations
                ],
                validate_verified,
            )
        )
    source = [{"id": str(i), **row} for i, row in enumerate(rows)]
    for name in ("group", "sort"):
        if name not in selected:
            continue

        def validate_shaped(result, name=name):
            if name == "sort":
                expected = sorted(source, key=lambda row: row["amount"], reverse=True)
                require(result.rows == expected, "Sort changed values or stable tie order")
            else:
                members = {
                    group: [row for row in source if row["group"] == group]
                    for group in dict.fromkeys(row["group"] for row in source)
                }
                require(len(result.rows) == len(members), "Group count differs")
                for row in result.rows:
                    inputs = members[row["group"]]
                    require(
                        row["amount"] == sum(r["amount"] for r in inputs) / len(inputs),
                        "Grouped average differs",
                    )
                    require(
                        result.contributors[row["id"]] == [r["id"] for r in inputs],
                        "Group contributor order differs",
                    )
                    require(set(row) == {"id", "group", "amount"}, "Unexpected aggregate columns")
            return result.rows

        cases.append(
            Workload(
                name,
                count,
                "in_memory",
                lambda name=name: transform_rows(
                    source,
                    schema_fields=FIELDS,
                    groupby="group" if name == "group" else None,
                    sort_keys=[SortKey("amount", "desc")] if name == "sort" else None,
                ),
                validate_shaped,
            )
        )
    store = None
    if any(name.startswith("lineage_") for name in selected):
        store = ResearchStore(str(directory / "benchmark.db"))
        try:
            rid = store.create("Synthetic benchmark", SCHEMA, task, None)
            for i, row in enumerate(records(lineage_count)):
                page, candidate = evidence(row, i)
                require(verify(candidate, page, SCHEMA, task) == [], "Ledger fixture is ungrounded")
                store.queue(rid, page.url, 0, None)
                # All snapshots share one synthetic URL; snapshot persistence only
                # needs an existing page ID and does not trigger any navigation.
                page_id = store.db.execute(
                    "SELECT id FROM pages WHERE run_id=?", (rid,)
                ).fetchone()[0]
                store.snapshot(rid, page_id, page, "benchmark")
                require(
                    store.accept(rid, page, candidate, [], task) == "accepted", "Acceptance failed"
                )
            effective = store.records(rid)
            for name in ("lineage_scalar", "lineage_grouped"):
                if name not in selected:
                    continue
                grouped = name == "lineage_grouped"
                shaped = transform_rows(
                    effective, schema_fields=FIELDS, groupby="group" if grouped else None
                )
                mappings = [
                    {
                        "output_id": i + 1,
                        **(
                            {"record_ids": shaped.contributors[row["id"]]}
                            if grouped
                            else {"record_id": row["id"]}
                        ),
                    }
                    for i, row in enumerate(shaped.rows)
                ]
                output = [{**row, "id": i + 1} for i, row in enumerate(shaped.rows)]

                def validate_cells(cells, output=output, mappings=mappings):
                    require(cells is not None, "Lineage mapping was omitted")
                    expected = {
                        (row["id"], p): v
                        for row in output
                        for p, v in leaves(row).items()
                        if p != "/id"
                    }
                    require(len(cells) == len(expected), "Lineage cell count differs")
                    seen = set()
                    stable = []
                    for cell in cells:
                        key = (cell["output_id"], cell["pointer"])
                        require(key not in seen and key in expected, "Duplicate or unexpected cell")
                        seen.add(key)
                        require(
                            cell["status"] == "resolved" and cell["output_value"] == expected[key],
                            "Cell derivation does not match output",
                        )
                        mapping = mappings[cell["output_id"] - 1]
                        identity = "record_ids" if "record_ids" in mapping else "record_id"
                        require(
                            cell[identity] == mapping[identity], "Cell evidence mapping differs"
                        )
                        stable.append(
                            {
                                k: cell[k]
                                for k in ("output_id", "pointer", "output_value", "status", "steps")
                            }
                        )
                    return stable

                cases.append(
                    Workload(
                        name,
                        lineage_count,
                        "local_sqlite",
                        lambda output=output,
                        mappings=mappings,
                        grouped=grouped: build_cell_lineage(
                            store,
                            rid,
                            output,
                            mappings,
                            strings=False,
                            groupby="group" if grouped else None,
                        ),
                        validate_cells,
                    )
                )
        except BaseException:
            store.close()
            raise
    if any(name in selected for name in OPTIONAL_CASE_NAMES):
        quotes = quote_cases(count)
        expected_quotes = [expected for _, _, _, expected in quotes]

        def validate_quotes(output):
            require(output == expected_quotes, "Quote boundary decisions differ")
            return output

        batches = [
            [(text, quote, numeric) for text, quote, numeric, _ in quotes[start : start + 1024]]
            for start in range(0, len(quotes), 1024)
        ]
        for name in OPTIONAL_CASE_NAMES:
            if name in selected:
                batch = name.startswith("quote_batch_")
                backend = name.removeprefix("quote_batch_" if batch else "quote_")
                cases.append(
                    Workload(
                        name,
                        count,
                        "in_memory",
                        (
                            lambda backend=backend: [
                                result
                                for batch in batches
                                for result in quotes_observed(batch, backend=backend)
                            ]
                        )
                        if batch
                        else (
                            lambda backend=backend: [
                                quote_observed(text, quote, numeric, backend=backend)
                                for text, quote, numeric, _ in quotes
                            ]
                        ),
                        validate_quotes,
                    )
                )
    return cases, store
