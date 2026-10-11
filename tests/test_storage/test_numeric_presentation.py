# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Numeric exports require bound units and preserve raw evidence across resumes."""

import copy
import json

import pytest
from verboisy.api import arun
from verboisy.core.units import canonical_unit, unit_normalization_event
from verboisy.evidence.models import ProjectionPlan, TaskSpec
from verboisy.extractor.ingestion import row_evidence
from verboisy.presentation import (
    PresentationPreferences,
    numeric_display_unit,
    present_number,
    present_rows,
)
from verboisy.product import transform_rows
from verboisy.storage.dataset import export_dataset
from verboisy.storage.numeric_presentation import output_numeric_units
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings

from tests.test_storage.test_dataset_assets import capture
from tests.test_storage.test_unit_replay_integrity import SCHEMA, accept_observation, ledger


@pytest.mark.parametrize(
    "value,label,options,expected",
    [
        (100, "lb", {}, 45.359237),
        ("100", "lb", {}, "45.359237"),
        (1000, "GRAM.", {}, 1),
        (0, "gram", {}, 0),
        (-100, "lb", {}, -45.359237),
        (1, "kilometres", {"length_unit": "ft"}, 3280.839895),
        (1, "kg", {"mass_unit": "lb"}, 2.204623),
        (1, "kg", {}, 1),
        (1, "kg", {"mass_unit": "source"}, 1),
        (None, "kg", {}, None),
        (True, "kg", {}, True),
        ([], "kg", {}, []),
        (1, "persons", {}, 1),
        (1, "kg dry weight", {}, 1),
        ("bad", "kg", {"mass_unit": "lb"}, "bad"),
        (float("inf"), "kg", {"mass_unit": "lb"}, float("inf")),
        (10**201, "kg", {"mass_unit": "lb"}, 10**201),
        ("-0.00000001", "g", {}, "0"),
    ],
)
def test_numeric_arithmetic(value, label, options, expected):
    assert present_number(value, label, PresentationPreferences(**options)) == expected


@pytest.mark.parametrize(
    "label,options,expected",
    [
        ("lb", {}, "kg"),
        ("meter", {}, "m"),
        ("unknown", {}, None),
        ("kg", {"mass_unit": "source"}, None),
        ("ft", {"length_unit": "source"}, None),
    ],
)
def test_target_unit_is_explicit(label, options, expected):
    assert numeric_display_unit(label, PresentationPreferences(**options)) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("normalized", [False, True])
@pytest.mark.parametrize("strings", [False, True])
@pytest.mark.parametrize("amount", [0, 2])
async def test_resume_normalized_mass_once_with_portable_chain(
    tmp_path, normalized, strings, amount
):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "kg", population=amount)
        if normalized:
            store.event(
                rid,
                "unit_normalization",
                unit_normalization_event(
                    record_id=record_id,
                    pointer="/population",
                    original_value=amount,
                    unit=canonical_unit("kg"),
                ),
            )
        store.event(rid, "product_options", {"strings": strings})
        store.finish(rid, "COMPLETED", "target_met", 17, 796)
        raw = store.evidence(rid)
    output = tmp_path / "rows.json"
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "replay.db"), search_provider="disabled"
    )
    result = await arun(resume=rid, export=output, mass_unit="lb", config=config)
    expected = 0 if amount == 0 else 4.409245
    assert result.records[0]["population"] == (str(expected) if strings else expected)
    manifest = json.loads(output.with_suffix(".json.manifest.json").read_text())
    cell = next(c for c in manifest["cell_lineage"] if c["pointer"] == "/population")
    assert cell["status"] == "resolved"
    step = cell["steps"][-1]
    assert step["target_unit"] == "lb"
    assert step["source_unit"] == ("gram" if normalized else "kg")
    assert step["unit_evidence"][0]["source"]["label"] == "kg"
    assert step["output"] == cell["output_value"]
    again = await arun(resume=rid, export=output, config=config)
    assert again.records == result.records
    reopened = ResearchStore(str(tmp_path / "replay.db"), read_only=True)
    assert reopened.evidence(rid) == raw
    assert (reopened.load(rid)["tokens"], reopened.load(rid)["reserved"]) == (17, 796)
    reopened.close()


@pytest.mark.parametrize(
    "case", ["missing", "stale", "forged", "protected", "empty", "unknown_record", "source"]
)
def test_missing_or_invalid_context_cannot_authorize_conversion(tmp_path, case):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "kg")
        event = copy.deepcopy(store.events(rid, "source_fitness")[0]["payload"])
        if case == "missing":
            event["claims"]["/population"]["comparability"].pop("unit")
            store.event(rid, "source_fitness", event)
        elif case == "stale":
            store.db.execute("DELETE FROM events WHERE run_id=? AND kind='source_fitness'", (rid,))
            event["snapshot_id"] = "stale"
            store.event(rid, "source_fitness", event)
        elif case == "forged":
            event["claims"]["/population"]["comparability"]["unit"]["label"] = "lb"
            store.event(rid, "source_fitness", event)
        mappings = [{"output_id": record_id, "record_id": record_id}]
        if case == "empty":
            mappings = [{"output_id": record_id, "record_ids": []}]
        elif case == "unknown_record":
            mappings = [{"output_id": record_id, "record_id": "missing"}]
        prefs = PresentationPreferences(mass_unit="source" if case == "source" else "lb")
        rows = present_rows(
            store.records(rid),
            SCHEMA,
            prefs,
            protected=["/population"] if case == "protected" else [],
            numeric_units=output_numeric_units(store, rid, mappings),
        )
        assert rows[0]["population"] == 2


@pytest.mark.parametrize("mixed", [False, True])
def test_grouped_conversion_requires_matching_effective_units(tmp_path, mixed):
    with ledger(tmp_path) as (store, rid, _):
        task = TaskSpec()
        # This test admits distinct whole-record identities; persist that policy
        # rather than retaining the fixture's name-only identity declaration.
        store.update_task(rid, task)
        accept_observation(store, rid, task, "kg", population=2)
        accept_observation(
            store, rid, task, "lb" if mixed else "kg", revision="second", population=4
        )
        shaped = transform_rows(
            store.records(rid), schema_fields=["name", "population", "revision"], groupby="name"
        )
        mapping = [
            {"output_id": r["id"], "record_ids": shaped.contributors[r["id"]]} for r in shaped.rows
        ]
        binding = output_numeric_units(store, rid, mapping)
        assert ((shaped.rows[0]["id"], "/population") in binding) is (not mixed)
        prefs = PresentationPreferences(mass_unit="lb")
        rows = present_rows(shaped.rows, SCHEMA, prefs, protected=[], numeric_units=binding)
        assert rows[0]["population"] == (3 if mixed else 6.613868)
        manifest = export_dataset(
            store,
            rid,
            tmp_path / "group.json",
            SCHEMA,
            task,
            rows=rows,
            metadata={"grouping": {"field": "name"}},
            output_lineage=mapping,
            presentation=prefs,
        )
        cell = next(
            c
            for c in json.loads(manifest.read_text())["cell_lineage"]
            if c["pointer"] == "/population"
        )
        assert cell["status"] == "resolved"
        assert cell["steps"][0]["operation"] == "average"
        if not mixed:
            assert cell["steps"][-1]["target_unit"] == "lb"
            assert len(cell["steps"][-1]["unit_evidence"]) == 2


def test_dataset_projection_uses_base_unit_and_retains_raw_asset(tmp_path):
    store = ResearchStore(str(tmp_path / "assets.db"))
    rid = store.create("Mass", SCHEMA, TaskSpec(), None)
    asset_id = store.save_dataset_asset(rid, capture(b'[{"amount":2,"unit":"kg"}]', "json"))
    asset = store.load_dataset_asset(rid, asset_id)
    plan = ProjectionPlan.model_validate(
        {
            "fields": [
                {
                    "source": "/amount",
                    "target": "/population",
                    "conversion": "unit_base",
                    "unit_source": "/unit",
                }
            ]
        }
    )
    snapshot, candidate = row_evidence(asset, asset.download.dataset.rows[0], plan)
    store.queue(rid, snapshot.url, 0, None)
    work = store.next_page(rid)
    store.snapshot(rid, work["id"], snapshot, "fixture")
    store.accept(rid, snapshot, candidate, [], TaskSpec())
    rows = store.records(rid)
    assert rows[0]["population"] == 2000
    mappings = [{"output_id": rows[0]["id"], "record_id": str(rows[0]["id"])}]
    prefs = PresentationPreferences()
    rows = present_rows(
        rows, SCHEMA, prefs, protected=[], numeric_units=output_numeric_units(store, rid, mappings)
    )
    assert rows[0]["population"] == 2
    manifest = export_dataset(
        store,
        rid,
        tmp_path / "rows.json",
        SCHEMA,
        TaskSpec(),
        rows=rows,
        output_lineage=mappings,
        presentation=prefs,
    )
    cell = json.loads(manifest.read_text())["cell_lineage"][0]
    assert cell["status"] == "resolved"
    assert cell["steps"][-1]["unit_evidence"][0]["basis"] == "dataset_unit_projection"
    assert (
        store.load_dataset_asset(rid, asset_id).download.dataset.original_bytes
        == b'[{"amount":2,"unit":"kg"}]'
    )
    store.close()


@pytest.mark.parametrize(
    "text", ["thousand lb", "million pounds", "kg per person", "kg/person", "meter²"]
)
def test_short_unit_binding_cannot_hide_scale_or_rate(tmp_path, text):
    with ledger(tmp_path) as (store, rid, task):
        label = (
            text.split()[1]
            if text.startswith(("thousand", "million"))
            else text.split("/")[0].split()[0].rstrip("²")
        )
        record_id = accept_observation(store, rid, task, label)
        evidence = store.evidence(rid)[0]
        evidence["snapshot"]["sources"][-1]["text"] = "Population unit: " + text + "."
        event = store.events(rid, "source_fitness")[0]["payload"]
        event["claims"]["/population"]["comparability"]["unit"]["quote"] = label
        store.db.execute(
            "UPDATE snapshots SET payload=? WHERE run_id=? AND id=?",
            (json.dumps(evidence["snapshot"]), rid, evidence["snapshot"]["id"]),
        )
        store.event(rid, "source_fitness", event)
        bindings = output_numeric_units(store, rid, [{"output_id": 1, "record_id": record_id}])
        assert (1, "/population") not in bindings


def test_nonfinite_or_unrepresentable_conversion_has_no_target_unit():
    from verboisy.presentation import number_conversion

    prefs = PresentationPreferences(mass_unit="lb")
    for value in [float("nan"), float("inf"), "1e999", 10**201, "bad"]:
        assert number_conversion(value, "kg", prefs) is None


def test_failed_conversion_does_not_label_raw_number_with_new_unit(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "kg", population=10**201)
        rows = store.records(rid)
        mapping = [{"output_id": record_id, "record_id": record_id}]
        prefs = PresentationPreferences(mass_unit="lb")
        rows = present_rows(
            rows,
            SCHEMA,
            prefs,
            protected=[],
            numeric_units=output_numeric_units(store, rid, mapping),
        )
        path = export_dataset(
            store,
            rid,
            tmp_path / "large.json",
            SCHEMA,
            task,
            rows=rows,
            output_lineage=mapping,
            presentation=prefs,
        )
        cell = next(
            c for c in json.loads(path.read_text())["cell_lineage"] if c["pointer"] == "/population"
        )
        assert cell["status"] == "resolved"
        assert [s["operation"] for s in cell["steps"]] == ["literal_evidence"]
        assert cell["output_value"] == 10**201


def test_definition_metadata_does_not_establish_numeric_unit(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "kg")
        event = store.events(rid, "source_fitness")[0]["payload"]
        comparability = event["claims"]["/population"]["comparability"]
        comparability["definition"] = comparability.pop("unit")
        store.event(rid, "source_fitness", event)
        assert output_numeric_units(store, rid, [{"output_id": 1, "record_id": record_id}]) == {}


def test_large_fractional_conversion_does_not_lose_decimal_digits():
    from verboisy.presentation import number_conversion

    assert number_conversion(10**100, "kg", PresentationPreferences(mass_unit="lb")) is None
    assert present_number(10**100, "kg", PresentationPreferences(mass_unit="lb")) == 10**100
