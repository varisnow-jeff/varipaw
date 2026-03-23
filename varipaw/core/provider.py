from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from varipaw.core.contracts import ToolCall
from varipaw.core.validation import (
    deep_copy_mapping,
    frozen_setattr as _set,
    redact,
    require_non_empty_str,
    require_optional_non_empty_str,
    require_optional_non_negative_int,
)
from varipaw.runtime.errors import ErrorEnvelope

__all__ = [
    "LLMResponse",
    "SystemMessage",
    "HumanMessage",
    "AssistantMessage",
    "ToolResultMessage",
    "Message",
    "BaseProvider",
    "ProviderError",
]


class ProviderError(Exception):
    def __init__(self, envelope: ErrorEnvelope) -> None:
        self.envelope = envelope
        super().__init__(envelope.message)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    thought: str | None = None
    text: str | None = None
    tool_call: ToolCall | None = None
    token_in: int | None = None
    token_out: int | None = None
    duration_ms: int | None = None
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _set(self, "thought", require_optional_non_empty_str(self.thought, "thought"))
        _set(self, "text", require_optional_non_empty_str(self.text, "text"))
        _set(self, "token_in", require_optional_non_negative_int(self.token_in, "token_in"))
        _set(self, "token_out", require_optional_non_negative_int(self.token_out, "token_out"))
        _set(self, "duration_ms", require_optional_non_negative_int(self.duration_ms, "duration_ms"))
        _set(self, "finish_reason", require_optional_non_empty_str(self.finish_reason, "finish_reason"))
        _set(self, "raw", deep_copy_mapping(self.raw, "raw"))

        if self.tool_call is not None and not isinstance(self.tool_call, ToolCall):
            raise ValueError("tool_call must be a ToolCall or None")
        if self.text is not None and self.tool_call is not None:
            raise ValueError("LLMResponse must have either text or tool_call, not both")
        if self.text is None and self.tool_call is None:
            raise ValueError("LLMResponse must have at least one of text or tool_call")

    @property
    def is_tool_call(self) -> bool:
        return self.tool_call is not None

    @property
    def is_text(self) -> bool:
        return self.text is not None

    def __repr__(self) -> str:
        parts = []
        if self.is_tool_call:
            parts.append(f"tool_call={self.tool_call!r}")
        else:
            parts.append(f"text={redact(self.text, max_len=60)}")
        if self.finish_reason:
            parts.append(f"finish_reason={self.finish_reason!r}")
        if self.duration_ms is not None:
            parts.append(f"duration_ms={self.duration_ms}")
        return f"LLMResponse({', '.join(parts)})"


@dataclass(frozen=True, slots=True)
class SystemMessage:
    content: str

    def __post_init__(self) -> None:
        _set(self, "content", require_non_empty_str(self.content, "content"))

    def to_dict(self) -> dict[str, str]:
        return {"role": "system", "content": self.content}


@dataclass(frozen=True, slots=True)
class HumanMessage:
    content: str

    def __post_init__(self) -> None:
        _set(self, "content", require_non_empty_str(self.content, "content"))

    def to_dict(self) -> dict[str, str]:
        return {"role": "user", "content": self.content}


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    content: str
    tool_calls: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise TypeError(f"content must be str, got {type(self.content).__name__}")

    def to_dict(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return msg


@dataclass(frozen=True, slots=True)
class ToolResultMessage:
    tool_name: str
    call_id: str
    content: str

    def __post_init__(self) -> None:
        _set(self, "tool_name", require_non_empty_str(self.tool_name, "tool_name"))
        _set(self, "call_id", require_non_empty_str(self.call_id, "call_id"))
        _set(self, "content", require_non_empty_str(self.content, "content"))

    def to_dict(self) -> dict[str, str]:
        return {
            "role": "tool",
            "tool_call_id": self.call_id,
            "name": self.tool_name,
            "content": self.content,
        }


Message = SystemMessage | HumanMessage | AssistantMessage | ToolResultMessage


class BaseProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: Sequence[Message],
        tool_schemas: Sequence[dict[str, Any]],
    ) -> LLMResponse:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
