import unittest

from varipaw.core.contracts import (
    AgentResponse,
    ContractParseError,
    ErrorEnvelope,
    ToolCall,
    ToolResult,
)


class TestCoreContracts(unittest.TestCase):
    def test_tool_call_from_dict(self) -> None:
        call = ToolCall.from_dict({"call_id": "c1", "name": "web_search", "arguments": {"q": "hi"}})
        self.assertEqual(call.call_id, "c1")
        self.assertEqual(call.name, "web_search")
        self.assertEqual(call.arguments, {"q": "hi"})

    def test_tool_call_from_dict_missing_field(self) -> None:
        with self.assertRaises(ContractParseError):
            ToolCall.from_dict({"name": "web_search"})

    def test_tool_result_invariants(self) -> None:
        ok = ToolResult(call_id="c1", ok=True, data={})
        self.assertTrue(ok.ok)
        with self.assertRaises(ValueError):
            ToolResult(call_id="c2", ok=False, data={})

    def test_agent_response_roundtrip(self) -> None:
        response = AgentResponse(trace_id="trace_1", text="done", steps=())
        raw = response.to_dict()
        parsed = AgentResponse.from_dict(raw)
        self.assertEqual(parsed.trace_id, "trace_1")
        self.assertEqual(parsed.text, "done")
        self.assertEqual(parsed.steps, ())

    def test_error_envelope_code_validation(self) -> None:
        with self.assertRaises(ValueError):
            ErrorEnvelope(code="X", message="bad")


if __name__ == "__main__":
    unittest.main()
