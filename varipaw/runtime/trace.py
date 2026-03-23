"""Step-level tracing for the VariPaw ReAct loop."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from varipaw.core.contracts import ContractParseError
from varipaw.core.validation import (
    deep_copy_mapping,
    frozen_setattr as _set,
    mapping_to_dict,
    redact,
    require_iso_datetime_str,
    require_keys,
    require_mapping,
    require_non_empty_str,
    require_non_negative_int,
    require_optional_non_empty_str,
    require_optional_non_negative_int,
    require_sequence_as_tuple,
    require_valid_error_code,
    utc_now_iso,
)

if TYPE_CHECKING:
    from varipaw.core.contracts import AgentStep

__all__ = [
    "generate_trace_id",
    "TraceStepRecord",
    "TraceRecord",
    "TraceCollector",
]


def generate_trace_id() -> str:
    return f"trace_{uuid4().hex}"


# ---------------------------------------------------------------------------
# TraceStepRecord
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TraceStepRecord:
    """Immutable ReAct step snapshot; keeps runtime tool names as-is."""

    step_index: int
    thought: str | None = None
    action_name: str | None = None
    action_args: dict[str, Any] | None = None
    observation_summary: str | None = None
    duration_ms: int = 0
    token_in: int | None = None
    token_out: int | None = None
    error_code: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        _set(self, "step_index", require_non_negative_int(self.step_index, "step_index"))
        _set(self, "thought", require_optional_non_empty_str(self.thought, "thought"))
        _set(self, "action_name", require_optional_non_empty_str(self.action_name, "action_name"))
        _set(self, "observation_summary", require_optional_non_empty_str(
            self.observation_summary, "observation_summary",
        ))
        _set(self, "duration_ms", require_non_negative_int(self.duration_ms, "duration_ms"))
        _set(self, "token_in", require_optional_non_negative_int(self.token_in, "token_in"))
        _set(self, "token_out", require_optional_non_negative_int(self.token_out, "token_out"))
        _set(self, "error_code", require_valid_error_code(self.error_code, "error_code"))
        _set(self, "created_at", require_iso_datetime_str(self.created_at, "created_at"))
        if self.action_args is not None:
            _set(self, "action_args", deep_copy_mapping(self.action_args, "action_args"))

    @classmethod
    def from_agent_step(
        cls,
        step: AgentStep,
        *,
        step_index: int | None = None,
    ) -> TraceStepRecord:
        """Create TraceStepRecord from AgentStep."""
        from varipaw.core.contracts import AgentStep as _AgentStep
        if not isinstance(step, _AgentStep):
            raise TypeError(f"expected AgentStep, got {type(step).__name__}")
        return cls(
            step_index=step_index if step_index is not None else step.step_index,
            thought=step.thought,
            action_name=step.action.name if step.action is not None else None,
            action_args=dict(step.action.arguments) if step.action is not None else None,
            observation_summary=step.observation,
            duration_ms=step.duration_ms,
            token_in=step.token_in,
            token_out=step.token_out,
            error_code=step.error_code,
            created_at=step.created_at,
        )

    def __repr__(self) -> str:
        return (
            f"TraceStepRecord(step={self.step_index}, "
            f"action={self.action_name!r}, "
            f"thought={redact(self.thought)}, "
            f"error_code={self.error_code!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "thought": self.thought,
            "action_name": self.action_name,
            "action_args": (
                deep_copy_mapping(self.action_args, "action_args")
                if self.action_args is not None else None
            ),
            "observation_summary": self.observation_summary,
            "duration_ms": self.duration_ms,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "error_code": self.error_code,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> TraceStepRecord:
        try:
            raw = require_mapping(raw, "TraceStepRecord raw")
            require_keys(raw, "step_index", "created_at")
            action_args_raw = raw.get("action_args")
            if action_args_raw is not None:
                action_args_raw = mapping_to_dict(action_args_raw, "action_args")
            return cls(
                step_index=raw["step_index"],
                thought=raw.get("thought"),
                action_name=raw.get("action_name"),
                action_args=action_args_raw,
                observation_summary=raw.get("observation_summary"),
                duration_ms=raw.get("duration_ms", 0),
                token_in=raw.get("token_in"),
                token_out=raw.get("token_out"),
                error_code=raw.get("error_code"),
                created_at=raw["created_at"],
            )
        except (ValueError, TypeError) as exc:
            raise ContractParseError("TraceStepRecord", str(exc)) from exc


# ---------------------------------------------------------------------------
# TraceRecord
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TraceRecord:
    """Immutable record containing every step of a single request trace."""

    trace_id: str
    session_id: str | None = None
    steps: tuple[TraceStepRecord, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _set(self, "trace_id", require_non_empty_str(self.trace_id, "trace_id"))
        _set(self, "session_id", require_optional_non_empty_str(self.session_id, "session_id"))

        if not isinstance(self.steps, Sequence) or isinstance(self.steps, (str, bytes)):
            raise ValueError("steps must be a sequence of TraceStepRecord")
        for i, s in enumerate(self.steps):
            if not isinstance(s, TraceStepRecord):
                raise ValueError(
                    f"steps[{i}] must be a TraceStepRecord, got {type(s).__name__}",
                )
        _set(self, "steps", tuple(self.steps))

    @property
    def total_duration_ms(self) -> int:
        return sum(s.duration_ms for s in self.steps)

    def __repr__(self) -> str:
        return (
            f"TraceRecord(trace_id={self.trace_id!r}, "
            f"session_id={self.session_id!r}, "
            f"steps=<{len(self.steps)}>)"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> TraceRecord:
        try:
            raw = require_mapping(raw, "TraceRecord raw")
            require_keys(raw, "trace_id")
            steps_raw = require_sequence_as_tuple(raw.get("steps", []), "steps")
            steps: list[TraceStepRecord] = []
            for i, item in enumerate(steps_raw):
                if not isinstance(item, Mapping):
                    raise ValueError(f"steps[{i}] must be a mapping")
                steps.append(TraceStepRecord.from_dict(item))
            return cls(
                trace_id=raw["trace_id"],
                session_id=raw.get("session_id"),
                steps=tuple(steps),
            )
        except (ValueError, TypeError) as exc:
            raise ContractParseError("TraceRecord", str(exc)) from exc


# ---------------------------------------------------------------------------
# TraceCollector (mutable builder)
# ---------------------------------------------------------------------------

class TraceCollector:
    """Mutable trace collector for a single run."""

    def __init__(self, trace_id: str, session_id: str | None = None) -> None:
        require_non_empty_str(trace_id, "trace_id")
        require_optional_non_empty_str(session_id, "session_id")
        self._trace_id = trace_id
        self._session_id = session_id
        self._steps: list[TraceStepRecord] = []

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def steps(self) -> tuple[TraceStepRecord, ...]:
        return tuple(self._steps)

    @property
    def step_count(self) -> int:
        return len(self._steps)

    @classmethod
    def start(cls, session_id: str | None = None) -> TraceCollector:
        return cls(trace_id=generate_trace_id(), session_id=session_id)

    def add_step(
        self,
        *,
        thought: str | None = None,
        action_name: str | None = None,
        action_args: dict[str, Any] | None = None,
        observation_summary: str | None = None,
        duration_ms: int = 0,
        token_in: int | None = None,
        token_out: int | None = None,
        error_code: str | None = None,
    ) -> TraceStepRecord:
        step = TraceStepRecord(
            step_index=len(self._steps),
            thought=thought,
            action_name=action_name,
            action_args=action_args,
            observation_summary=observation_summary,
            duration_ms=duration_ms,
            token_in=token_in,
            token_out=token_out,
            error_code=error_code,
        )
        self._steps.append(step)
        return step

    def add_from_agent_step(self, step: AgentStep) -> TraceStepRecord:
        """Append step with re-indexing."""
        record = TraceStepRecord.from_agent_step(
            step, step_index=len(self._steps),
        )
        self._steps.append(record)
        return record

    def clear(self) -> None:
        self._steps.clear()

    def to_record(self) -> TraceRecord:
        return TraceRecord(
            trace_id=self._trace_id,
            session_id=self._session_id,
            steps=tuple(self._steps),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.to_record().to_dict()

    def __repr__(self) -> str:
        return (
            f"TraceCollector(trace_id={self._trace_id!r}, "
            f"session_id={self._session_id!r}, "
            f"steps=<{len(self._steps)}>)"
        )
