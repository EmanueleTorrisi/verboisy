"""
Unit tests for the DOMParser utility.
"""

from verboisy.browser.dom_parser import DOMParser, clean_html

from tests.conftest import load_html_fixture


def test_clean_html_removes_scripts_and_styles() -> None:
    raw_html = """
    <html>
        <head>
            <script>alert('test');</script>
            <style>body { color: red; }</style>
        </head>
        <body>
            <div id="content" class="main-content" style="background: blue;">
                <p>Important text</p>
            </div>
            <!-- This is a comment -->
            <footer>Footer data</footer>
        </body>
    </html>
    """

    cleaned = DOMParser.clean_html(raw_html)

    assert "<script>" not in cleaned
    assert "<style>" not in cleaned
    assert "alert('test')" not in cleaned
    assert "<!-- This is a comment -->" not in cleaned
    assert "<footer>" not in cleaned
    assert "Important text" in cleaned
    assert 'id="content"' in cleaned
    # Ensure inline styles are stripped
    assert 'style="background: blue;"' not in cleaned


def test_extract_interactive_elements() -> None:
    raw_html = """
    <body>
        <a href="https://example.com" id="link1" class="btn">Click Me</a>
        <button id="submit-btn" class="primary">Submit</button>
        <p>Not interactive</p>
        <input type="text" id="username" name="user" />
    </body>
    """

    interactive = DOMParser.extract_interactive_elements(raw_html)

    import json

    controls = {entry["selector"]: entry for entry in json.loads(interactive)}
    assert controls["#link1"]["html_attributes"]["href"] == "https://example.com"
    assert controls["#link1"]["label"] == "Click Me"
    assert controls["#submit-btn"]["label"] == "Submit"
    assert controls["#username"]["html_attributes"] == {"type": "text", "name": "user"}
    assert "Not interactive" not in interactive


def test_clean_html_strips_nav_scripts_and_styles() -> None:
    cleaned = clean_html(load_html_fixture("startup_directory.html"))
    assert "analytics.js" not in cleaned
    assert "cookie-banner" not in cleaned
    assert "Aurora Labs" in cleaned


def test_golden_listing_tree():
    import re

    from bs4 import BeautifulSoup

    from tests.conftest import FIXTURES_DIR

    cleaned = BeautifulSoup(clean_html(load_html_fixture("startup_directory.html")), "html.parser")
    expected = BeautifulSoup(
        (FIXTURES_DIR / "expected/startup_directory.cleaned.html").read_text(), "html.parser"
    )

    def normalize(tree):
        return re.sub(r">\s+<", "><", str(tree)).strip()

    assert normalize(cleaned.main) == normalize(expected.main)


def test_directory_filters_keep_labels_options_and_unique_selectors():
    import json

    from bs4 import BeautifulSoup

    html = """<main>
        <input id="batch" type="checkbox"><label for="batch">Fall 2026</label>
        <label>AI only<input type="checkbox"></label>
        <button id="duplicate">First</button><button id="duplicate">Second</button>
        <button id="space id" aria-label="More filters"></button>
        <input type="hidden" value="SECRET"><input type="password" value="SECRET">
        <button hidden>SECRET</button>
        <select id="industry"><option value="">All</option><option value="ai">AI</option></select>
        <div role="checkbox" aria-checked="false">AI research</div>
    </main>"""
    soup = BeautifulSoup(html, "html.parser")
    controls = json.loads(DOMParser.extract_interactive_elements(html))
    assert "SECRET" not in json.dumps(controls)
    assert next(c for c in controls if c["selector"] == "#batch")["label"] == "Fall 2026"
    assert any(c["tag"] == "input" and c["label"] == "AI only" for c in controls)
    assert any(c["label"] == "More filters" for c in controls)
    select = next(c for c in controls if c["tag"] == "select")
    assert select["options"] == [{"value": "", "label": "All"}, {"value": "ai", "label": "AI"}]
    for control in controls:
        assert len(soup.select(control["selector"])) == 1, control


def test_filter_controls_precede_large_result_lists():
    import json

    html = '<a href="/company">Company</a>' * 150 + '<button id="filter">Batch</button>'
    controls = json.loads(DOMParser.extract_interactive_elements(html))
    assert len(controls) == 100 and controls[0]["selector"] == "#filter"
