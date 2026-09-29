"""Real Chromium DOM and pagination checks; no model credential is used."""

import hashlib
import os

import pytest
from verboisy.browser.context import BrowserManager
from verboisy.core.research import CAPTURE_PAGE
from verboisy.evidence.snapshot import snapshot
from verboisy.utils.config import Settings

pytestmark = pytest.mark.browser


async def test_rendered_visibility_pagination_and_sandbox_configuration():
    config = Settings(
        _env_file=None,
        browser_auto_install=False,
        browser_sandbox=os.environ.get("TEST_BROWSER_SANDBOX", "true") == "true",
    )
    manager = BrowserManager(config)
    try:
        page = await manager.start()
        await page.set_content("""<style>.hidden {display:none}</style>
          <article><h1>First</h1><p class="hidden">Fabricated</p></article>
          <button id="next"
          onclick="document.querySelector('h1').textContent='Second'">Next</button>""")
        captured = await page.evaluate(CAPTURE_PAGE, 100000)
        assert captured["url"] == page.url
        assert "Fabricated" in captured["html"]
        first = snapshot(captured["visible_html"], "https://fixture.example/")
        assert first.content_hash == hashlib.sha256(captured["visible_html"].encode()).hexdigest()
        assert (await page.evaluate(CAPTURE_PAGE, 1))["oversized"]
        assert "First" in [s.text for s in first.sources]
        assert "Fabricated" not in [s.text for s in first.sources]
        await page.locator("#next").click()
        second = snapshot(
            (await page.evaluate(CAPTURE_PAGE, 100000))["visible_html"], "https://fixture.example/"
        )
        assert "Second" in [s.text for s in second.sources]
        assert "First" not in [s.text for s in second.sources]
    finally:
        await manager.close()


async def test_real_browser_resume_and_json_csv_exports(tmp_path, monkeypatch):
    """Actual HTTP and browser traversal; scripted model, not live accuracy evidence."""
    import functools
    import json
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from verboisy import arun

    (tmp_path / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><a href="/people.html">People</a>',
        encoding="utf-8",
    )
    (tmp_path / "people.html").write_text(
        '<!doctype html><meta charset="utf-8">'
        "<article><p>Anaïs</p><p>31</p></article><article><p>李雷</p><p>22</p></article>",
        encoding="utf-8",
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    schema = {
        "type": "object",
        "properties": {"person": {"type": "string"}, "years": {"type": "integer"}},
        "required": ["person", "years"],
        "additionalProperties": False,
    }

    async def respond(_self, _system, prompt):
        payload = json.loads(prompt)
        if "candidate" in payload:
            return {
                "relevant": True,
                "same_entity": True,
                "supported_fields": list(payload["candidate"]["evidence"]),
                "rejected_fields": [],
            }
        sources = {s["text"]: s for s in payload["sources"]}
        candidates = []
        for name, age in [("Anaïs", 31), ("李雷", 22)]:
            if name in sources:
                candidates.append(
                    {
                        "scope": sources[name]["scope"],
                        "record": {"person": name, "years": age},
                        "evidence": {
                            "/person": {"source": sources[name]["id"], "quote": name},
                            "/years": {
                                "source": sources[str(age)]["id"],
                                "quote": str(age),
                                "transform": "integer",
                            },
                        },
                    }
                )
        return {"candidates": candidates, "priority_links": []}

    monkeypatch.setattr("verboisy.llm.client.LLMClient.complete_json", respond)
    config = Settings(
        _env_file=None,
        browser_auto_install=False,
        allow_private_network=True,
        browser_sandbox=os.environ.get("TEST_BROWSER_SANDBOX", "true") == "true",
        sqlite_db_path=str(tmp_path / "run.db"),
        action_delay_seconds=0,
    )
    try:
        first = await arun(
            goal="Collect people and ages",
            schema=schema,
            task={"seed_urls": [origin + "/index.html"], "target_records": 2, "settle_ms": 0},
            config=config,
            max_steps=1,
            export=tmp_path / "data.json",
        )
        assert first.status == "PAUSED" and not first.records
        second = await arun(resume=first.run_id, config=config)
        assert second.completed
        assert second.records == [{"person": "Anaïs", "years": 31}, {"person": "李雷", "years": 22}]
        assert json.loads(second.manifest_path.read_text())["pages"] == {"done": 2}
        evidence = json.loads((tmp_path / "data.json.evidence.json").read_text())
        assert all(r["snapshot"]["url"] == origin + "/people.html" for r in evidence)
        exported = await arun(resume=first.run_id, config=config, export=tmp_path / "data.csv")
        assert exported.records == second.records
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
