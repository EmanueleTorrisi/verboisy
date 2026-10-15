# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Reuse ledger inputs within a generation, while keeping later exports fresh."""

from unittest.mock import Mock

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.product import transform_rows
from verboisy.storage.lineage import build_cell_lineage

from benchmarks.workloads import FIELDS, digest, evidence, make_workloads, records


@pytest.mark.parametrize(
    "case,expected",
    [
        ("lineage_scalar", "d3e3b935e8b29e097d92b6f44f8526f66883cc1c0775fdb63f011ac28eb99b70"),
        ("lineage_grouped", "0d0311d129c3132820ada1d8ad946e9776b5486becbfa48e6e14da003a376420"),
    ],
)
@pytest.mark.parametrize("normalized", [False, True])
def test_baseline_derivations_match_with_bounded_ledger_reads(tmp_path, case, expected, normalized):
    cases, store = make_workloads(16, 100, tmp_path, [case])
    try:
        if normalized:
            rid = store.db.execute("SELECT id FROM research_runs").fetchone()[0]
            store.event(rid, "unit_normalization", {})
        store.evidence = Mock(wraps=store.evidence)
        store.records = Mock(wraps=store.records)
        store.evidence_records = Mock(wraps=store.evidence_records)
        before = store.db.total_changes
        result = cases[0].operation()
        # Digests come from the independently retained R9i baseline, including
        # every derivation step. Checks do not discard unresolved differences.
        assert digest(cases[0].validate(result)) == expected
        assert store.evidence.call_count == 1
        assert store.evidence_records.call_count == 1
        store.records.assert_not_called()
        assert store.db.total_changes == before
    finally:
        store.close()


def grouped_cells(store, rid):
    shaped = transform_rows(store.records(rid), schema_fields=FIELDS, groupby="group")
    rows = [{**row, "id": index + 1} for index, row in enumerate(shaped.rows)]
    mappings = [
        {"output_id": index + 1, "record_ids": shaped.contributors[row["id"]]}
        for index, row in enumerate(shaped.rows)
    ]
    return build_cell_lineage(store, rid, rows, mappings, strings=False, groupby="group")


def test_later_export_reads_new_accepted_evidence(tmp_path):
    _, store = make_workloads(16, 8, tmp_path, ["lineage_grouped"])
    try:
        rid = store.db.execute("SELECT id FROM research_runs").fetchone()[0]
        first = grouped_cells(store, rid)
        original = digest(first)
        page, candidate = evidence(records(9)[-1], 8)
        page_id = store.db.execute("SELECT id FROM pages WHERE run_id=?", (rid,)).fetchone()[0]
        store.snapshot(rid, page_id, page, "benchmark")
        assert (
            store.accept(rid, page, candidate, [], TaskSpec(identity_fields=["/name"]))
            == "accepted"
        )
        second = grouped_cells(store, rid)
        assert digest(first) == original
        assert digest(second) != original
        cell = next(c for c in second if c["pointer"] == "/amount" and len(c["record_ids"]) == 2)
        assert cell["status"] == "resolved"
        assert cell["output_value"] == 4
        assert cell["steps"][0]["inputs"] == [0, 8]
    finally:
        store.close()


def test_absent_mapping_does_not_read_the_ledger():
    store = Mock()
    assert build_cell_lineage(store, "run", [], None, strings=False) is None
    assert store.mock_calls == []
