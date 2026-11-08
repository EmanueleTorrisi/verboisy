# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Import and help avoid research runtimes while public bindings remain exact."""

import importlib
import json
import os
import pickle
import subprocess
import sys
from pathlib import Path

import pytest
import verboisy

PUBLIC = [
    ("verboisy", "RunResult", "verboisy.api"),
    ("verboisy", "arun", "verboisy.api"),
    ("verboisy", "run", "verboisy.api"),
    ("verboisy", "StreamLedger", "verboisy.streaming.ledger"),
    ("verboisy", "StreamLimits", "verboisy.streaming.contract"),
    ("verboisy", "StreamResult", "verboisy.streaming.contract"),
    ("verboisy", "stream_dataset", "verboisy.streaming.api"),
    ("verboisy.streaming", "StreamLedger", "verboisy.streaming.ledger"),
    ("verboisy.streaming", "StreamLimits", "verboisy.streaming.contract"),
    ("verboisy.streaming", "StreamResult", "verboisy.streaming.contract"),
    ("verboisy.streaming", "stream_dataset", "verboisy.streaming.api"),
]


UTILITY_EXPORTS = [
    ("settings", "verboisy.utils.config"),
    ("VerboisyError", "verboisy.utils.exceptions"),
    ("NavigationError", "verboisy.utils.exceptions"),
    ("ExtractionError", "verboisy.utils.exceptions"),
    ("PlanningError", "verboisy.utils.exceptions"),
    ("get_logger", "verboisy.utils.logger"),
]


@pytest.mark.parametrize("name,origin", UTILITY_EXPORTS)
def test_utility_exports_keep_the_original_singleton_or_callable(monkeypatch, name, origin):
    module = importlib.import_module("verboisy.utils")
    expected = getattr(importlib.import_module(origin), name)
    monkeypatch.delitem(module.__dict__, name, raising=False)
    assert getattr(module, name) is expected
    assert module.__dict__[name] is expected
    assert name in dir(module) and name in module.__all__
    with monkeypatch.context() as isolated:

        def unexpected(_name):
            raise AssertionError("A cached utility export must not import again")

        isolated.setattr(module, "import_module", unexpected)
        assert getattr(module, name) is expected


@pytest.mark.parametrize("package,name,origin", PUBLIC)
def test_public_exports_are_original_cached_and_pickleable(monkeypatch, package, name, origin):
    module = importlib.import_module(package)
    expected = getattr(importlib.import_module(origin), name)
    monkeypatch.delitem(module.__dict__, name, raising=False)
    actual = getattr(module, name)
    assert actual is expected
    assert module.__dict__[name] is expected
    assert pickle.loads(pickle.dumps(actual)) is expected
    assert name in dir(module) and name in module.__all__
    with monkeypatch.context() as isolated:

        def unexpected(_name):
            raise AssertionError("A cached export must not import again")

        isolated.setattr(module, "import_module", unexpected)
        assert getattr(module, name) is expected


@pytest.mark.parametrize(
    "package",
    [
        "verboisy",
        "verboisy.streaming",
        "verboisy.utils",
        "verboisy.cli.main",
        "verboisy.cli.streaming",
    ],
)
def test_unknown_lazy_names_raise_attribute_error(package):
    module = importlib.import_module(package)
    with pytest.raises(AttributeError, match="no attribute"):
        module.__getattr__("_not_a_verboisy_export")


@pytest.mark.parametrize(
    "package,name,origin_name",
    [
        ("verboisy", "run", "verboisy.api"),
        ("verboisy.streaming", "stream_dataset", "verboisy.streaming.api"),
        ("verboisy.utils", "settings", "verboisy.utils.config"),
    ],
)
def test_reload_restores_public_bindings(monkeypatch, package, name, origin_name):
    module = importlib.import_module(package)
    origin = importlib.import_module(origin_name)
    replacement = object()
    try:
        with monkeypatch.context() as isolated:
            isolated.setattr(origin, name, replacement)
            importlib.reload(module)
            assert getattr(module, name) is replacement
    finally:
        importlib.reload(module)
    assert getattr(module, name) is getattr(origin, name)


@pytest.mark.parametrize("package", ["verboisy.cli.main", "verboisy.cli.streaming"])
def test_cli_runtime_loaders_preserve_monkeypatch_hooks(monkeypatch, package):
    module = importlib.import_module(package)
    names = tuple(module._EXPORTS)
    for name in names:
        monkeypatch.delitem(module.__dict__, name, raising=False)
    loader = module._load_run_runtime if package.endswith(".main") else module._load_stream_runtime
    if package.endswith(".main"):
        loader()
    else:
        loader(*names)
    for name, origin in module._EXPORTS.items():
        assert getattr(module, name) is getattr(importlib.import_module(origin), name)
        assert name in dir(module)
    name = "run" if package.endswith(".main") else "stream_dataset"
    replacement = object()
    monkeypatch.setitem(module.__dict__, name, replacement)
    if package.endswith(".main"):
        loader()
    else:
        loader(*names)
    assert getattr(module, name) is replacement


COLD = r"""
import importlib.abc
import json
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
args = json.loads(sys.argv[2])
blocked = ("jsonschema", "rfc3987_syntax", "litellm", "openai", "playwright",
           "verboisy.api", "verboisy.product", "verboisy.streaming.api")
if args == ["stream-api"]:
    blocked = tuple(name for name in blocked
                    if name not in ("jsonschema", "rfc3987_syntax", "verboisy.streaming.api"))
if args == ["utility-package"]:
    blocked += ("verboisy.utils.config", "verboisy.utils.logger", "verboisy.utils.exceptions")
class RejectRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise AssertionError("Unexpected runtime import: " + fullname)
sys.meta_path.insert(0, RejectRuntime())
import verboisy
assert verboisy.__version__ == sys.argv[3]
if args == ["utility-package"]:
    import verboisy.utils
    assert "settings" in dir(verboisy.utils)
elif args == ["utilities"]:
    from verboisy.utils import (
        settings, get_logger, VerboisyError, ExtractionError, NavigationError, PlanningError,
    )
    from verboisy.utils.config import settings as original_settings
    assert settings is original_settings
    assert callable(get_logger) and issubclass(ExtractionError, VerboisyError)
elif len(args) == 2 and args[0] == "module":
    module = importlib.import_module(args[1])
    assert module.__name__ == args[1]
elif args == ["metadata"]:
    from verboisy import StreamLedger, StreamLimits, StreamResult
    assert StreamLedger.__module__ == "verboisy.streaming.ledger"
    assert StreamLimits.__module__ == StreamResult.__module__ == "verboisy.streaming.contract"
elif args == ["stream-api"]:
    from verboisy import stream_dataset
    assert stream_dataset.__module__ == "verboisy.streaming.api"
    assert "jsonschema" in sys.modules
elif args:
    from verboisy.cli.main import app
    try:
        app(args=args, prog_name="verboisy")
    except SystemExit as error:
        assert error.code in (0, None)
assert not any(name == prefix or name.startswith(prefix + ".")
               for name in sys.modules for prefix in blocked)
print("COLD_START_OK")
"""


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["metadata"],
        ["stream-api"],
        ["--help"],
        ["run", "--help"],
        ["stream", "--help"],
        ["stream-status", "--help"],
        ["formats"],
        ["utility-package"],
        ["utilities"],
        ["module", "verboisy.presentation_config"],
        ["module", "verboisy.provider_config"],
        ["module", "verboisy.source_config"],
        ["module", "verboisy.time_series_contract"],
        ["module", "verboisy.utils.config"],
        ["module", "verboisy.utils.logger"],
        ["module", "verboisy.evidence.models"],
    ],
)
def test_cold_import_and_help_do_not_load_runtime(args, tmp_path):
    root = str(Path(verboisy.__file__).resolve().parent.parent)
    env = {key: value for key, value in os.environ.items() if not key.endswith("API_KEY")}
    env.update(
        PYTHON_DOTENV_DISABLED="1",
        LITELLM_LOCAL_MODEL_COST_MAP="True",
        MODEL_REQUEST_BUDGET="1",
        SEARCH_REQUEST_BUDGET="0",
        SEARCH_PROVIDER="disabled",
        BROWSER_AUTO_INSTALL="false",
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", COLD, root, json.dumps(args), verboisy.__version__],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert b"COLD_START_OK" in result.stdout
    if "--help" in args:
        assert b"Usage:" in result.stdout
