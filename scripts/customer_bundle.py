# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Create a private delivery ZIP from a tested wheel and an existing customer agreement."""

import argparse
import hashlib
import re
import zipfile
from pathlib import Path

from package_release import read_candidate
from release_matrix import ROOT


def make_bundle(order: str, agreement: Path, root: Path = ROOT) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", order):
        raise ValueError("Order reference must contain only letters, digits, _ and -")
    if not agreement.is_file() or not agreement.read_bytes().startswith(b"%PDF-"):
        raise ValueError("Supply the actual agreed license PDF; this script does not draft one")
    _, artifacts = read_candidate(root)
    wheel = next(p for p in artifacts if p.suffix == ".whl")
    files = {
        wheel.name: wheel.read_bytes(),
        "AGREEMENT.pdf": agreement.read_bytes(),
        "LICENSE": (root / "LICENSE").read_bytes(),
        "COPYRIGHT.md": (root / "COPYRIGHT.md").read_bytes(),
        "INSTALLATION.md": (root / "docs/installation.md").read_bytes(),
    }
    files["INSTALL.md"] = (
        f"# Verboisy delivery — {order}\n\n"
        "Usage rights and support are defined by AGREEMENT.pdf.\n"
        "Python 3.11-3.14 and pipx are required for the CLI installation below.\n"
        "Run from the extracted delivery directory:\n\n"
        f"```bash\npipx install './{wheel.name}'\nverboisy --help\n```\n\n"
        "For the Python API, use a virtual environment:\n\n"
        f"```bash\npython3 -m venv .venv\nsource .venv/bin/activate\n"
        f"python -m pip install './{wheel.name}'\nverboisy --help\n```\n\n"
        "Dependencies download from the configured package index; "
        "this is not an offline bundle.\n"
        "No activation server is implemented. "
        "An order reference is not a secret or an access key.\n"
        "Checksums detect corruption, not authorship; "
        "obtain this bundle through the agreed channel.\n"
    ).encode()
    files["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items())
    ).encode()
    output = root / "build/customer-deliveries"
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"verboisy-{order}.zip"
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order", required=True)
    parser.add_argument("--agreement", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(make_bundle(args.order, args.agreement))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Customer delivery: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
