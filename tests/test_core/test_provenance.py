# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

from verboisy.core.provenance import (
    canonical_provenance_label,
    provenance_identity,
)
from verboisy.evidence.models import Source


def text_source(
    text: str = ("According to World Health Organization, " "the value is 42."),
) -> Source:
    return Source(
        id="e1",
        kind="text",
        text=text,
        scope="page",
    )


def link_source(
    href: str = ("https://www.who.int/data/report"),
) -> Source:
    return Source(
        id="e2",
        kind="link",
        text=("Source: World Health Organization"),
        scope="page",
        href=href,
    )


def test_canonical_provenance_label_normalizes_literal_form():
    assert (
        canonical_provenance_label("  World   Health Organization ") == "world health organization"
    )


def test_grounded_text_attribution_builds_label_identity():
    identity = provenance_identity(
        text_source(),
        label="World Health Organization",
        quote=("According to World Health " "Organization, the value is 42."),
    )

    assert identity is not None
    assert identity.kind == "attribution_label"
    assert identity.host is None
    assert identity.label == "World Health Organization"
    assert len(identity.key) == 64


def test_label_identity_is_stable_across_case_and_whitespace():
    first = provenance_identity(
        text_source(),
        label="World Health Organization",
        quote=("According to World Health " "Organization, the value is 42."),
    )

    second = provenance_identity(
        text_source("According to WORLD HEALTH ORGANIZATION, " "the value is 42."),
        label="WORLD HEALTH ORGANIZATION",
        quote=("According to WORLD HEALTH ORGANIZATION, " "the value is 42."),
    )

    assert first is not None
    assert second is not None
    assert first.key == second.key


def test_unobserved_quote_cannot_create_identity():
    assert (
        provenance_identity(
            text_source(),
            label="World Health Organization",
            quote=("World Health Organization " "published another report."),
        )
        is None
    )


def test_label_must_be_inside_grounded_quote():
    assert (
        provenance_identity(
            text_source(),
            label="UNICEF",
            quote=("According to World Health " "Organization, the value is 42."),
        )
        is None
    )


def test_blank_label_cannot_create_identity():
    assert (
        provenance_identity(
            text_source(),
            label=" ",
            quote=("According to World Health " "Organization, the value is 42."),
        )
        is None
    )


def test_grounded_http_link_builds_host_identity():
    identity = provenance_identity(
        link_source(),
        label="World Health Organization",
        quote=("Source: World Health Organization"),
    )

    assert identity is not None
    assert identity.kind == "attribution_host"
    assert identity.host == "who.int"


def test_same_attribution_host_ignores_path():
    first = provenance_identity(
        link_source("https://www.who.int/a"),
        label="World Health Organization",
        quote=("Source: World Health Organization"),
    )

    second = provenance_identity(
        link_source("https://who.int/b"),
        label="World Health Organization",
        quote=("Source: World Health Organization"),
    )

    assert first is not None
    assert second is not None
    assert first.key == second.key


def test_non_http_link_falls_back_to_literal_label():
    identity = provenance_identity(
        link_source("mailto:data@example.test"),
        label="World Health Organization",
        quote=("Source: World Health Organization"),
    )

    assert identity is not None
    assert identity.kind == "attribution_label"
    assert identity.host is None


def test_source_id_does_not_change_origin_identity():
    first = provenance_identity(
        text_source(),
        label="World Health Organization",
        quote=("According to World Health " "Organization, the value is 42."),
    )

    other = Source(
        id="different-local-id",
        kind="text",
        text=("According to World Health Organization, " "the value is 42."),
        scope="page",
    )

    second = provenance_identity(
        other,
        label="World Health Organization",
        quote=("According to World Health " "Organization, the value is 42."),
    )

    assert first is not None
    assert second is not None
    assert first.key == second.key


def test_identity_event_is_durable():
    identity = provenance_identity(
        link_source(),
        label="World Health Organization",
        quote=("Source: World Health Organization"),
    )

    assert identity is not None

    assert identity.as_event() == {
        "kind": "attribution_host",
        "key": identity.key,
        "label": "World Health Organization",
        "source_id": "e2",
        "quote": ("Source: World Health Organization"),
        "host": "who.int",
    }


def _linked_origin(
    *,
    label,
    host,
    source_id,
):
    source = Source(
        id=source_id,
        kind="link",
        text=f"Source: {label}",
        scope="page",
        href=f"https://{host}/data",
    )

    identity = provenance_identity(
        source,
        label=label,
        quote=f"Source: {label}",
    )

    assert identity is not None
    return identity


def test_provenance_event_round_trip():
    from verboisy.core.provenance import (
        provenance_identity_from_event,
    )

    identity = _linked_origin(
        label="Agency A",
        host="agency-a.example",
        source_id="a",
    )

    decoded = provenance_identity_from_event(identity.as_event())

    assert decoded == identity


def test_corrupt_provenance_event_is_rejected():
    from verboisy.core.provenance import (
        provenance_identity_from_event,
    )

    identity = _linked_origin(
        label="Agency A",
        host="agency-a.example",
        source_id="a",
    )

    event = identity.as_event()
    event["key"] = "wrong"

    assert provenance_identity_from_event(event) is None


def test_text_only_origins_do_not_corroborate():
    from verboisy.core.provenance import (
        provenance_can_corroborate,
    )

    first = provenance_identity(
        text_source("Source: Agency A"),
        label="Agency A",
        quote="Source: Agency A",
    )
    second = provenance_identity(
        text_source("Source: Agency B"),
        label="Agency B",
        quote="Source: Agency B",
    )

    assert first is not None
    assert second is not None

    assert not provenance_can_corroborate(
        first,
        second,
    )


def test_same_host_does_not_corroborate():
    from verboisy.core.provenance import (
        provenance_can_corroborate,
    )

    first = _linked_origin(
        label="Agency A",
        host="shared.example",
        source_id="a",
    )
    second = _linked_origin(
        label="Agency B",
        host="shared.example",
        source_id="b",
    )

    assert not provenance_can_corroborate(
        first,
        second,
    )


def test_same_literal_origin_label_does_not_corroborate():
    from verboisy.core.provenance import (
        provenance_can_corroborate,
    )

    first = _linked_origin(
        label="Agency A",
        host="a.example",
        source_id="a",
    )
    second = _linked_origin(
        label="Agency A",
        host="b.example",
        source_id="b",
    )

    assert not provenance_can_corroborate(
        first,
        second,
    )


def test_distinct_grounded_origins_can_corroborate():
    from verboisy.core.provenance import (
        provenance_can_corroborate,
    )

    first = _linked_origin(
        label="Agency A",
        host="a.example",
        source_id="a",
    )
    second = _linked_origin(
        label="Agency B",
        host="b.example",
        source_id="b",
    )

    assert provenance_can_corroborate(
        first,
        second,
    )


def test_corroboration_count_deduplicates_origins():
    from verboisy.core.provenance import (
        independent_corroboration_count,
    )

    current = _linked_origin(
        label="Agency A",
        host="a.example",
        source_id="a",
    )
    second = _linked_origin(
        label="Agency B",
        host="b.example",
        source_id="b",
    )
    third = _linked_origin(
        label="Agency C",
        host="c.example",
        source_id="c",
    )

    assert (
        independent_corroboration_count(
            current,
            [
                current,
                second,
                second,
                third,
            ],
        )
        == 2
    )


def test_provenance_event_rejects_non_mapping():
    from verboisy.core.provenance import (
        provenance_identity_from_event,
    )

    assert provenance_identity_from_event("not-an-event") is None


def test_provenance_event_rejects_invalid_field_types():
    from verboisy.core.provenance import (
        provenance_identity_from_event,
    )

    assert (
        provenance_identity_from_event(
            {
                "kind": "attribution_host",
                "key": 123,
                "label": "Agency A",
                "source_id": "a",
                "quote": "Source: Agency A",
                "host": "a.example",
            }
        )
        is None
    )


def test_host_identity_event_requires_host():
    from verboisy.core.provenance import (
        provenance_identity_from_event,
    )

    assert (
        provenance_identity_from_event(
            {
                "kind": "attribution_host",
                "key": "irrelevant",
                "label": "Agency A",
                "source_id": "a",
                "quote": "Source: Agency A",
                "host": None,
            }
        )
        is None
    )


def test_label_identity_event_rejects_host():
    from verboisy.core.provenance import (
        provenance_identity_from_event,
    )

    assert (
        provenance_identity_from_event(
            {
                "kind": "attribution_label",
                "key": "irrelevant",
                "label": "Agency A",
                "source_id": "a",
                "quote": "Source: Agency A",
                "host": "a.example",
            }
        )
        is None
    )


def test_corroboration_count_skips_non_independent_origin():
    from verboisy.core.provenance import (
        independent_corroboration_count,
    )

    current = _linked_origin(
        label="Agency A",
        host="a.example",
        source_id="a",
    )

    # Different host/key, but the same literal origin.
    # That is not independent corroboration.
    repeated_origin = _linked_origin(
        label="Agency A",
        host="mirror.example",
        source_id="mirror",
    )

    assert (
        independent_corroboration_count(
            current,
            [repeated_origin],
        )
        == 0
    )


def test_label_provenance_event_round_trip():
    from verboisy.core.provenance import (
        provenance_identity_from_event,
    )

    identity = provenance_identity(
        Source(
            id="label-source",
            kind="text",
            text="Source: Agency A",
            scope="page",
        ),
        label="Agency A",
        quote="Source: Agency A",
    )

    assert identity is not None
    assert identity.kind == "attribution_label"

    decoded = provenance_identity_from_event(identity.as_event())

    assert decoded == identity
