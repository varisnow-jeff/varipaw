import unittest

from varipaw.core.validation import (
    mapping_to_dict,
    require_iso_datetime_str,
    require_non_empty_str,
    require_non_negative_int,
)


class TestCoreValidation(unittest.TestCase):
    def test_require_non_empty_str(self) -> None:
        self.assertEqual(require_non_empty_str("ok", "f"), "ok")
        with self.assertRaises(ValueError):
            require_non_empty_str("  ", "f")

    def test_require_non_negative_int(self) -> None:
        self.assertEqual(require_non_negative_int(0, "n"), 0)
        with self.assertRaises(ValueError):
            require_non_negative_int(-1, "n")
        with self.assertRaises(ValueError):
            require_non_negative_int(True, "n")

    def test_mapping_to_dict_and_iso_datetime(self) -> None:
        self.assertEqual(mapping_to_dict({"a": 1}, "m"), {"a": 1})
        with self.assertRaises(ValueError):
            mapping_to_dict([], "m")
        self.assertEqual(
            require_iso_datetime_str("2026-03-19T12:00:00+00:00", "created_at"),
            "2026-03-19T12:00:00+00:00",
        )
        with self.assertRaises(ValueError):
            require_iso_datetime_str("bad-time", "created_at")


if __name__ == "__main__":
    unittest.main()
