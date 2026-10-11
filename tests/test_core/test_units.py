# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

import pytest
from verboisy.core.units import (
    CanonicalUnit,
    canonical_unit,
)


def test_person_unit_aliases_share_identity():
    expected = CanonicalUnit(
        dimension="count",
        base_unit="person",
        multiplier=1,
    )

    assert canonical_unit("person") == expected
    assert canonical_unit("persons") == expected
    assert canonical_unit("People") == expected
    assert canonical_unit(" individuals. ") == expected


def test_scaled_person_units_preserve_multiplier():
    assert canonical_unit("thousands of persons") == CanonicalUnit(
        dimension="count",
        base_unit="person",
        multiplier=1_000,
    )

    assert canonical_unit("million people") == CanonicalUnit(
        dimension="count",
        base_unit="person",
        multiplier=1_000_000,
    )


def test_unknown_unit_is_not_inferred():
    assert canonical_unit("population units") is None


def test_canonical_unit_event_is_serializable():
    unit = CanonicalUnit(
        dimension="count",
        base_unit="person",
        multiplier=1_000,
    )

    assert unit.as_event() == {
        "dimension": "count",
        "base_unit": "person",
        "multiplier": 1_000,
    }


def test_mass_units_are_canonicalized():
    assert canonical_unit("grams") == CanonicalUnit(
        dimension="mass",
        base_unit="gram",
        multiplier=1,
    )

    assert canonical_unit("KG") == CanonicalUnit(
        dimension="mass",
        base_unit="gram",
        multiplier=1_000,
    )


def test_length_units_are_canonicalized():
    assert canonical_unit("metres") == CanonicalUnit(
        dimension="length",
        base_unit="meter",
        multiplier=1,
    )

    assert canonical_unit("kilometers") == CanonicalUnit(
        dimension="length",
        base_unit="meter",
        multiplier=1_000,
    )


def test_unit_value_normalizes_integer_scale():
    from verboisy.core.units import (
        normalize_unit_value,
    )

    unit = CanonicalUnit(
        dimension="count",
        base_unit="person",
        multiplier=1_000,
    )

    assert (
        normalize_unit_value(
            750,
            unit,
        )
        == 750_000
    )


def test_unit_value_normalizes_decimal_scale():
    from verboisy.core.units import (
        normalize_unit_value,
    )

    unit = CanonicalUnit(
        dimension="count",
        base_unit="person",
        multiplier=1_000_000,
    )

    assert (
        normalize_unit_value(
            1.5,
            unit,
        )
        == 1_500_000
    )


def test_unit_value_preserves_fraction_when_needed():
    from verboisy.core.units import (
        normalize_unit_value,
    )

    unit = CanonicalUnit(
        dimension="mass",
        base_unit="gram",
        multiplier=1_000,
    )

    assert (
        normalize_unit_value(
            1.2345,
            unit,
        )
        == 1234.5
    )


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        None,
        "12",
        [],
        {},
    ],
)
def test_unit_value_refuses_non_numeric_values(
    value,
):
    from verboisy.core.units import (
        normalize_unit_value,
    )

    unit = CanonicalUnit(
        dimension="mass",
        base_unit="gram",
        multiplier=1_000,
    )

    assert (
        normalize_unit_value(
            value,
            unit,
        )
        is None
    )


def test_unit_value_multiplier_one_is_stable():
    from verboisy.core.units import (
        normalize_unit_value,
    )

    unit = CanonicalUnit(
        dimension="count",
        base_unit="person",
        multiplier=1,
    )

    assert (
        normalize_unit_value(
            123,
            unit,
        )
        == 123
    )


def test_canonical_unit_decodes_event():
    from verboisy.core.units import (
        canonical_unit_from_event,
    )

    assert canonical_unit_from_event(
        {
            "dimension": "count",
            "base_unit": "person",
            "multiplier": 1_000,
        }
    ) == CanonicalUnit(
        dimension="count",
        base_unit="person",
        multiplier=1_000,
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "invalid",
        {
            "dimension": 1,
            "base_unit": "person",
            "multiplier": 1,
        },
        {
            "dimension": "count",
            "base_unit": 1,
            "multiplier": 1,
        },
        {
            "dimension": "count",
            "base_unit": "person",
            "multiplier": 0,
        },
        {
            "dimension": "count",
            "base_unit": "person",
            "multiplier": True,
        },
    ],
)
def test_canonical_unit_rejects_invalid_event(
    value,
):
    from verboisy.core.units import (
        canonical_unit_from_event,
    )

    assert canonical_unit_from_event(value) is None


def test_unit_normalization_event_preserves_provenance():
    from verboisy.core.units import (
        unit_normalization_event,
    )

    event = unit_normalization_event(
        record_id="row-1",
        pointer="/population",
        original_value=1.5,
        unit=CanonicalUnit(
            dimension="count",
            base_unit="person",
            multiplier=1_000_000,
        ),
        source_unit={
            "label": "million persons",
            "source": "metadata",
            "quote": "Population in million persons",
        },
    )

    assert event == {
        "version": 1,
        "record_id": "row-1",
        "pointer": "/population",
        "original_value": 1.5,
        "normalized_value": 1_500_000,
        "observed_unit": {
            "dimension": "count",
            "base_unit": "person",
            "multiplier": 1_000_000,
        },
        "canonical_unit": {
            "dimension": "count",
            "base_unit": "person",
            "multiplier": 1,
        },
        "multiplier": 1_000_000,
        "source_unit": {
            "label": "million persons",
            "source": "metadata",
            "quote": "Population in million persons",
        },
    }


def test_unit_normalization_event_rejects_non_numeric():
    from verboisy.core.units import (
        unit_normalization_event,
    )

    assert (
        unit_normalization_event(
            record_id="row-1",
            pointer="/population",
            original_value="1.5",
            unit=CanonicalUnit(
                dimension="count",
                base_unit="person",
                multiplier=1_000_000,
            ),
        )
        is None
    )


def test_unit_normalization_event_omits_missing_source_metadata():
    from verboisy.core.units import (
        unit_normalization_event,
    )

    event = unit_normalization_event(
        record_id="row-1",
        pointer="/population",
        original_value=2,
        unit=CanonicalUnit(
            dimension="count",
            base_unit="person",
            multiplier=1_000,
        ),
    )

    assert event is not None
    assert "source_unit" not in event


def test_unit_normalization_replays_valid_event():
    from verboisy.core.units import (
        normalized_unit_value_from_events,
        unit_normalization_event,
    )

    unit = CanonicalUnit(
        dimension="count",
        base_unit="person",
        multiplier=1_000,
    )

    payload = unit_normalization_event(
        record_id="row-1",
        pointer="/population",
        original_value=750,
        unit=unit,
    )

    assert payload is not None

    assert (
        normalized_unit_value_from_events(
            [{"payload": payload}],
            record_id="row-1",
            pointer="/population",
            original_value=750,
            unit=unit,
        )
        == 750_000
    )


def test_unit_normalization_skips_malformed_event_before_valid_one():
    from verboisy.core.units import (
        normalized_unit_value_from_events,
        unit_normalization_event,
    )

    unit = CanonicalUnit(
        dimension="count",
        base_unit="person",
        multiplier=1_000,
    )

    payload = unit_normalization_event(
        record_id="row-1",
        pointer="/population",
        original_value=2,
        unit=unit,
    )

    assert payload is not None

    assert (
        normalized_unit_value_from_events(
            [
                {"payload": payload},
                {"payload": "invalid"},
            ],
            record_id="row-1",
            pointer="/population",
            original_value=2,
            unit=unit,
        )
        == 2_000
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("version", 999),
        ("record_id", "other"),
        ("pointer", "/other"),
        ("original_value", 99),
        (
            "observed_unit",
            {
                "dimension": "mass",
                "base_unit": "gram",
                "multiplier": 1_000,
            },
        ),
        (
            "canonical_unit",
            {
                "dimension": "mass",
                "base_unit": "gram",
                "multiplier": 1,
            },
        ),
        ("multiplier", 999),
        ("normalized_value", 999),
    ],
)
def test_unit_normalization_rejects_tampered_event(
    key,
    value,
):
    from copy import deepcopy

    from verboisy.core.units import (
        normalized_unit_value_from_events,
        unit_normalization_event,
    )

    unit = CanonicalUnit(
        dimension="count",
        base_unit="person",
        multiplier=1_000,
    )

    payload = unit_normalization_event(
        record_id="row-1",
        pointer="/population",
        original_value=2,
        unit=unit,
    )

    assert payload is not None

    payload = deepcopy(payload)
    payload[key] = value

    assert (
        normalized_unit_value_from_events(
            [{"payload": payload}],
            record_id="row-1",
            pointer="/population",
            original_value=2,
            unit=unit,
        )
        is None
    )


def test_unit_normalization_replay_rejects_non_numeric_original():
    from verboisy.core.units import (
        normalized_unit_value_from_events,
    )

    assert (
        normalized_unit_value_from_events(
            [],
            record_id="row-1",
            pointer="/population",
            original_value="2",
            unit=CanonicalUnit(
                dimension="count",
                base_unit="person",
                multiplier=1_000,
            ),
        )
        is None
    )
