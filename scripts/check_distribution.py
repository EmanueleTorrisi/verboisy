# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Inspect pure-Python distribution contracts and optionally build/install in isolation."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any


def safe_members(names: list[str]) -> None:
    """Reject ambiguous, duplicate or escaping archive paths before extraction."""
    seen = set()
    for name in names:
        path = PurePosixPath(name)
        if (
            not name
            or "\\" in name
            or "\x00" in name
            or path.is_absolute()
            or ".." in path.parts
            or re.match(r"^[A-Za-z]:", name)
            or str(path) in seen
        ):
            raise ValueError("Unsafe distribution archive member")
        seen.add(str(path))


def inspect_archive(path: Path) -> dict[str, Any]:
    """Validate modules, typing, entrypoint, Python range and proprietary license."""
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            safe_members([m.orig_filename for m in members])
            if any(
                m.orig_filename != m.filename
                or stat.S_IFMT(m.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR)
                for m in members
            ):
                raise ValueError("Unsupported wheel member type")
            if sum(m.file_size for m in members) > 50_000_000 or archive.testzip() is not None:
                raise ValueError("Invalid or oversized wheel")
            files = {m.filename: archive.read(m) for m in members if not m.is_dir()}
        metadata = [v for k, v in files.items() if k.endswith(".dist-info/METADATA")]
        modules = sorted(k for k in files if k.startswith("verboisy/") and k.endswith(".py"))
        if "verboisy/py.typed" not in files:
            raise ValueError("Missing py.typed")
        points = [v for k, v in files.items() if k.endswith(".dist-info/entry_points.txt")]
        if len(points) != 1 or not re.search(
            r"(?m)^verboisy\s*=\s*verboisy\.cli\.main:app$", points[0].decode()
        ):
            raise ValueError("Invalid CLI entry point")
    else:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            safe_members([m.name for m in members])
            if (
                any(not (m.isfile() or m.isdir()) for m in members)
                or sum(m.size for m in members) > 50_000_000
            ):
                raise ValueError("Unsupported sdist member type or size")
            files = {}
            for member in members:
                if member.isfile():
                    if "/" not in member.name:
                        raise ValueError("Invalid sdist root layout")
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise ValueError("Unreadable archive member")
                    with stream:
                        files[member.name.split("/", 1)[1]] = stream.read()
        metadata = [v for k, v in files.items() if k == "PKG-INFO"]
        modules = sorted(
            k.removeprefix("src/")
            for k in files
            if k.startswith("src/verboisy/") and k.endswith(".py")
        )
        if "src/verboisy/py.typed" not in files:
            raise ValueError("Missing py.typed")
        config = tomllib.loads(files["pyproject.toml"].decode())
        if config["project"]["scripts"].get("verboisy") != "verboisy.cli.main:app":
            raise ValueError("Invalid CLI entry point")
    if len(metadata) != 1:
        raise ValueError("Ambiguous package metadata")
    parsed = BytesParser().parsebytes(metadata[0])
    if (
        parsed.get("Name") != "verboisy"
        or parsed.get("Requires-Python") != ">=3.11,<3.15"
        or parsed.get("License-Expression") != "LicenseRef-Verboisy-Source-Inspection-2.0"
    ):
        raise ValueError("Distribution metadata disagrees with package contract")
    licenses = [v for k, v in files.items() if k.endswith("LICENSE")]
    if not licenses or any(b"VERBOISY SOURCE INSPECTION LICENSE 2.0" not in v for v in licenses):
        raise ValueError("Missing proprietary license")
    if not modules or "verboisy/__init__.py" not in modules or "verboisy/api.py" not in modules:
        raise ValueError("Missing public Python modules")
    forbidden = ("tests/", "__pycache__", ".env", ".so", ".pyd", ".pyc", ".git/")
    if any(any(part in name for part in forbidden) for name in files):
        raise ValueError("Unexpected test, cache, secret or native binary in distribution")
    return {
        "version": parsed.get("Version"),
        "python": parsed.get("Requires-Python"),
        "license": parsed.get("License-Expression"),
        "modules": modules,
    }


def _run(command: list[str], cwd: Path) -> None:
    environment = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME"):
        environment.pop(key, None)
    environment["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    subprocess.run(command, cwd=cwd, env=environment, check=True, timeout=600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--from-sdist", action="store_true")
    parser.add_argument("--install-smoke", action="store_true")
    args = parser.parse_args()
    stage = "locating artifacts"
    try:
        wheels = list(args.dist_dir.resolve().glob("*.whl"))
        sources = list(args.dist_dir.resolve().glob("*.tar.gz"))
        if len(wheels) != 1 or len(sources) != 1:
            raise ValueError(
                "Expected exactly one wheel and one sdist; "
                f"found {len(wheels)} wheels and {len(sources)} sdists. "
                "Build into a fresh output directory with poetry build --output."
            )
        stage = "inspecting archive contracts"
        contract = inspect_archive(wheels[0])
        project = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
        )
        if contract["version"] != project["project"]["version"]:
            raise ValueError("Distribution version differs from source project")
        if inspect_archive(sources[0]) != contract:
            raise ValueError("Wheel and sdist contracts differ")
        temporary_root = Path(__file__).resolve().parents[1] / "build" / "distribution-validation"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="verboisy-distribution-", dir=temporary_root
        ) as temporary:
            work = Path(temporary)
            if args.from_sdist:
                stage = "rebuilding from sdist"
                with tarfile.open(sources[0]) as archive:
                    archive.extractall(work, filter="data")
                extracted = next(p for p in work.iterdir() if p.is_dir())
                rebuilt = work / "rebuilt"
                _run(
                    [
                        sys.executable,
                        "-m",
                        "build",
                        "--wheel",
                        "--outdir",
                        str(rebuilt),
                        str(extracted),
                    ],
                    work,
                )
                if inspect_archive(next(rebuilt.glob("*.whl"))) != contract:
                    raise ValueError("Rebuilt wheel contract differs")
            if args.install_smoke:
                stage = "installing and checking the fresh environment"
                environment = work / "environment"
                _run([sys.executable, "-m", "venv", str(environment)], work)
                python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                empty = work / "empty"
                empty.mkdir()
                _run([str(python), "-m", "pip", "install", str(wheels[0])], empty)
                _run([str(python), "-m", "pip", "check"], empty)
                _run(
                    [
                        str(python),
                        "-c",
                        "import verboisy; from pathlib import Path; "
                        "assert verboisy.__version__ == '"
                        + str(contract["version"])
                        + "'; assert Path(verboisy.__file__).with_name('py.typed').is_file(); "
                        "from verboisy import run, arun, RunResult, StreamLedger, StreamLimits, "
                        "StreamResult, stream_dataset; "
                        "from verboisy.browser.context import BrowserManager; "
                        "assert len(verboisy.__all__) == 7",
                    ],
                    empty,
                )
                _run([str(python), "-m", "verboisy", "--help"], empty)
        print(
            json.dumps(
                {
                    "passed": True,
                    **contract,
                    "from_sdist": args.from_sdist,
                    "installed": args.install_smoke,
                }
            )
        )
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        tarfile.TarError,
        zipfile.BadZipFile,
        subprocess.SubprocessError,
    ) as error:
        detail = str(error) if type(error) is ValueError else type(error).__name__
        print(f"Distribution validation failed ({stage}): {detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
