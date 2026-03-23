"""Shared constants for the core layer."""

from __future__ import annotations

__all__ = ["VALID_ERROR_CODES"]

VALID_ERROR_CODES: frozenset[str] = frozenset({
    "VALIDATION_ERROR",
    "TOOL_NOT_FOUND",
    "TOOL_TIMEOUT",
    "TOOL_EXEC_ERROR",
    "PROVIDER_ERROR",
    "INTERNAL_ERROR",
})
