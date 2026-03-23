import unittest

from varipaw.core.constants import VALID_ERROR_CODES


class TestCoreConstants(unittest.TestCase):
    def test_valid_error_codes_exact(self) -> None:
        self.assertEqual(
            VALID_ERROR_CODES,
            frozenset(
                {
                    "VALIDATION_ERROR",
                    "TOOL_NOT_FOUND",
                    "TOOL_TIMEOUT",
                    "TOOL_EXEC_ERROR",
                    "PROVIDER_ERROR",
                    "INTERNAL_ERROR",
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
