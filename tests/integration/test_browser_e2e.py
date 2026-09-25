"""Real Chromium + actual CLI/LiteLLM HTTP transport; the model endpoint is a test stub."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
    "minItems": 1,
}
PAGE = '<main><h1>Directory fixture</h1><article id="person">Aurora Labs</article></main>'


@pytest.fixture
def service():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            data = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            context = json.loads(payload["messages"][1]["content"])
            if "html" in context:
                assert "Aurora Labs" in context["html"]
                answer = {"results": [{"name": "Aurora Labs"}]}
            elif context["current_url"] == "about:blank":
                answer = {
                    "thought": "fixture navigate",
                    "action": "NAVIGATE",
                    "parameters": {"url": f"http://127.0.0.1:{self.server.server_port}/directory"},
                }
            elif context["saved_record_count"] == 0:
                answer = {"thought": "fixture extract", "action": "EXTRACT", "parameters": {}}
            else:
                answer = {"thought": "fixture finish", "action": "FINISH", "parameters": {}}
            response = json.dumps(
                {
                    "id": "test-response",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "test",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": json.dumps(answer)},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.browser
def test_cli_browser_resume_export(service, tmp_path):
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(chromium_sandbox=False)
            browser.close()
    except Exception as exc:
        if os.getenv("VERBOISY_REQUIRE_BROWSER") == "1":
            pytest.fail(f"Required Chromium unavailable: {exc}")
        pytest.skip("Chromium unavailable; VERBOISY_REQUIRE_BROWSER=1 makes this a failure")
    url, requests = service
    (tmp_path / "schema.json").write_text(json.dumps(SCHEMA))
    environment = {
        **os.environ,
        "SQLITE_DB_PATH": str(tmp_path / "runs.db"),
        "LITELLM_MODEL": "openai/test",
        "LITELLM_API_BASE": url + "/v1",
        "LITELLM_API_KEY": "test-only",
        "ALLOW_PRIVATE_NETWORK": "true",
        "BROWSER_SANDBOX": "false",
        "USER_AGENT_ROTATION": "false",
        "ACTION_DELAY_SECONDS": "0",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    }
    first = subprocess.run(
        [
            sys.executable,
            "-m",
            "verboisy",
            "run",
            "--goal",
            "Read directory",
            "--schema",
            "schema.json",
            "--export",
            "result.json",
            "--max-steps",
            "2",
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=90,
    )
    assert first.returncode == 2, first.stdout + first.stderr
    assert not (tmp_path / "result.json").exists()
    second = subprocess.run(
        [sys.executable, "-m", "verboisy", "run", "--resume"],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=90,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert json.loads((tmp_path / "result.json").read_text()) == [{"name": "Aurora Labs"}]
    assert len(requests) == 4


async def test_actual_litellm_http_transport(service, config, monkeypatch):
    """The production SDK and HTTP transport talk to an explicitly local stub."""
    from pydantic import SecretStr
    from verboisy.llm.client import LLMClient

    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    url, requests = service
    config.litellm_api_base = url + "/v1"
    config.litellm_api_key = SecretStr("test-only")
    client = LLMClient(config=config)
    response = await client.complete_json("Return JSON", json.dumps({"current_url": "about:blank"}))
    assert response["action"] == "NAVIGATE"
    assert len(requests) == 1 and client.total_tokens == 20
