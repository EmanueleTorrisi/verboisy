# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Validate durable discovery acquisitions before they can publish frontier work."""

from collections.abc import Callable
from typing import Any

from verboisy.core.search import SearchObservation
from verboisy.product import SourcePolicy
from verboisy.utils.exceptions import VerboisyError

Canonicalize = Callable[[str], str | None]


def _permitted_url(value: Any, policy: SourcePolicy, canonicalize: Canonicalize) -> str:
    if not isinstance(value, str):
        raise VerboisyError("Saved discovery result failed integrity verification")
    url = canonicalize(value)
    if url is None or not policy.permits(url):
        raise VerboisyError("Saved discovery result failed integrity verification")
    return url


def validated_observation(
    value: Any, policy: SourcePolicy, *, canonicalize: Canonicalize
) -> dict[str, Any]:
    """Validate result structure and scope while retaining historical JSON fields."""
    if not isinstance(value, dict):
        raise VerboisyError("Saved discovery result failed integrity verification")
    try:
        observation = SearchObservation.model_validate(value)
    except ValueError as error:
        raise VerboisyError("Saved discovery result failed integrity verification") from error
    for result in observation.results:
        _permitted_url(result.url, policy, canonicalize)
    return value


def validated_discovery_result(
    value: Any, policy: SourcePolicy, *, canonicalize: Canonicalize
) -> tuple[list[str], list[dict[str, Any]]]:
    """Validate the acquisition before task updates or source publication begin."""
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("seeds"), list)
        or not value["seeds"]
        or not isinstance(value.get("observations"), list)
    ):
        raise VerboisyError("Saved discovery result failed integrity verification")
    seeds = [_permitted_url(seed, policy, canonicalize) for seed in value["seeds"]]
    observations = [
        validated_observation(observation, policy, canonicalize=canonicalize)
        for observation in value["observations"]
    ]
    # Retain first occurrence, matching fresh discovery's frontier ordering.
    return list(dict.fromkeys(seeds)), observations
