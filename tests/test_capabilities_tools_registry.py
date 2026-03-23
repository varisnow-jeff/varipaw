import asyncio
import unittest
from typing import Any

from varipaw.capabilities.tools.base import BaseTool, ToolSpec
from varipaw.capabilities.tools.registry import DuplicateToolError, ToolRegistry
from varipaw.core.contracts import ToolCall


class DummyTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="dummy_tool", description="dummy")

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "echo": arguments}


class TestCapabilitiesToolsRegistry(unittest.TestCase):
    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        tool = DummyTool()
        registry.register(tool)
        self.assertIn("dummy_tool", registry)
        self.assertIs(registry.get("dummy_tool"), tool)
        self.assertEqual(registry.list_names(), ["dummy_tool"])

    def test_duplicate_register_raises(self) -> None:
        registry = ToolRegistry()
        registry.register(DummyTool())
        with self.assertRaises(DuplicateToolError):
            registry.register(DummyTool())

    def test_dispatch_not_found(self) -> None:
        registry = ToolRegistry()
        call = ToolCall(call_id="c1", name="missing", arguments={})
        result = asyncio.run(registry.dispatch(call))
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "TOOL_NOT_FOUND")

    def test_dispatch_found(self) -> None:
        registry = ToolRegistry()
        registry.register(DummyTool())
        call = ToolCall(call_id="c2", name="dummy_tool", arguments={"a": 1})
        result = asyncio.run(registry.dispatch(call))
        self.assertTrue(result.ok)
        self.assertEqual(result.data["echo"], {"a": 1})


if __name__ == "__main__":
    unittest.main()
