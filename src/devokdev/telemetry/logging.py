"""Structured logging with structlog: readable in a terminal, JSON in CI.

Later milestones add OpenTelemetry traces; log lines will then carry trace IDs.
"""

from __future__ import annotations

import logging

import structlog

from devokdev.config import Settings


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level)
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s", force=True)
    # httpx logs every request URL at INFO; the router already logs each call's decision.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))
