from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from varipaw.core.validation import (
    frozen_setattr,
    require_non_empty_str,
    require_non_negative_int,
    require_valid_error_code,
)


@dataclass(frozen=True, slots=True)
class LogContext:
    trace_id: str | None = None
    step_index: int | None = None
    duration_ms: int | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.trace_id is not None:
            frozen_setattr(
                self,
                "trace_id",
                require_non_empty_str(self.trace_id, "trace_id"),
            )
        if self.step_index is not None:
            frozen_setattr(
                self,
                "step_index",
                require_non_negative_int(self.step_index, "step_index"),
            )
        if self.duration_ms is not None:
            frozen_setattr(
                self,
                "duration_ms",
                require_non_negative_int(self.duration_ms, "duration_ms"),
            )
        if self.error_code is not None:
            frozen_setattr(
                self,
                "error_code",
                require_valid_error_code(self.error_code, "error_code"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if getattr(self, f.name) is not None
        }


def _validate_log_level(level: object, field_name: str) -> int:
    if isinstance(level, bool) or not isinstance(level, int):
        raise TypeError(f"{field_name} must be an int")
    if level < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return level


def setup_logger(
    name: str = "varipaw",
    level: int = logging.INFO,
) -> logging.Logger:
    name = require_non_empty_str(name, "name")
    level = _validate_log_level(level, "level")

    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s"
            )
        )
        logger.addHandler(handler)

    logger.setLevel(level)
    logger.propagate = False
    return logger


_CONTEXT_KEYS = frozenset(f.name for f in fields(LogContext))
_RESERVED_KEYS = frozenset({"event"}) | _CONTEXT_KEYS


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    context: LogContext | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    if not isinstance(logger, logging.Logger):
        raise TypeError("logger must be a logging.Logger")
    level = _validate_log_level(level, "level")
    event = require_non_empty_str(event, "event")

    if context is not None and not isinstance(context, LogContext):
        raise TypeError("context must be a LogContext or None")

    if not logger.isEnabledFor(level):
        return

    payload: dict[str, Any] = {"event": event}

    if context is not None:
        payload.update(context.to_dict())

    if extra is not None:
        for key, value in extra.items():
            if not isinstance(key, str):
                raise TypeError("extra keys must be str")
            if key in _RESERVED_KEYS:
                raise ValueError(f"extra contains reserved key: {key}")
            payload[key] = value

    logger.log(
        level,
        json.dumps(payload, ensure_ascii=False, default=str),
    )
