# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Versioned normalization binding and strict replay contracts."""

import pytest
from verboisy.core.units import (
    canonical_unit,
    normalized_unit_value_from_events,
    unit_normalization_event,
)


@pytest.mark.parametrize(
    ("candidate_key", "snapshot_id"),
    [(None, "s"), ("c", None), ("", "s"), ("c", "")],
)
def test_partial_binding_cannot_be_written(candidate_key, snapshot_id):
    with pytest.raises(ValueError, match="both candidate_key and snapshot_id"):
        unit_normalization_event(
            record_id="r",
            pointer="/value",
            original_value=2,
            unit=canonical_unit("thousands of persons"),
            candidate_key=candidate_key,
            snapshot_id=snapshot_id,
        )


@pytest.mark.parametrize(
    ("candidate_key", "snapshot_id"),
    [(None, None), ("c", None), ("wrong", "s"), ("c", "wrong"), ("c", "s")],
)
def test_bound_replay_requires_exact_context(candidate_key, snapshot_id):
    unit = canonical_unit("thousands of persons")
    event = unit_normalization_event(
        record_id="r",
        pointer="/value",
        original_value=2,
        unit=unit,
        candidate_key="c",
        snapshot_id="s",
    )
    expected = 2000 if (candidate_key, snapshot_id) == ("c", "s") else None
    assert (
        normalized_unit_value_from_events(
            [{"payload": event}],
            record_id="r",
            pointer="/value",
            original_value=2,
            unit=unit,
            candidate_key=candidate_key,
            snapshot_id=snapshot_id,
        )
        == expected
    )


@pytest.mark.parametrize("field", ["candidate_key", "snapshot_id"])
def test_legacy_envelope_cannot_carry_an_unchecked_binding(field):
    unit = canonical_unit("thousands of persons")
    event = unit_normalization_event(record_id="r", pointer="/value", original_value=2, unit=unit)
    event[field] = "unchecked"
    assert (
        normalized_unit_value_from_events(
            [{"payload": event}],
            record_id="r",
            pointer="/value",
            original_value=2,
            unit=unit,
        )
        is None
    )
