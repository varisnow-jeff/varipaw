from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from varipaw.capabilities.memory.base import SemanticHit, SemanticMemoryStore
from varipaw.core.validation import (
    freeze_metadata,
    frozen_setattr,
    require_non_empty_str,
    require_positive_int,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _FallbackItem:
    item_id: str
    text: str
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        frozen_setattr(
            self,
            "item_id",
            require_non_empty_str(self.item_id, "item_id"),
        )
        frozen_setattr(
            self,
            "text",
            require_non_empty_str(self.text, "text"),
        )
        frozen_setattr(
            self,
            "metadata",
            freeze_metadata(self.metadata, "metadata"),
        )


class ChromaMemoryStore(SemanticMemoryStore):
    def __init__(
        self,
        collection_name: str = "varipaw_memory",
        persist_directory: str = ".varipaw/state/chroma_data",
    ) -> None:
        self._collection_name = require_non_empty_str(
            collection_name,
            "collection_name",
        )
        self._persist_directory = persist_directory
        self._fallback_items: list[_FallbackItem] = []
        self._collection: Any | None = None
        self._lock = threading.Lock()
        self._init_backend()


    @property
    def is_chroma_available(self) -> bool:
        return self._collection is not None

    async def upsert_text(
        self,
        *,
        item_id: str,
        text: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        item_id = require_non_empty_str(item_id, "item_id")
        text = require_non_empty_str(text, "text")
        normalized_metadata = freeze_metadata(metadata or {}, "metadata")

        await asyncio.to_thread(
            self._upsert_sync,
            item_id,
            text,
            normalized_metadata,
        )

    async def search(
        self,
        *,
        query: str,
        limit: int = 3,
    ) -> list[SemanticHit]:
        query = require_non_empty_str(query, "query")
        limit = require_positive_int(limit, "limit")
        return await asyncio.to_thread(self._search_sync, query, limit)

    def _init_backend(self) -> None:
        try:
            import chromadb
        except ModuleNotFoundError:
            logger.info(
                "chromadb not installed; ChromaMemoryStore will use fallback matcher"
            )
            self._collection = None
            return

        try:
            client = chromadb.PersistentClient(path=self._persist_directory)
            self._collection = client.get_or_create_collection(
                name=self._collection_name
            )
        except Exception as exc:
            logger.warning(
                "Failed to initialize Chroma collection (%s); "
                "falling back to in-memory matcher",
                exc,
            )
            self._collection = None


    def _upsert_sync(
        self,
        item_id: str,
        text: str,
        metadata: Mapping[str, Any],
    ) -> None:
        collection = self._collection
        if collection is not None:
            collection.upsert(
                ids=[item_id],
                documents=[text],
                metadatas=[dict(metadata)],
            )
            return

        with self._lock:
            self._upsert_fallback(item_id, text, metadata)

    def _upsert_fallback(
        self,
        item_id: str,
        text: str,
        metadata: Mapping[str, Any],
    ) -> None:
        for i, item in enumerate(self._fallback_items):
            if item.item_id == item_id:
                self._fallback_items[i] = _FallbackItem(
                    item_id=item_id,
                    text=text,
                    metadata=metadata,
                )
                return

        self._fallback_items.append(
            _FallbackItem(
                item_id=item_id,
                text=text,
                metadata=metadata,
            )
        )

    def _search_sync(self, query: str, limit: int) -> list[SemanticHit]:
        collection = self._collection
        if collection is not None:
            return self._search_chroma(collection, query, limit)

        with self._lock:
            return self._search_fallback(query, limit)

    def _search_chroma(
        self,
        collection: Any,
        query: str,
        limit: int,
    ) -> list[SemanticHit]:
        result = collection.query(
            query_texts=[query],
            n_results=limit,
        )

        documents_raw = result.get("documents", [[]])
        distances_raw = result.get("distances", [[]])
        metadatas_raw = result.get("metadatas", [[]])

        documents = documents_raw[0] if documents_raw else []
        distances = distances_raw[0] if distances_raw else []
        metadatas = metadatas_raw[0] if metadatas_raw else []

        hits: list[SemanticHit] = []
        for i, doc in enumerate(documents):
            dist = distances[i] if i < len(distances) else 0.0
            meta = metadatas[i] if i < len(metadatas) else {}

            hits.append(
                SemanticHit(
                    text=str(doc),
                    score=-float(dist),
                    metadata=meta if isinstance(meta, dict) else {},
                )
            )

        return hits

    def _search_fallback(self, query: str, limit: int) -> list[SemanticHit]:
        q = query.strip().lower()
        q_tokens = set(q.split())

        scored: list[SemanticHit] = []
        for item in self._fallback_items:
            text = item.text.strip()
            lowered = text.lower()

            if q in lowered:
                score = 1.0
            else:
                text_tokens = set(lowered.split())
                overlap = len(q_tokens & text_tokens)
                score = overlap / max(len(q_tokens), 1)

            if score > 0:
                scored.append(
                    SemanticHit(
                        text=text,
                        score=score,
                        metadata=item.metadata,
                    )
                )

        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:limit]

    def __repr__(self) -> str:
        backend = "chroma" if self._collection is not None else "fallback"
        return (
            f"ChromaMemoryStore(collection_name={self._collection_name!r}, "
            f"backend={backend!r})"
        )
