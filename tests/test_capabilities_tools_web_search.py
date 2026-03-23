import unittest
from unittest.mock import patch

from tests._offline_imports import offline_dependencies

with offline_dependencies():
    from varipaw.capabilities.tools.web_search import WebSearchConfig, WebSearchTool


class TestWebSearchTool(unittest.TestCase):
    def test_validate_arguments(self) -> None:
        tool = WebSearchTool(WebSearchConfig(default_max_results=3, max_max_results=5, timeout_seconds=1.0))
        tool.validate_arguments({"query": "python", "max_results": 2})
        with self.assertRaises(ValueError):
            tool.validate_arguments({"query": ""})
        with self.assertRaises(ValueError):
            tool.validate_arguments({"query": "x", "max_results": 999})

    def test_run_with_mocked_search(self) -> None:
        tool = WebSearchTool(WebSearchConfig(default_max_results=2, max_max_results=5, timeout_seconds=1.0))
        fake_raw = [
            {"title": "A", "href": "https://a", "body": "sa"},
            {"title": "B", "href": "https://b", "body": "sb"},
        ]
        with patch.object(tool, "_search_sync", return_value=fake_raw):
            result = __import__("asyncio").run(tool.run({"query": "hello"}))
        self.assertEqual(result["query"], "hello")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["results"][0]["rank"], 1)


if __name__ == "__main__":
    unittest.main()
