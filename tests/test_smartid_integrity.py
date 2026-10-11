# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""SmartID contradiction, identifier semantics, and output-integrity regressions."""

import copy

import pytest
from verboisy.product import apply_smart_ids
from verboisy.utils.exceptions import VerboisyError


@pytest.mark.parametrize(
    ("current", "previous"),
    [
        (
            {"website": "https://shop.test/", "sku": "B"},
            {"website": "https://shop.test/", "sku": "A"},
        ),
        (
            {"name": "Same", "city": "Rome", "sku": "B"},
            {"name": "Same", "city": "Rome", "sku": "A"},
        ),
        (
            {"canonical_url": "https://example.test/Item"},
            {"canonical_url": "https://example.test/item"},
        ),
        (
            {"canonical_url": "https://example.test/item/"},
            {"canonical_url": "https://example.test/item"},
        ),
        ({"sku": "Abc"}, {"sku": "abc"}),
        ({"sku": "123"}, {"sku": 123}),
        ({"sku": True}, {"sku": True}),
        ({"sku": {"key": "x"}}, {"sku": {"key": "x"}}),
        ({"sku": "  "}, {"sku": "  "}),
    ],
)
def test_contradiction_or_unsafe_identifier_never_links(current, previous):
    rows, decisions = apply_smart_ids(
        [{"id": 1, **current}], [{"id": 10, **previous}], "previous_id"
    )
    assert rows[0]["previous_id"] is None
    assert decisions[0]["outcome"] == "unresolved"


@pytest.mark.parametrize("value", ["SKU-A", 123, "https://example.test/Item"])
def test_exact_unique_identifier_still_links(value):
    rows, decisions = apply_smart_ids(
        [{"id": 1, "sku": value}], [{"id": 10, "sku": value}], "previous_id"
    )
    assert rows[0]["previous_id"] == 10
    assert decisions[0]["outcome"] == "exact"


def test_mixed_prior_ids_are_ambiguous_and_deterministic():
    previous = [{"id": 10, "sku": "A"}, {"id": "legacy-10", "sku": "A"}]
    first = apply_smart_ids([{"id": 1, "sku": "A"}], previous, "previous_id")
    second = apply_smart_ids([{"id": 1, "sku": "A"}], list(reversed(previous)), "previous_id")
    assert first == second
    rows, decisions = first
    assert rows[0]["previous_id"] is None
    assert decisions[0]["outcome"] == "ambiguous"
    assert decisions[0]["candidate_ids"] == [10, "legacy-10"]


@pytest.mark.parametrize("existing", [None, "original-value"])
def test_relation_field_collision_is_rejected_without_mutation(existing):
    rows = [{"id": 1, "sku": "A"}, {"id": 2, "previous_id": existing}]
    before = copy.deepcopy(rows)
    with pytest.raises(VerboisyError, match="relation field already exists"):
        apply_smart_ids(rows, [{"id": 10, "sku": "A"}], "previous_id")
    assert rows == before


def test_name_only_stays_unresolved():
    rows, decisions = apply_smart_ids(
        [{"id": 1, "name": "Same"}], [{"id": 10, "name": "Same"}], "previous_id"
    )
    assert rows[0]["previous_id"] is None
    assert decisions[0]["outcome"] == "unresolved"


@pytest.mark.parametrize("model,expected", [(None, None), (2025, 10)])
def test_name_context_fallback_handles_missing_and_numeric_models(model, expected):
    rows, _ = apply_smart_ids(
        [{"id": 1, "name": "Same", "model": model}],
        [{"id": 10, "name": "Same", "model": model}],
        "previous_id",
    )
    assert rows[0]["previous_id"] == expected
