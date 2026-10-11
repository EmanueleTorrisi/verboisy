# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Resource-heavy documents must expose source facts within the model HTML budget."""

import json

import pytest
from bs4 import BeautifulSoup
from verboisy.browser.dom_parser import DOMParser


@pytest.fixture
def resource_heavy_profile():
    resources = "".join(
        f'<link rel="modulepreload" href="https://assets.example/chunk-{index}.js">'
        f'<meta name="asset-{index}" content="not a company fact">'
        for index in range(500)
    )
    return (
        "<html><head><title>Fixture company</title>"
        + resources
        + "</head><body><main><h1>Fixture company</h1>"
        "<p>AI voice authentication</p><p>Fall 2026</p>"
        '<a href="https://fixture.example/">Actual company website</a>'
        '<a href="/companies/fixture">YC profile</a>'
        "</main></body></html>"
    )


def assert_facts(html):
    parsed = BeautifulSoup(html, "html.parser")
    assert parsed.title.get_text() == "Fixture company"
    assert "AI voice authentication" in parsed.get_text()
    assert "Fall 2026" in parsed.get_text()
    assert parsed.find("a", href="https://fixture.example/").get_text() == "Actual company website"
    assert parsed.find("a", href="/companies/fixture") is not None
    assert parsed.find(["link", "meta"]) is None


def test_resource_tags_do_not_displace_facts(resource_heavy_profile):
    assert len(resource_heavy_profile) > 10000
    assert "Fall 2026" not in resource_heavy_profile[:10000]
    cleaned = DOMParser.clean_html(resource_heavy_profile)
    assert_facts(cleaned[:1000])


def test_snapshot_budget_keeps_facts(resource_heavy_profile):
    from verboisy.evidence.snapshot import chunks, snapshot

    page = snapshot(resource_heavy_profile, "https://example.com/companies/fixture")
    rendered = json.dumps([s.model_dump() for batch in chunks(page, 1000) for s in batch])
    assert "Fall 2026" in rendered and "https://fixture.example/" in rendered
    assert "modulepreload" not in rendered
