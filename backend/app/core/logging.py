"""Structured logging with request ids (Plan Phase 0 task 2).

Logs are JSON lines. Never log secrets, raw user free text or real identities
(Plan §5.12); log pseudonymous ids only.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

import structlog

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def _add_request_id(
    _logger: object, _method: str, event_dict: structlog.typing.EventDict
) -> structlog.typing.EventDict:
    rid = request_id_var.get()
    if rid is not None:
        event_dict["request_id"] = rid
    return event_dict


def configure_logging(*, json_output: bool = True, level: int = logging.INFO) -> None:
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if json_output
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_request_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(name)
    return logger
