from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, cast

from varipaw.core.contracts import AgentResponse, UserMessage
from varipaw.core.validation import (
    freeze_metadata,
    frozen_setattr,
    require_finite_float,
    require_iso_datetime_str,
    require_non_empty_str,
    require_tuple_of,
    utc_now_iso,
)


def _require_tuple_of_str(
    value: object,
    *,
    field_name: str,
) -> tuple[str, ...]:
    if isinstance(value, tuple):
        items = value
    else:
        if isinstance(value, (str, bytes)):
            raise TypeError(f"{field_name} must be an iterable of strings, not a string")
        if not isinstance(value, Iterable):
            raise TypeError(f"{field_name} must be an iterable of strings")
        items = tuple(value)

    for idx, item in enumerate(items):
        if not isinstance(item, str):
            raise TypeError(
                f"{field_name}[{idx}] must be str, got {type(item).__name__}"
            )

    return cast(tuple[str, ...], items)


@dataclass(frozen=True, slots=True)
class MemoryTurn:
    session_id: str
    user_id: str
    user_text: str
    assistant_text: str
    trace_id: str
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        frozen_setattr(
            self,
            "session_id",
            require_non_empty_str(self.session_id, "session_id"),
        )
        frozen_setattr(
            self,
            "user_id",
            require_non_empty_str(self.user_id, "user_id"),
        )
        frozen_setattr(
            self,
            "user_text",
            require_non_empty_str(self.user_text, "user_text"),
        )
        frozen_setattr(
            self,
            "assistant_text",
            require_non_empty_str(self.assistant_text, "assistant_text"),
        )
        frozen_setattr(
            self,
            "trace_id",
            require_non_empty_str(self.trace_id, "trace_id"),
        )
        frozen_setattr(
            self,
            "created_at",
            require_iso_datetime_str(self.created_at, "created_at"),
        )

    @classmethod
    def from_exchange(cls, msg: UserMessage, resp: AgentResponse) -> MemoryTurn:
        return cls(
            session_id=msg.session_id,
            user_id=msg.user_id,
            user_text=msg.text,
            assistant_text=resp.text,
            trace_id=resp.trace_id,
        )


@dataclass(frozen=True, slots=True)
class SemanticHit:
    text: str
    score: float
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        frozen_setattr(self, "text", require_non_empty_str(self.text, "text"))
        frozen_setattr(self, "score", require_finite_float(self.score, "score"))
        frozen_setattr(self, "metadata", freeze_metadata(self.metadata, "metadata"))


@dataclass(frozen=True, slots=True)
class MemoryContext:
    recent_turns: tuple[MemoryTurn, ...] = field(default_factory=tuple)
    semantic_hits: tuple[SemanticHit, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        frozen_setattr(
            self,
            "recent_turns",
            require_tuple_of(
                self.recent_turns,
                field_name="recent_turns",
                item_type=MemoryTurn,
            ),
        )
        frozen_setattr(
            self,
            "semantic_hits",
            require_tuple_of(
                self.semantic_hits,
                field_name="semantic_hits",
                item_type=SemanticHit,
            ),
        )
        frozen_setattr(
            self,
            "notes",
            _require_tuple_of_str(
                self.notes,
                field_name="notes",
            ),
        )

    def is_empty(self) -> bool:
        return not (self.recent_turns or self.semantic_hits or self.notes)

    @classmethod
    def empty(cls) -> MemoryContext:
        return cls()


class StructuredMemoryStore(ABC):
    @abstractmethod
    async def save_turn(self, turn: MemoryTurn) -> None:
        ...

    @abstractmethod
    async def list_recent_turns(
        self,
        session_id: str,
        limit: int = 5,
    ) -> list[MemoryTurn]:
        ...


class SemanticMemoryStore(ABC):
    @abstractmethod
    async def upsert_text(
        self,
        *,
        item_id: str,
        text: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        ...

    @abstractmethod
    async def search(
        self,
        *,
        query: str,
        limit: int = 3,
    ) -> list[SemanticHit]:
        ...


class MemoryProvider(ABC):
    @abstractmethod
    async def build_context(self, user_message: UserMessage) -> MemoryContext:
        ...

    @abstractmethod
    async def remember_turn(
        self,
        user_message: UserMessage,
        response: AgentResponse,
    ) -> None:
        ...
