import unittest

from varipaw.runtime.trace import TraceCollector, TraceRecord, TraceStepRecord, generate_trace_id


class TestRuntimeTrace(unittest.TestCase):
    def test_generate_trace_id_format(self) -> None:
        trace_id = generate_trace_id()
        self.assertTrue(trace_id.startswith("trace_"))
        self.assertGreater(len(trace_id), 10)

    def test_trace_step_roundtrip(self) -> None:
        step = TraceStepRecord(step_index=0, duration_ms=10, action_name="search")
        parsed = TraceStepRecord.from_dict(step.to_dict())
        self.assertEqual(parsed.step_index, 0)
        self.assertEqual(parsed.duration_ms, 10)
        self.assertEqual(parsed.action_name, "search")

    def test_trace_collector_build_record(self) -> None:
        collector = TraceCollector.start(session_id="s1")
        collector.add_step(thought="t", duration_ms=5)
        record = collector.to_record()
        self.assertIsInstance(record, TraceRecord)
        self.assertEqual(record.session_id, "s1")
        self.assertEqual(len(record.steps), 1)
        self.assertEqual(record.steps[0].step_index, 0)

    def test_trace_record_steps_type_validation(self) -> None:
        with self.assertRaises(ValueError):
            TraceRecord(trace_id="trace_1", steps=[object()])


if __name__ == "__main__":
    unittest.main()
