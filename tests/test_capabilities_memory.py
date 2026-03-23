import asyncio
import tempfile
import unittest

from varipaw.capabilities.memory.base import MemoryContext, MemoryTurn
from varipaw.capabilities.memory.chroma_store import ChromaMemoryStore
from varipaw.capabilities.memory.router import MemoryRouter
from varipaw.capabilities.memory.sqlite_store import SQLiteMemoryStore
from varipaw.core.contracts import AgentResponse, UserMessage


class TestCapabilitiesMemory(unittest.TestCase):
    def test_sqlite_store_save_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMemoryStore(db_path=f"{tmp}/memory.sqlite3")
            turn = MemoryTurn(
                session_id="s1",
                user_id="u1",
                user_text="hello",
                assistant_text="hi",
                trace_id="trace_1",
            )
            asyncio.run(store.save_turn(turn))
            recent = asyncio.run(store.list_recent_turns("s1", limit=3))
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0].assistant_text, "hi")

    def test_chroma_fallback_search(self) -> None:
        store = ChromaMemoryStore()
        asyncio.run(store.upsert_text(item_id="1", text="python unit test", metadata={"k": "v"}))
        hits = asyncio.run(store.search(query="python", limit=2))
        self.assertGreaterEqual(len(hits), 1)
        self.assertIn("python", hits[0].text.lower())

    def test_memory_router_context_and_remember(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            structured = SQLiteMemoryStore(db_path=f"{tmp}/memory.sqlite3")
            semantic = ChromaMemoryStore()
            router = MemoryRouter(structured=structured, semantic=semantic)
            user_message = UserMessage(session_id="s1", user_id="u1", text="I like python")
            response = AgentResponse(trace_id="trace_1", text="noted", steps=tuple())
            asyncio.run(router.remember_turn(user_message, response))
            context = asyncio.run(router.build_context(user_message))
            self.assertIsInstance(context, MemoryContext)
            self.assertGreaterEqual(len(context.recent_turns), 1)
            self.assertGreaterEqual(len(context.semantic_hits), 1)


if __name__ == "__main__":
    unittest.main()
