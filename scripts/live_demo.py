"""Recordable acceptance run with a real configured model and real Chromium."""

import functools
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    if "--help" in sys.argv or "--live" not in sys.argv:
        print("Paid opt-in: python scripts/live_demo.py --live")
        print("Uses your configured model, a local fixture server, and a new demo-runs directory.")
        return 0
    runs = root / "demo-runs"
    runs.mkdir(exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=runs))
    handler = functools.partial(
        SimpleHTTPRequestHandler, directory=str(root / "tests/fixtures/pages")
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}/startup_directory.html"
    environment = {
        **os.environ,
        "SQLITE_DB_PATH": str(output / "verboisy.db"),
        "ALLOW_PRIVATE_NETWORK": "true",
    }
    task_path = output / "task.json"
    task_path.write_text(
        json.dumps(
            {
                "seed_urls": [url],
                "allowed_hosts": ["127.0.0.1"],
                "target_records": 2,
                "max_depth": 0,
                "max_pages": 1,
            }
        )
    )
    command = [
        sys.executable,
        "-m",
        "verboisy",
        "run",
        "--goal",
        f"Open {url}. Extract both company cards. Copy company name, website href, "
        "tagline as description, and batch verbatim from the page. "
        "Do not visit the company websites.",
        "--task",
        str(task_path),
        "--schema",
        str(root / "examples/yc_startups/schema.json"),
        "--export",
        str(output / "result.json"),
        "--max-steps",
        "2",
    ]
    try:
        first = subprocess.run(command, cwd=root, env=environment, check=False)
        if first.returncode == 2:
            final = subprocess.run(
                [sys.executable, "-m", "verboisy", "run", "--resume"],
                cwd=root,
                env=environment,
                check=False,
            )
            if final.returncode:
                return final.returncode
        elif first.returncode:
            return first.returncode
        actual = json.loads((output / "result.json").read_text())
        expected = json.loads((root / "tests/fixtures/expected/startup_directory.json").read_text())
        if sorted(actual, key=lambda row: row["name"]) != sorted(
            expected, key=lambda row: row["name"]
        ):
            print(
                f"Acceptance failed: actual output differs from fixture evidence. Inspect {output}"
            )
            return 1
        print(f"Live acceptance passed. Actual database and output: {output}")
        return 0
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
