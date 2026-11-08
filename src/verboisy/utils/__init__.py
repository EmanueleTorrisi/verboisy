# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Shared utilities with configuration loaded only when requested."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import settings
    from .exceptions import ExtractionError, NavigationError, PlanningError, VerboisyError
    from .logger import get_logger

__all__ = [
    "settings",
    "VerboisyError",
    "NavigationError",
    "ExtractionError",
    "PlanningError",
    "get_logger",
]

_EXPORTS = {
    "settings": "verboisy.utils.config",
    "VerboisyError": "verboisy.utils.exceptions",
    "NavigationError": "verboisy.utils.exceptions",
    "ExtractionError": "verboisy.utils.exceptions",
    "PlanningError": "verboisy.utils.exceptions",
    "get_logger": "verboisy.utils.logger",
}

# Reload restores the same public bindings as a fresh import.
for _export_name in _EXPORTS:
    globals().pop(_export_name, None)
del _export_name


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})
