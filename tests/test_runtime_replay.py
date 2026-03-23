import unittest

from varipaw.core.contracts import AgentResponse
from varipaw.runtime.replay import ReplayStore, response_to_trace_record


class TestRuntimeReplay(unittest.TestCase):
    def test_response_to_trace_record(self) -> None:
        response = AgentResponse(trace_id="trace_1", text="ok", steps=tuple())
        record = response_to_trace_record(response, session_id="s1")
        self.assertEqual(record.trace_id, "trace_1")
        self.assertEqual(record.session_id, "s1")
        self.assertEqual(len(record.steps), 0)

    def test_replay_store(self) -> None:
        store = ReplayStore()
        response = AgentResponse(trace_id="trace_1", text="ok", steps=tuple())
        store.add(response)
        got = store.get("trace_1")
        self.assertIsNotNone(got)
        self.assertEqual(got.text, "ok")
        snap = store.snapshot("trace_1")
        self.assertEqual(snap.step_count, 0)
        self.assertEqual(store.list_trace_ids(), ["trace_1"])


if __name__ == "__main__":
    unittest.main()
