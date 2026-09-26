"""Resource-heavy documents must expose source facts within the model HTML budget."""

import json

import pytest
from bs4 import BeautifulSoup
from verboisy.browser.dom_parser import DOMParser
from verboisy.core.planner import Planner
from verboisy.extractor.engine import ExtractionEngine

from tests.conftest import action


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


async def test_planner_receives_facts_with_small_budget(
    config, model_script, resource_heavy_profile
):
    config.max_dom_chars = 1000
    completion = model_script(action("EXTRACT"))
    request = await Planner(config=config).decide_next_action(
        "Find AI companies in Fall 2026",
        "https://example.com/companies/fixture",
        resource_heavy_profile,
        [],
    )
    assert request.action == "EXTRACT"
    prompt = json.loads(completion.await_args.kwargs["messages"][1]["content"])
    assert len(prompt["page_html"]) <= config.max_dom_chars
    assert_facts(prompt["page_html"])
    assert prompt["page_truncated"] is False
    controls = json.loads(prompt["interactive_elements"])
    assert any(
        control["html_attributes"].get("href") == "https://fixture.example/" for control in controls
    )


async def test_extractor_receives_facts_with_small_budget(
    config, model_script, resource_heavy_profile
):
    config.max_dom_chars = 1000
    record = {
        "name": "Fixture company",
        "website": "https://fixture.example/",
        "batch": "Fall 2026",
    }
    completion = model_script({"results": [record]})
    engine = ExtractionEngine(
        {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "website": {"type": "string", "format": "uri"},
                    "batch": {"type": "string"},
                },
                "required": ["name", "website"],
            },
        },
        config=config,
    )
    assert await engine.extract_from_html(resource_heavy_profile, "Find AI companies") == [record]
    prompt = json.loads(completion.await_args.kwargs["messages"][1]["content"])
    assert len(prompt["html"]) <= config.max_dom_chars
    assert_facts(prompt["html"])
    assert prompt["html_truncated"] is False
