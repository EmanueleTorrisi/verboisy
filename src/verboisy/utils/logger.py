# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Centralized logging with an optional structlog integration."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from verboisy.utils.config import Settings, settings


class _CompatLogger:
    """Small adapter that accepts structlog-style keyword context."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def debug(self, message: str, **context: Any) -> None:
        self._logger.debug(_with_context(message, context))

    def info(self, message: str, **context: Any) -> None:
        self._logger.info(_with_context(message, context))

    def warning(self, message: str, **context: Any) -> None:
        self._logger.warning(_with_context(message, context))

    def error(self, message: str, **context: Any) -> None:
        self._logger.error(_with_context(message, context))


def _with_context(
    message: str,
    context: dict[str, Any],
) -> str:
    if not context:
        return message

    details = " ".join(f"{key}={value!r}" for key, value in sorted(context.items()))

    return f"{message} {details}"


def setup_logging(
    config: Settings | None = None,
) -> None:
    """Initialize logging while keeping provider chatter quiet."""

    log_level = getattr(
        logging,
        (config or settings).log_level.upper(),
        logging.INFO,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
    )

    os.environ.setdefault(
        "LITELLM_LOG",
        "ERROR",
    )

    for name in (
        "LiteLLM",
        "litellm",
        "httpx",
        "httpcore",
    ):
        provider_logger = logging.getLogger(name)
        provider_logger.setLevel(logging.ERROR)
        provider_logger.propagate = False

    try:
        import structlog

    except ImportError:
        return

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            (
                structlog.dev.ConsoleRenderer(colors=True)
                if sys.stderr.isatty()
                else structlog.processors.JSONRenderer()
            ),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Return structlog when available, otherwise stdlib logging."""

    try:
        import structlog

    except ImportError:
        return _CompatLogger(logging.getLogger(name))

    return structlog.get_logger(name)
