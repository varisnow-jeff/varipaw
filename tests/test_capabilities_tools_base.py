import asyncio
import unittest
from typing import Any

from varipaw.capabilities.tools.base import BaseTool, ToolSpec, VariPawToolError
from varipaw.core.contracts import ErrorEnvelope, ToolCall


class EchoTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="echo", description="echo tool")

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"echo": arguments.get("text")}


class FailTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="fail", description="fail tool")

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raise VariPawToolError(
            ErrorEnvelope(code="TOOL_EXEC_ERROR", message="controlled fail")
        )


class TestCapabilitiesToolsBase(unittest.TestCase):
    def test_tool_invoke_success(self) -> None:
        tool = EchoTool()
        call = ToolCall(call_id="c1", name="echo", arguments={"text": "hi"})
        result = asyncio.run(tool.invoke(call))
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"echo": "hi"})
        self.assertIsNone(result.error)

    def test_tool_invoke_name_mismatch(self) -> None:
        tool = EchoTool()
        call = ToolCall(call_id="c2", name="other", arguments={})
        result = asyncio.run(tool.invoke(call))
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "VALIDATION_ERROR")

    def test_tool_invoke_controlled_error(self) -> None:
        tool = FailTool()
        call = ToolCall(call_id="c3", name="fail", arguments={})
        result = asyncio.run(tool.invoke(call))
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "TOOL_EXEC_ERROR")
        self.assertEqual(result.error.message, "controlled fail")


if __name__ == "__main__":
    unittest.main()
