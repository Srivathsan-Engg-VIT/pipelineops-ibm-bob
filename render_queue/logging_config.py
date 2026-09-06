"""
Structured logging configuration for the render_queue package.

All modules should obtain their logger via ``get_logger(__name__)`` rather
than calling structlog directly, so the configuration is guaranteed to be
applied before first use.

Log level is controlled by the ``LOG_LEVEL`` environment variable
(default: ``INFO``).  Valid values are the standard Python level names
(DEBUG, INFO, WARNING, ERROR, CRITICAL).
"""

from __future__ import annotations

import logging
import os
import sys

import structlog

_CONFIGURED = False


def _configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    # Configure the stdlib root logger so that structlog's stdlib fallback
    # (and any third-party code that uses stdlib logging) also emits JSON.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to *name*, configuring the pipeline on first call."""
    _configure()
    return structlog.get_logger(name)
