# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Real HTTP acquisition exercises each new parser through the public research API."""

import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from verboisy import arun
from verboisy.dataset_formats import MIME_TYPES
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings

from tests.test_research.test_dataset_ingestion import no_paid_or_browser_work
from tests.test_research.test_format_workflows import CASES

__all__ = ["no_paid_or_browser_work"]


async def test_public_http_capture_for_every_new_adapter(tmp_path):
    cases = {
        f"/{fmt}": (fmt, raw, properties, expected) for fmt, raw, properties, expected in CASES
    }
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):  # noqa: N802 - standard server interface
            seen.append(self.path)
            fmt, raw, _, _ = cases[self.path]
            self.send_response(200)
            self.send_header(
                "Content-Type", "application/pdf" if fmt == "asset" else MIME_TYPES[fmt][0]
            )
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "run.db"),
        allow_private_network=True,
        allowed_domains=["127.0.0.1"],
        model_request_budget=1,
    )
    try:
        for path, (fmt, raw, properties, expected) in cases.items():
            schema = {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            }
            result = await arun(
                goal="Observe the declared HTTP source",
                schema=schema,
                dataset_sources=[
                    {"format": fmt, "url": f"http://127.0.0.1:{server.server_port}{path}"}
                ],
                maxrows=1,
                config=config,
            )
            assert result.completed and result.records == [{"id": 1, **expected}]
            with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
                assert store.dataset_assets(result.run_id)[0].download.dataset.original_bytes == raw
                assert store.load(result.run_id)["reserved"] == 0
        assert seen == list(cases)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
