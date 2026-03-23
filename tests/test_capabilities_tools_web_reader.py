import unittest
from unittest.mock import patch

from tests._offline_imports import offline_dependencies

with offline_dependencies():
    from varipaw.capabilities.tools.web_reader import WebReaderConfig, WebReaderTool


class TestWebReaderTool(unittest.TestCase):
    def test_validate_arguments(self) -> None:
        tool = WebReaderTool(WebReaderConfig(default_max_chars=100, max_max_chars=200, timeout_seconds=1.0))
        tool.validate_arguments({"url": "https://example.com"})
        with self.assertRaises(ValueError):
            tool.validate_arguments({"url": "ftp://example.com"})
        with self.assertRaises(ValueError):
            tool.validate_arguments({"url": "https://example.com", "max_chars": 999})

    def test_extract_fallback_and_collapse_whitespace(self) -> None:
        tool = WebReaderTool(WebReaderConfig())
        with patch.object(tool, "_extract_readability", side_effect=RuntimeError("x")), patch.object(
            tool, "_extract_fallback", return_value=("", "")
        ):
            title, content = tool._extract("not-html", "https://example.com")
        self.assertEqual(title, "")
        self.assertEqual(content, "")
        self.assertEqual(tool._collapse_whitespace(" a \n\n b "), "a\nb")


if __name__ == "__main__":
    unittest.main()
