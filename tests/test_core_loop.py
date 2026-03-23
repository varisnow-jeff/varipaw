import asyncio
import unittest
from unittest.mock import patch

from varipaw.adapters.providers.base import BaseProvider, LLMResponse, ProviderError
from varipaw.capabilities.tools.base import BaseTool, ToolSpec
from varipaw.capabilities.tools.registry import ToolRegistry
from varipaw.core.contracts import ErrorEnvelope, ToolCall, UserMessage
from varipaw.core.loop import AgentLoop, LoopConfig


class EchoProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "echo"

    async def generate(self, messages, tool_schemas) -> LLMResponse:
        return LLMResponse(text="ok")


class FailingProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "fail"

    async def generate(self, messages, tool_schemas) -> LLMResponse:
        raise ProviderError(ErrorEnvelope(code="PROVIDER_ERROR", message="down"))


class DummyTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="dummy_tool", description="dummy")

    async def run(self, arguments) -> dict:
        return {"ok": True}


class FakeSkills:
    async def select_for_user_text(self, user_text: str, limit: int = 3):
        return [type("S", (), {"render": lambda self: "Skill: time-helper\nGuidance:\nUse local time."})()]


class TestCoreLoop(unittest.TestCase):
    def _msg(self) -> UserMessage:
        return UserMessage(session_id="s1", user_id="u1", text="hi")

    def test_run_text_response(self) -> None:
        loop = AgentLoop(
            provider=EchoProvider(),
            tool_registry=ToolRegistry(),
            config=LoopConfig(max_steps=2),
        )
        resp = asyncio.run(loop.run(self._msg()))
        self.assertEqual(resp.text, "ok")
        self.assertEqual(len(resp.steps), 1)

    def test_run_provider_failure_response(self) -> None:
        loop = AgentLoop(
            provider=FailingProvider(),
            tool_registry=ToolRegistry(),
            config=LoopConfig(max_steps=2, provider_failure_text="pf"),
        )
        resp = asyncio.run(loop.run(self._msg()))
        self.assertEqual(resp.text, "pf")
        self.assertEqual(len(resp.steps), 1)
        self.assertEqual(resp.steps[0].error_code, "PROVIDER_ERROR")

    def test_dispatch_tool_success(self) -> None:
        registry = ToolRegistry()
        registry.register(DummyTool())
        loop = AgentLoop(provider=EchoProvider(), tool_registry=registry, config=LoopConfig(max_steps=1))
        tool_call = ToolCall(
            call_id="c1",
            name="dummy_tool",
            arguments={},
        )
        result, _ = asyncio.run(loop._dispatch_tool(tool_call))
        self.assertTrue(result.ok)

    def test_build_initial_history_injects_current_time(self) -> None:
        loop = AgentLoop(
            provider=EchoProvider(),
            tool_registry=ToolRegistry(),
            config=LoopConfig(max_steps=2, system_prompt="sys"),
        )
        with patch.dict("os.environ", {"TZ_OFFSET": "9"}, clear=False):
            history = asyncio.run(loop._build_initial_history(self._msg()))
        self.assertIn("Current time:", history[0].content)
        self.assertIn("(UTC+9)", history[0].content)

    def test_build_initial_history_injects_skills(self) -> None:
        loop = AgentLoop(
            provider=EchoProvider(),
            tool_registry=ToolRegistry(),
            config=LoopConfig(max_steps=2, system_prompt="sys"),
            skills=FakeSkills(),
        )
        history = asyncio.run(loop._build_initial_history(self._msg()))
        self.assertIn("Relevant skills:", history[0].content)
        self.assertIn("time-helper", history[0].content)


if __name__ == "__main__":
    unittest.main()
