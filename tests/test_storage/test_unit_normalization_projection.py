# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

import pytest
from verboisy.core.units import (
    CanonicalUnit,
    unit_normalization_event,
)
from verboisy.storage.research import (
    _apply_unit_normalizations,
    _replace_pointer_value,
)


@pytest.mark.parametrize(
    ("record", "pointer"),
    [
        # Invalid JSON pointer.
        (
            {"value": 1},
            "value",
        ),
        # Intermediate list requires numeric index.
        (
            {"items": [{"value": 1}]},
            "/items/not-an-index/value",
        ),
        # Intermediate list index out of range.
        (
            {"items": [{"value": 1}]},
            "/items/2/value",
        ),
        # Missing intermediate dictionary key.
        (
            {"item": {"value": 1}},
            "/missing/value",
        ),
        # Intermediate value is neither list nor dict.
        (
            {"item": 1},
            "/item/value",
        ),
        # Final list key is not numeric.
        (
            {"items": [1]},
            "/items/not-an-index",
        ),
        # Final list index is out of range.
        (
            {"items": [1]},
            "/items/2",
        ),
        # Missing final dictionary key.
        (
            {"item": {"value": 1}},
            "/item/missing",
        ),
        # Intermediate container is scalar.
        (
            {"company": "Acme"},
            "/company/name",
        ),
        # Final container is scalar.
        (
            {"item": 1},
            "/item/",
        ),
    ],
)
def test_replace_pointer_value_rejects_invalid_paths(
    record,
    pointer,
):
    assert (
        _replace_pointer_value(
            record,
            pointer,
            99,
        )
        is False
    )


def test_replace_pointer_value_updates_list_member():
    record = {
        "items": [
            {"value": 1},
            {"value": 2},
        ]
    }

    assert (
        _replace_pointer_value(
            record,
            "/items/1",
            99,
        )
        is True
    )

    assert record == {
        "items": [
            {"value": 1},
            99,
        ]
    }


def test_replace_pointer_value_updates_dict_member():
    record = {
        "item": {
            "value": 1,
        }
    }

    assert (
        _replace_pointer_value(
            record,
            "/item/value",
            99,
        )
        is True
    )

    assert record == {
        "item": {
            "value": 99,
        }
    }


def _normalization_payload(
    *,
    record_id="row-1",
    pointer="/population",
    original_value=2,
):
    payload = unit_normalization_event(
        record_id=record_id,
        pointer=pointer,
        original_value=original_value,
        unit=CanonicalUnit(
            dimension="count",
            base_unit="person",
            multiplier=1_000,
        ),
    )

    assert payload is not None
    return payload


def test_apply_unit_normalizations_skips_non_dict_payload():
    record = {"population": 2}

    _apply_unit_normalizations(
        "row-1",
        record,
        [
            {
                "payload": "invalid",
            }
        ],
        units={"/population": CanonicalUnit("count", "person", 1000)},
    )

    assert record == {
        "population": 2,
    }


def test_apply_unit_normalizations_skips_other_record():
    record = {"population": 2}

    payload = _normalization_payload(
        record_id="other-row",
    )

    _apply_unit_normalizations(
        "row-1",
        record,
        [{"payload": payload}],
        units={"/population": CanonicalUnit("count", "person", 1000)},
    )

    assert record == {
        "population": 2,
    }


def test_apply_unit_normalizations_skips_non_string_pointer():
    record = {"population": 2}

    payload = _normalization_payload()
    payload["pointer"] = 123

    _apply_unit_normalizations(
        "row-1",
        record,
        [{"payload": payload}],
        units={"/population": CanonicalUnit("count", "person", 1000)},
    )

    assert record == {
        "population": 2,
    }


def test_apply_unit_normalizations_skips_invalid_unit():
    record = {"population": 2}

    payload = _normalization_payload()
    payload["observed_unit"] = "invalid"

    _apply_unit_normalizations(
        "row-1",
        record,
        [{"payload": payload}],
        units={"/population": CanonicalUnit("count", "person", 1000)},
    )

    assert record == {
        "population": 2,
    }


def test_apply_unit_normalizations_skips_missing_pointer():
    record = {"population": 2}

    payload = _normalization_payload(
        pointer="/missing",
        original_value=2,
    )

    _apply_unit_normalizations(
        "row-1",
        record,
        [{"payload": payload}],
        units={"/population": CanonicalUnit("count", "person", 1000)},
    )

    assert record == {
        "population": 2,
    }


def test_apply_unit_normalizations_applies_valid_event():
    record = {
        "population": 2,
    }

    payload = _normalization_payload()

    _apply_unit_normalizations(
        "row-1",
        record,
        [{"payload": payload}],
        units={"/population": CanonicalUnit("count", "person", 1000)},
    )

    assert record == {
        "population": 2_000,
    }


@pytest.mark.parametrize("pointer", ["/missing", "population", "/population/value"])
def test_projection_ignores_units_without_a_value(pointer):
    record = {"population": 2}
    _apply_unit_normalizations(
        "row-1", record, [], units={pointer: CanonicalUnit("count", "person", 1000)}
    )
    assert record == {"population": 2}
