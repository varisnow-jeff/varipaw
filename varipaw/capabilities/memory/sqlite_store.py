from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from varipaw.capabilities.memory.base import MemoryTurn, StructuredMemoryStore
from varipaw.core.validation import require_non_empty_str, require_positive_int


class SQLiteMemoryStore(StructuredMemoryStore):
    def __init__(self, db_path: str | Path = "varipaw_memory.sqlite3") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    async def save_turn(self, turn: MemoryTurn) -> None:
        if not isinstance(turn, MemoryTurn):
            raise TypeError("turn must be a MemoryTurn")
        await asyncio.to_thread(self._save_turn_sync, turn)

    async def list_recent_turns(
        self,
        session_id: str,
        limit: int = 5,
    ) -> list[MemoryTurn]:
        session_id = require_non_empty_str(session_id, "session_id")
        limit = require_positive_int(limit, "limit")
        return await asyncio.to_thread(
            self._list_recent_turns_sync,
            session_id,
            limit,
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_turns_session_id_desc
                ON memory_turns(session_id, id DESC)
                """
            )

    def _save_turn_sync(self, turn: MemoryTurn) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_turns (
                    session_id,
                    user_id,
                    user_text,
                    assistant_text,
                    trace_id,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    turn.session_id,
                    turn.user_id,
                    turn.user_text,
                    turn.assistant_text,
                    turn.trace_id,
                    turn.created_at,
                ),
            )

    def _list_recent_turns_sync(
        self,
        session_id: str,
        limit: int,
    ) -> list[MemoryTurn]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    session_id,
                    user_id,
                    user_text,
                    assistant_text,
                    trace_id,
                    created_at
                FROM memory_turns
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

        return [
            MemoryTurn(
                session_id=row["session_id"],
                user_id=row["user_id"],
                user_text=row["user_text"],
                assistant_text=row["assistant_text"],
                trace_id=row["trace_id"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def __repr__(self) -> str:
        return f"SQLiteMemoryStore(db_path={str(self._db_path)!r})"
