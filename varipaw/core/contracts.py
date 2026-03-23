"""Unified data contracts for the VariPaw agent pipeline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from varipaw.core.validation import (
    deep_copy_mapping,
    frozen_setattr as _set,
    mapping_to_dict,
    redact,
    require_bool,
    require_iso_datetime_str,
    require_keys,
    require_mapping,
    require_non_empty_str,
    require_non_negative_int,
    require_optional_non_empty_str,
    require_optional_non_negative_int,
    require_sequence_as_tuple,
    require_tool_name,
    require_valid_error_code,
    require_valid_error_code_required,
    utc_now_iso,
    validate_str,
)

__all__ = [
    "ErrorEnvelope",
    "ContractParseError",
    "UserMessage",
    "ToolCall",
    "ToolResult",
    "AgentStep",
    "AgentResponse",
]


class ContractParseError(ValueError):
    def __init__(self, contract_name: str, reason: str) -> None:
        self.contract_name = contract_name
        self.reason = reason
        super().__init__(f"Failed to parse {contract_name}: {reason}")


@dataclass(frozen=True, slots=True)
class ErrorEnvelope:
    code: str
    message: str
    retriable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _set(self, "code", require_valid_error_code_required(self.code, "code"))
        _set(self, "message", require_non_empty_str(self.message, "message"))
        require_bool(self.retriable, "retriable")
        _set(self, "details", deep_copy_mapping(self.details, "details"))

    def __repr__(self) -> str:
        return f"ErrorEnvelope(code={self.code!r}, message={redact(self.message)}, retriable={self.retriable})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retriable": self.retriable,
            "details": deep_copy_mapping(self.details, "details"),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ErrorEnvelope:
        try:
            raw = require_mapping(raw, "ErrorEnvelope raw")
            require_keys(raw, "code", "message")
            return cls(
                code=raw["code"],
                message=raw["message"],
                retriable=raw.get("retriable", False),
                details=mapping_to_dict(raw.get("details", {}), "details"),
            )
        except (ValueError, TypeError) as exc:
            raise ContractParseError("ErrorEnvelope", str(exc)) from exc


@dataclass(frozen=True, slots=True)
class UserMessage:
    """User input contract."""

    session_id: str
    user_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _set(self, "session_id", require_non_empty_str(self.session_id, "session_id"))
        _set(self, "user_id", require_non_empty_str(self.user_id, "user_id"))
        _set(self, "text", validate_str(self.text, "text", strip=False, allow_whitespace_only=True))
        _set(self, "metadata", deep_copy_mapping(self.metadata, "metadata"))

    def __repr__(self) -> str:
        return f"UserMessage(session_id={self.session_id!r}, user_id={self.user_id!r}, text={redact(self.text)})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "text": self.text,
            "metadata": deep_copy_mapping(self.metadata, "metadata"),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> UserMessage:
        try:
            raw = require_mapping(raw)
            require_keys(raw, "session_id", "user_id", "text")
            return cls(
                session_id=raw["session_id"],
                user_id=raw["user_id"],
                text=raw["text"],
                metadata=mapping_to_dict(raw.get("metadata", {}), "metadata"),
            )
        except (ValueError, TypeError) as exc:
            raise ContractParseError("UserMessage", str(exc)) from exc


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Tool invocation contract."""

    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _set(self, "call_id", require_non_empty_str(self.call_id, "call_id"))
        _set(self, "name", require_non_empty_str(self.name, "name"))
        _set(self, "arguments", deep_copy_mapping(self.arguments, "arguments"))

    def __repr__(self) -> str:
        return f"ToolCall(call_id={self.call_id!r}, name={self.name!r}, arguments={{...}})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "arguments": deep_copy_mapping(self.arguments, "arguments"),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ToolCall:
        try:
            raw = require_mapping(raw)
            require_keys(raw, "call_id", "name")
            return cls(
                call_id=raw["call_id"],
                name=raw["name"],
                arguments=mapping_to_dict(raw.get("arguments", {}), "arguments"),
            )
        except (ValueError, TypeError) as exc:
            raise ContractParseError("ToolCall", str(exc)) from exc


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    ok: bool
    data: dict[str, Any] | None = None
    error: ErrorEnvelope | None = None

    def __post_init__(self) -> None:
        _set(self, "call_id", require_non_empty_str(self.call_id, "call_id"))
        _set(self, "ok", require_bool(self.ok, "ok"))
        if self.error is not None and not isinstance(self.error, ErrorEnvelope):
            raise ValueError("error must be an ErrorEnvelope or None")
        if self.ok:
            if self.data is None:
                raise ValueError("ok=True requires data (pass {} for empty)")
            _set(self, "data", deep_copy_mapping(self.data, "data"))
            if self.error is not None:
                raise ValueError("ok=True must have error=None")
        else:
            if self.error is None:
                raise ValueError("ok=False requires error")
            if self.data is not None:
                raise ValueError("ok=False must have data=None")

    def __repr__(self) -> str:
        if self.ok:
            return f"ToolResult(call_id={self.call_id!r}, ok=True, data_keys={list(self.data.keys())!r})"
        return f"ToolResult(call_id={self.call_id!r}, ok=False, error_code={self.error.code!r})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "ok": self.ok,
            "data": deep_copy_mapping(self.data, "data") if self.data is not None else None,
            "error": self.error.to_dict() if self.error is not None else None,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ToolResult:
        try:
            raw = require_mapping(raw)
            require_keys(raw, "call_id", "ok")
            ok_val = require_bool(raw["ok"], "ok")
            data_raw = raw.get("data")
            if data_raw is not None:
                data_raw = mapping_to_dict(data_raw, "data")
            error_raw = raw.get("error")
            error_obj = ErrorEnvelope.from_dict(require_mapping(error_raw, "error")) if error_raw is not None else None
            return cls(call_id=raw["call_id"], ok=ok_val, data=data_raw, error=error_obj)
        except (ValueError, TypeError) as exc:
            raise ContractParseError("ToolResult", str(exc)) from exc


@dataclass(frozen=True, slots=True)
class AgentStep:
    trace_id: str
    session_id: str
    step_index: int
    thought: str | None = None
    action: ToolCall | None = None
    observation: str | None = None
    duration_ms: int = 0
    token_in: int | None = None
    token_out: int | None = None
    error_code: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        _set(self, "trace_id", require_non_empty_str(self.trace_id, "trace_id"))
        _set(self, "session_id", require_non_empty_str(self.session_id, "session_id"))
        _set(self, "step_index", require_non_negative_int(self.step_index, "step_index"))
        _set(self, "duration_ms", require_non_negative_int(self.duration_ms, "duration_ms"))
        _set(self, "thought", require_optional_non_empty_str(self.thought, "thought"))
        _set(self, "observation", require_optional_non_empty_str(self.observation, "observation"))
        _set(self, "token_in", require_optional_non_negative_int(self.token_in, "token_in"))
        _set(self, "token_out", require_optional_non_negative_int(self.token_out, "token_out"))
        _set(self, "error_code", require_valid_error_code(self.error_code, "error_code"))
        _set(self, "created_at", require_iso_datetime_str(self.created_at, "created_at"))
        if self.action is not None and not isinstance(self.action, ToolCall):
            raise ValueError("action must be a ToolCall or None")

    def __repr__(self) -> str:
        return (
            f"AgentStep(trace={self.trace_id!r}, step={self.step_index}, "
            f"thought={redact(self.thought)}, action={self.action!r}, "
            f"error_code={self.error_code!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "step_index": self.step_index,
            "thought": self.thought,
            "action": self.action.to_dict() if self.action is not None else None,
            "observation": self.observation,
            "duration_ms": self.duration_ms,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "error_code": self.error_code,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AgentStep:
        try:
            raw = require_mapping(raw)
            require_keys(raw, "trace_id", "session_id", "step_index", "created_at")
            action_raw = raw.get("action")
            action_obj = ToolCall.from_dict(require_mapping(action_raw, "action")) if action_raw is not None else None
            return cls(
                trace_id=raw["trace_id"],
                session_id=raw["session_id"],
                step_index=raw["step_index"],
                thought=raw.get("thought"),
                action=action_obj,
                observation=raw.get("observation"),
                duration_ms=raw.get("duration_ms", 0),
                token_in=raw.get("token_in"),
                token_out=raw.get("token_out"),
                error_code=raw.get("error_code"),
                created_at=raw["created_at"],
            )
        except (ValueError, TypeError) as exc:
            raise ContractParseError("AgentStep", str(exc)) from exc


@dataclass(frozen=True, slots=True)
class AgentResponse:
    """Final user-facing response; ``text`` must be non-empty."""
    trace_id: str
    text: str
    steps: tuple[AgentStep, ...] = field(default_factory=tuple)
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        _set(self, "trace_id", require_non_empty_str(self.trace_id, "trace_id"))
        _set(self, "text", require_non_empty_str(self.text, "text"))
        _set(self, "created_at", require_iso_datetime_str(self.created_at, "created_at"))
        if not isinstance(self.steps, Sequence) or isinstance(self.steps, (str, bytes)):
            raise ValueError("steps must be a sequence of AgentStep")
        for i, step in enumerate(self.steps):
            if not isinstance(step, AgentStep):
                raise ValueError(f"steps[{i}] must be an AgentStep, got {type(step).__name__}")
        _set(self, "steps", tuple(self.steps))

    def __repr__(self) -> str:
        return f"AgentResponse(trace_id={self.trace_id!r}, text={redact(self.text)}, steps=<{len(self.steps)}>)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "text": self.text,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AgentResponse:
        try:
            raw = require_mapping(raw)
            require_keys(raw, "trace_id", "text", "created_at")
            steps_raw = require_sequence_as_tuple(raw.get("steps", []), "steps")
            steps = []
            for i, item in enumerate(steps_raw):
                if not isinstance(item, Mapping):
                    raise ValueError(f"steps[{i}] must be a mapping")
                steps.append(AgentStep.from_dict(item))
            return cls(
                trace_id=raw["trace_id"],
                text=raw["text"],
                steps=tuple(steps),
                created_at=raw["created_at"],
            )
        except (ValueError, TypeError) as exc:
            raise ContractParseError("AgentResponse", str(exc)) from exc
