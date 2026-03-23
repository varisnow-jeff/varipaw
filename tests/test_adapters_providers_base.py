import unittest

from varipaw.adapters.providers.base import (
    AssistantMessage,
    HumanMessage,
    LLMResponse,
    ProviderError,
    SystemMessage,
    ToolResultMessage,
)
from varipaw.core.contracts import ErrorEnvelope, ToolCall


class TestAdaptersProvidersBase(unittest.TestCase):
    def test_message_to_dict(self) -> None:
        self.assertEqual(SystemMessage("s").to_dict()["role"], "system")
        self.assertEqual(HumanMessage("u").to_dict()["role"], "user")
        self.assertEqual(AssistantMessage("a").to_dict()["role"], "assistant")
        self.assertEqual(
            ToolResultMessage(tool_name="t", call_id="c", content="x").to_dict()["role"],
            "tool",
        )

    def test_llm_response_text_and_tool_call_constraints(self) -> None:
        text_resp = LLMResponse(text="hello")
        self.assertTrue(text_resp.is_text)
        call = ToolCall(call_id="c1", name="web_search", arguments={})
        tool_resp = LLMResponse(tool_call=call)
        self.assertTrue(tool_resp.is_tool_call)
        with self.assertRaises(ValueError):
            LLMResponse(text="x", tool_call=call)
        with self.assertRaises(ValueError):
            LLMResponse()

    def test_provider_error_wraps_envelope(self) -> None:
        env = ErrorEnvelope(code="PROVIDER_ERROR", message="p")
        err = ProviderError(env)
        self.assertEqual(err.envelope.code, "PROVIDER_ERROR")
        self.assertEqual(str(err), "p")


if __name__ == "__main__":
    unittest.main()
