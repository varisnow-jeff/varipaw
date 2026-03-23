"""Runtime error helpers."""

from __future__ import annotations

from typing import Any

from varipaw.core.constants import VALID_ERROR_CODES
from varipaw.core.contracts import ErrorEnvelope
from varipaw.core.validation import require_non_empty_str, require_non_negative_int

__all__ = [
    "VALID_ERROR_CODES",
    "validation_error",
    "tool_not_found",
    "tool_timeout",
    "tool_exec_error",
    "provider_error",
    "internal_error",
]


def validation_error(
    message: str,
    *,
    retriable: bool = False,
    details: dict[str, Any] | None = None,
) -> ErrorEnvelope:
    return ErrorEnvelope(
        code="VALIDATION_ERROR",
        message=message,
        retriable=retriable,
        details=details or {},
    )


def tool_not_found(
    tool_name: str,
    *,
    details: dict[str, Any] | None = None,
) -> ErrorEnvelope:
    require_non_empty_str(tool_name, "tool_name")
    d: dict[str, Any] = {"tool": tool_name}
    if details:
        d.update(details)
    return ErrorEnvelope(
        code="TOOL_NOT_FOUND",
        message=f"Tool not found: {tool_name}",
        retriable=False,
        details=d,
    )


def tool_timeout(
    tool_name: str,
    timeout_ms: int,
    *,
    details: dict[str, Any] | None = None,
) -> ErrorEnvelope:
    require_non_empty_str(tool_name, "tool_name")
    require_non_negative_int(timeout_ms, "timeout_ms")
    d: dict[str, Any] = {"tool": tool_name, "timeout_ms": timeout_ms}
    if details:
        d.update(details)
    return ErrorEnvelope(
        code="TOOL_TIMEOUT",
        message=f"Tool '{tool_name}' timed out after {timeout_ms}ms",
        retriable=True,
        details=d,
    )


def tool_exec_error(
    tool_name: str,
    reason: str,
    *,
    retriable: bool = False,
    details: dict[str, Any] | None = None,
) -> ErrorEnvelope:
    require_non_empty_str(tool_name, "tool_name")
    require_non_empty_str(reason, "reason")
    d: dict[str, Any] = {"tool": tool_name}
    if details:
        d.update(details)
    return ErrorEnvelope(
        code="TOOL_EXEC_ERROR",
        message=f"Tool '{tool_name}' failed: {reason}",
        retriable=retriable,
        details=d,
    )


def provider_error(
    message: str,
    *,
    retriable: bool = True,
    details: dict[str, Any] | None = None,
) -> ErrorEnvelope:
    return ErrorEnvelope(
        code="PROVIDER_ERROR",
        message=message,
        retriable=retriable,
        details=details or {},
    )


def internal_error(
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> ErrorEnvelope:
    return ErrorEnvelope(
        code="INTERNAL_ERROR",
        message=message,
        retriable=False,
        details=details or {},
    )
