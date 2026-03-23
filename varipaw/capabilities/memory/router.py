from __future__ import annotations

from dataclasses import dataclass

from varipaw.capabilities.memory.base import (
    MemoryContext,
    MemoryProvider,
    MemoryTurn,
    SemanticMemoryStore,
    StructuredMemoryStore,
)
from varipaw.capabilities.memory.chroma_store import ChromaMemoryStore
from varipaw.capabilities.memory.sqlite_store import SQLiteMemoryStore
from varipaw.core.contracts import AgentResponse, UserMessage
from varipaw.core.validation import (
    frozen_setattr,
    require_non_empty_str,
    require_positive_int,
)


@dataclass(frozen=True, slots=True)
class MemoryRouterConfig:
    recent_turn_limit: int = 4
    semantic_top_k: int = 3

    def __post_init__(self) -> None:
        frozen_setattr(
            self,
            "recent_turn_limit",
            require_positive_int(self.recent_turn_limit, "recent_turn_limit"),
        )
        frozen_setattr(
            self,
            "semantic_top_k",
            require_positive_int(self.semantic_top_k, "semantic_top_k"),
        )


class MemoryRouter(MemoryProvider):
    def __init__(
        self,
        *,
        structured: StructuredMemoryStore,
        semantic: SemanticMemoryStore,
        config: MemoryRouterConfig | None = None,
    ) -> None:
        self._structured = structured
        self._semantic = semantic
        self._config = config or MemoryRouterConfig()

    async def remember_turn(
        self,
        user_message: UserMessage,
        response: AgentResponse,
    ) -> None:
        turn = MemoryTurn.from_exchange(user_message, response)
        await self._structured.save_turn(turn)

        memory_text = f"user: {user_message.text}\nassistant: {response.text}"
        item_id = f"{response.trace_id}:{user_message.session_id}"
        metadata = {
            "session_id": user_message.session_id,
            "user_id": user_message.user_id,
            "trace_id": response.trace_id,
        }
        await self._semantic.upsert_text(
            item_id=item_id,
            text=memory_text,
            metadata=metadata,
        )

    async def build_context(self, user_message: UserMessage) -> MemoryContext:
        require_non_empty_str(user_message.session_id, "session_id")
        require_non_empty_str(user_message.text, "text")

        recent = await self._structured.list_recent_turns(
            user_message.session_id,
            limit=self._config.recent_turn_limit,
        )
        semantic = await self._semantic.search(
            query=user_message.text,
            limit=self._config.semantic_top_k,
        )

        return MemoryContext(
            recent_turns=tuple(recent),
            semantic_hits=tuple(semantic),
        )


def build_default_memory_router(
    db_path: str = ".varipaw/state/varipaw_memory.sqlite3",
) -> MemoryRouter:
    return MemoryRouter(
        structured=SQLiteMemoryStore(db_path=db_path),
        semantic=ChromaMemoryStore(),
    )
