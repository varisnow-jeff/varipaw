import unittest

from varipaw.runtime.errors import (
    VALID_ERROR_CODES,
    internal_error,
    provider_error,
    tool_exec_error,
    tool_not_found,
    tool_timeout,
    validation_error,
)


class TestRuntimeErrors(unittest.TestCase):
    def test_standard_codes_set(self) -> None:
        self.assertIn("VALIDATION_ERROR", VALID_ERROR_CODES)
        self.assertIn("INTERNAL_ERROR", VALID_ERROR_CODES)

    def test_validation_error_factory(self) -> None:
        env = validation_error("bad input")
        self.assertEqual(env.code, "VALIDATION_ERROR")
        self.assertEqual(env.message, "bad input")
        self.assertFalse(env.retriable)

    def test_tool_related_error_factories(self) -> None:
        not_found = tool_not_found("search")
        timeout = tool_timeout("search", 1000)
        exec_err = tool_exec_error("search", "boom")
        self.assertEqual(not_found.code, "TOOL_NOT_FOUND")
        self.assertEqual(timeout.code, "TOOL_TIMEOUT")
        self.assertTrue(timeout.retriable)
        self.assertEqual(exec_err.code, "TOOL_EXEC_ERROR")

    def test_provider_and_internal_error_factories(self) -> None:
        p = provider_error("provider down")
        i = internal_error("oops")
        self.assertEqual(p.code, "PROVIDER_ERROR")
        self.assertTrue(p.retriable)
        self.assertEqual(i.code, "INTERNAL_ERROR")
        self.assertFalse(i.retriable)


if __name__ == "__main__":
    unittest.main()
