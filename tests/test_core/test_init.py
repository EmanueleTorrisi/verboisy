"""Tests for lazy imports in the core package."""

import importlib

import pytest
import verboisy.core as core


@pytest.mark.parametrize(
    ("name", "module_name"),
    [
        ("Agent", "verboisy.core.agent"),
        ("Planner", "verboisy.core.planner"),
    ],
)
def test_lazy_imports(name: str, module_name: str) -> None:
    """Lazy imports should expose the correct classes."""
    expected = getattr(importlib.import_module(module_name), name)

    assert core.__getattr__(name) is expected
    assert getattr(core, name) is expected


def test_unknown_lazy_import_raises_attribute_error() -> None:
    """Unknown core attributes should raise AttributeError."""
    with pytest.raises(AttributeError, match="^MissingExport$"):
        core.__getattr__("MissingExport")
