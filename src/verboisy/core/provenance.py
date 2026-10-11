# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Deterministic provenance identities for grounded source attribution."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from verboisy.evidence.models import Source
from verboisy.evidence.snapshot import whitespace

ProvenanceIdentityKind = Literal[
    "attribution_label",
    "attribution_host",
]


@dataclass(frozen=True)
class ProvenanceIdentity:
    """A grounded origin identity.

    Equality of keys means two observations refer to the same
    observed origin. Different keys do not, by themselves, prove
    independence.
    """

    kind: ProvenanceIdentityKind
    key: str
    label: str
    source_id: str
    quote: str
    host: str | None = None

    def as_event(self) -> dict[str, Any]:
        return asdict(self)


def canonical_provenance_label(
    value: str,
) -> str:
    """Normalize an observed attribution label without semantic guessing."""

    normalized = unicodedata.normalize(
        "NFKC",
        value,
    )

    return whitespace(normalized).casefold()


def _identity_key(
    kind: ProvenanceIdentityKind,
    value: str,
) -> str:
    payload = (f"{kind}\0{value}").encode()

    return hashlib.sha256(payload).hexdigest()


def _label_is_observed(
    label: str,
    quote: str,
) -> bool:
    """Require the attribution label to appear as a bounded literal."""

    normalized_label = canonical_provenance_label(label)
    normalized_quote = canonical_provenance_label(quote)

    if not normalized_label or not normalized_quote:
        return False

    pattern = r"(?<!\w)" + re.escape(normalized_label) + r"(?!\w)"

    return (
        re.search(
            pattern,
            normalized_quote,
        )
        is not None
    )


def _attribution_host(
    source: Source,
) -> str | None:
    """Return an explicitly observed HTTP(S) attribution-link host."""

    if source.kind != "link" or source.href is None:
        return None

    parsed = urlsplit(source.href)

    if (
        parsed.scheme
        not in {
            "http",
            "https",
        }
        or parsed.hostname is None
    ):
        return None

    host = parsed.hostname.lower().rstrip(".")

    if host.startswith("www."):
        host = host[4:]

    return host or None


def provenance_identity(
    source: Source,
    *,
    label: str,
    quote: str,
) -> ProvenanceIdentity | None:
    """Build an identity only from grounded observed attribution.

    The quote must occur in the supplied source text and must
    literally contain the supplied origin label.

    An observed attribution hyperlink yields a host identity.
    Otherwise the normalized literal attribution label is retained.

    Different identity keys must not automatically be interpreted as
    independent corroboration.
    """

    observed_quote = whitespace(quote)
    observed_text = whitespace(source.text)

    if (
        not observed_quote
        or observed_quote not in observed_text
        or not _label_is_observed(
            label,
            observed_quote,
        )
    ):
        return None

    normalized_label = canonical_provenance_label(label)
    host = _attribution_host(source)

    if host is not None:
        kind: ProvenanceIdentityKind = "attribution_host"
        identity_value = host
    else:
        kind = "attribution_label"
        identity_value = normalized_label

    return ProvenanceIdentity(
        kind=kind,
        key=_identity_key(
            kind,
            identity_value,
        ),
        label=whitespace(label),
        source_id=source.id,
        quote=observed_quote,
        host=host,
    )


def provenance_identity_from_event(
    value: object,
) -> ProvenanceIdentity | None:
    """Decode a durable provenance identity conservatively."""

    if not isinstance(value, dict):
        return None

    kind = value.get("kind")
    key = value.get("key")
    label = value.get("label")
    source_id = value.get("source_id")
    quote = value.get("quote")
    host = value.get("host")

    if (
        kind
        not in {
            "attribution_label",
            "attribution_host",
        }
        or not isinstance(key, str)
        or not isinstance(label, str)
        or not isinstance(source_id, str)
        or not isinstance(quote, str)
        or (host is not None and not isinstance(host, str))
    ):
        return None

    if kind == "attribution_host":
        if not host:
            return None
        identity_value = host
    else:
        if host is not None:
            return None
        identity_value = canonical_provenance_label(label)

    if key != _identity_key(
        kind,
        identity_value,
    ):
        return None

    return ProvenanceIdentity(
        kind=kind,
        key=key,
        label=label,
        source_id=source_id,
        quote=quote,
        host=host,
    )


def provenance_can_corroborate(
    left: ProvenanceIdentity,
    right: ProvenanceIdentity,
) -> bool:
    """Return whether two grounded origins are conservatively independent.

    Text labels alone are insufficient. Both observations need explicit
    attribution links, and both the observed host and literal attribution
    label must differ.
    """

    if left.host is None or right.host is None:
        return False

    return left.host != right.host and canonical_provenance_label(
        left.label
    ) != canonical_provenance_label(right.label)


def independent_corroboration_count(
    current: ProvenanceIdentity,
    observations: list[ProvenanceIdentity],
) -> int:
    """Count pairwise-independent origins beyond the current origin."""

    selected = [current]

    unique = {observation.key: observation for observation in observations}

    for observation in sorted(
        unique.values(),
        key=lambda item: item.key,
    ):
        if observation.key == current.key:
            continue

        if all(
            provenance_can_corroborate(
                observation,
                existing,
            )
            for existing in selected
        ):
            selected.append(observation)

    return len(selected) - 1
