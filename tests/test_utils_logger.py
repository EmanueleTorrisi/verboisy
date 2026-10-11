# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Logging stays usable both with and without optional structlog imports."""

import logging
import sys
from types import SimpleNamespace

from verboisy.utils import logger
from verboisy.utils.config import Settings


def test_compat_logger_methods_and_plain_message(caplog, monkeypatch):
    adapter = logger._CompatLogger(logging.getLogger("compat"))
    with caplog.at_level(logging.DEBUG):
        adapter.debug("debug")
        adapter.info("info", b=2, a=1)
        adapter.warning("warning")
        adapter.error("error", code=3)
    assert "debug" in caplog.text
    assert "info a=1 b=2" in caplog.text
    assert "warning" in caplog.text
    assert "error code=3" in caplog.text
    assert logger._with_context("plain", {}) == "plain"

    # Exercise the fallback path even when structlog is installed locally.
    monkeypatch.setitem(sys.modules, "structlog", None)
    assert isinstance(logger.get_logger("fallback"), logger._CompatLogger)
    logger.setup_logging(Settings(_env_file=None, log_level="debug"))


def test_structlog_integration_branch(monkeypatch):
    configured = []
    bound = object()
    fake = SimpleNamespace()
    fake.stdlib = SimpleNamespace(
        add_log_level=object(),
        add_logger_name=object(),
        LoggerFactory=lambda: "factory",
        BoundLogger=object,
    )
    fake.processors = SimpleNamespace(
        TimeStamper=lambda fmt: ("stamp", fmt),
        StackInfoRenderer=lambda: "stack",
        format_exc_info="exc",
        JSONRenderer=lambda: "json",
    )
    fake.dev = SimpleNamespace(ConsoleRenderer=lambda colors: ("console", colors))
    fake.configure = lambda **kwargs: configured.append(kwargs)
    fake.get_logger = lambda name: (bound, name)
    monkeypatch.setitem(sys.modules, "structlog", fake)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    logger.setup_logging(Settings(_env_file=None, log_level="info"))
    assert configured and "json" in configured[0]["processors"]
    assert logger.get_logger("named") == (bound, "named")

    configured.clear()
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    logger.setup_logging(Settings(_env_file=None, log_level="info"))
    assert ("console", True) in configured[0]["processors"]
