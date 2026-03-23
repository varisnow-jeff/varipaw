"""Reusable validation helpers for contract construction and parsing."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from varipaw.core.constants import VALID_ERROR_CODES

REPR_MAX_LEN = 40
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def frozen_setattr(obj: object, name: str, value: Any) -> None:
    object.__setattr__(obj, name, value)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


# --- String ----------------------------------------------------------------

def validate_str(
    value: object,
    field_name: str,
    *,
    strip: bool = True,
    allow_whitespace_only: bool = False,
) -> str:
    """Validate string with strip and whitespace policy."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if len(value) == 0:
        raise ValueError(f"{field_name} must be a non-empty string")
    if value.strip() == "":
        if allow_whitespace_only:
            return value
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip() if strip else value


def require_non_empty_str(value: object, field_name: str) -> str:
    return validate_str(value, field_name, strip=True)


def require_optional_non_empty_str(value: object, field_name: str) -> str | None:
    """Use None for absence; empty strings are invalid."""
    if value is None:
        return None
    return require_non_empty_str(value, field_name)


# --- Numeric ---------------------------------------------------------------

def require_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative int")
    return value


def require_optional_non_negative_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return require_non_negative_int(value, field_name)


# --- Bool ------------------------------------------------------------------

def require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a bool")
    return value


# --- Type guard ------------------------------------------------------------

def require_type(value: object, expected: type, field_name: str) -> Any:
    if not isinstance(value, expected):
        raise ValueError(f"{field_name} must be {expected.__name__}, got {type(value).__name__}")
    return value


# --- Mapping / Sequence ----------------------------------------------------

def require_mapping(value: object, field_name: str = "data") -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return value


def mapping_to_dict(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return dict(value)


def deep_copy_mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    try:
        return copy.deepcopy(dict(value))
    except TypeError as exc:
        raise ValueError(f"{field_name} contains non-copyable values: {exc}") from exc


def require_sequence_as_tuple(value: object, field_name: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence (list or tuple)")
    return tuple(value)


# --- Keys ------------------------------------------------------------------

def require_keys(data: Mapping[str, Any], *keys: str) -> None:
    for key in keys:
        if key not in data:
            raise ValueError(f"missing required field: {key}")


# --- Error code ------------------------------------------------------------

def require_valid_error_code(code: str | None, field_name: str) -> str | None:
    if code is None:
        return None
    code = require_non_empty_str(code, field_name)
    if code not in VALID_ERROR_CODES:
        raise ValueError(f"unknown error code {code!r}; valid codes: {sorted(VALID_ERROR_CODES)}")
    return code


def require_valid_error_code_required(code: str, field_name: str) -> str:
    code = require_non_empty_str(code, field_name)
    if code not in VALID_ERROR_CODES:
        raise ValueError(f"unknown error code {code!r}; valid codes: {sorted(VALID_ERROR_CODES)}")
    return code


# --- Tool name -------------------------------------------------------------

def require_tool_name(name: str, field_name: str = "tool name") -> str:
    name = require_non_empty_str(name, field_name)
    if not _TOOL_NAME_RE.match(name):
        raise ValueError(f"Invalid {field_name}: {name!r} (must match {_TOOL_NAME_RE.pattern})")
    return name


# --- Datetime --------------------------------------------------------------

def require_iso_datetime_str(value: object, field_name: str) -> str:
    s = require_non_empty_str(value, field_name)
    normalized = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO-8601 datetime string, got {s!r}") from exc
    return normalized


# --- Repr ------------------------------------------------------------------

def redact(value: str | None, max_len: int = REPR_MAX_LEN) -> str:
    if value is None:
        return "None"
    if len(value) <= max_len:
        return repr(value)
    return repr(value[:max_len] + "...")

# --- ---

import math
from collections.abc import Iterable
from dataclasses import fields
from numbers import Real
from types import MappingProxyType
from typing import TypeVar,cast

T = TypeVar("T")


def require_positive_int(value: object, field_name: str) -> int:
    """Require int > 0."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive int")
    return value


def require_positive_float(value: object, field_name: str) -> float:
    """Require finite float > 0."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if normalized <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return normalized


def require_non_negative_float(value: object, field_name: str) -> float:
    """Require finite float >= 0."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if normalized < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return normalized


def require_str_frozenset(value: object, field_name: str) -> frozenset[str]:
    """Normalize iterable of strings to frozenset."""
    if isinstance(value, frozenset):
        items = value
    elif isinstance(value, (str, bytes)):
        raise ValueError(
            f"{field_name} must be an iterable of strings, not a single string"
        )
    elif not isinstance(value, Iterable):
        raise ValueError(f"{field_name} must be an iterable of strings")
    else:
        items = list(value)
        if not all(isinstance(item, str) for item in items):
            raise ValueError(f"{field_name} must contain only strings")
        items = frozenset(items)

    if isinstance(value, frozenset) and not all(isinstance(item, str) for item in items):
        raise ValueError(f"{field_name} must contain only strings")
    return items


def reject_unknown_keys(
    value: Mapping[str, Any],
    *,
    allowed_keys: frozenset[str],
    field_name: str,
) -> None:
    """Raise on unknown keys."""
    unknown = sorted(k for k in value if k not in allowed_keys)
    if unknown:
        raise ValueError(
            f"{field_name} has unknown keys: {', '.join(unknown)}"
        )


def dataclass_field_names(cls: type) -> frozenset[str]:
    """Return dataclass field names."""
    return frozenset(f.name for f in fields(cls))


def build_dataclass_from_mapping(
    cls: type[T],
    raw: object,
    *,
    field_name: str,
) -> T:
    """Build dataclass from validated mapping."""
    mapping = require_mapping(raw, field_name)
    reject_unknown_keys(
        mapping,
        allowed_keys=dataclass_field_names(cls),
        field_name=field_name,
    )
    return cls(**mapping)


def require_tool_overrides_mapping(
    value: object,
    field_name: str,
) -> MappingProxyType[str, Any]:
    """Validate and freeze tool overrides."""
    mapping = require_mapping(value, field_name)
    for key in mapping:
        if not isinstance(key, str) or not key:
            raise ValueError(f"{field_name} keys must be non-empty strings")
    return MappingProxyType(dict(mapping))

def require_frozenset_of_str(value: object, field_name: str) -> frozenset[str]:
    """Require frozenset[str]."""
    if not isinstance(value, frozenset):
        raise TypeError(f"{field_name} must be a frozenset")
    if not all(isinstance(item, str) for item in value):
        raise TypeError(f"{field_name} must contain only strings")
    return value


def require_non_empty_str_key(key: object, context: str) -> str:
    """Require non-empty string key."""
    if not isinstance(key, str):
        raise TypeError(f"{context} keys must be str")
    if not key:
        raise ValueError(f"{context} keys must be non-empty strings")
    return key

# --- Finite float ----------------------------------------------------------

def require_finite_float(value: object, field_name: str) -> float:
    """Require finite real number."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


# --- Tuple of typed instances ----------------------------------------------

def require_tuple_of(
    value: object,
    *,
    field_name: str,
    item_type: type[T],
) -> tuple[T, ...]:
    """Normalize iterable to tuple[item_type, ...]."""
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{field_name} must be an iterable, not a string")
    if isinstance(value, tuple):
        items = value
    elif isinstance(value, Iterable):
        items = tuple(value)
    else:
        raise TypeError(f"{field_name} must be an iterable")

    for idx, item in enumerate(items):
        if not isinstance(item, item_type):
            raise TypeError(
                f"{field_name}[{idx}] must be {item_type.__name__}, "
                f"got {type(item).__name__}"
            )
    return cast(tuple[T, ...], items)


def require_tuple_of_non_empty_str(
    value: object,
    *,
    field_name: str,
) -> tuple[str, ...]:
    """Normalize iterable to tuple[str, ...]."""
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{field_name} must be an iterable of strings, not a string")
    if isinstance(value, tuple):
        items = value
    elif isinstance(value, Iterable):
        items = tuple(value)
    else:
        raise TypeError(f"{field_name} must be an iterable of strings")

    return tuple(
        require_non_empty_str(item, f"{field_name}[{idx}]")
        for idx, item in enumerate(items)
    )


# --- Deep freeze -----------------------------------------------------------

def deep_freeze(value: object) -> object:
    """Recursively freeze containers."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(deep_freeze(v) for v in value)
    return value


def freeze_metadata(value: object, field_name: str) -> Mapping[str, Any]:
    """Validate and freeze mapping."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    frozen = deep_freeze(value)
    return cast(Mapping[str, Any], frozen)
