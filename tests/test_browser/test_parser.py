"""
Unit tests for the DOMParser utility.
"""

from verboisy.browser.dom_parser import DOMParser


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

    assert "<a id='link1' class='btn' href='https://example.com'>Click Me</a>" in interactive
    assert "<button id='submit-btn' class='primary' href=''>Submit</button>" in interactive
    assert "<input id='username' class='' href=''></input>" in interactive
    assert "Not interactive" not in interactive
