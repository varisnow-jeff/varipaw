import json
import logging
import unittest
from unittest.mock import patch

from varipaw.runtime.logger import LogContext, log_event, setup_logger


class TestRuntimeLogger(unittest.TestCase):
    def test_log_context_to_dict(self) -> None:
        ctx = LogContext(trace_id="t1", step_index=1, duration_ms=10, error_code="INTERNAL_ERROR")
        payload = ctx.to_dict()
        self.assertEqual(payload["trace_id"], "t1")
        self.assertEqual(payload["step_index"], 1)
        self.assertEqual(payload["duration_ms"], 10)
        self.assertEqual(payload["error_code"], "INTERNAL_ERROR")

    def test_setup_logger(self) -> None:
        logger = setup_logger("varipaw.test.logger")
        self.assertEqual(logger.name, "varipaw.test.logger")

    def test_log_event_payload(self) -> None:
        logger = logging.getLogger("varipaw.test.log_event")
        logger.setLevel(logging.INFO)
        with patch.object(logger, "log") as mocked_log:
            log_event(
                logger,
                logging.INFO,
                "step_done",
                context=LogContext(trace_id="t1", step_index=2),
                extra={"k": "v"},
            )
        self.assertTrue(mocked_log.called)
        level, content = mocked_log.call_args.args
        self.assertEqual(level, logging.INFO)
        payload = json.loads(content)
        self.assertEqual(payload["event"], "step_done")
        self.assertEqual(payload["trace_id"], "t1")
        self.assertEqual(payload["step_index"], 2)
        self.assertEqual(payload["k"], "v")


if __name__ == "__main__":
    unittest.main()
