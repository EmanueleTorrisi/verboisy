"""
Centralized structured logging using structlog.
"""

import logging
import sys

from typing import cast

import structlog

from verboisy.utils.config import settings


def setup_logging() -> None:
    """Initialize structured logging based on the application configuration."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True)
            if sys.stdout.isatty()
            else structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """
    Get a pre-configured structlog logger instance.

    Args:
        name: The name of the module or component requesting the logger.

    Returns:
        structlog.BoundLogger: The configured logger instance.
    """
    return cast(structlog.BoundLogger, structlog.get_logger(name))


# Auto-initialize logging on module import
setup_logging()
