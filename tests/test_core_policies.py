import unittest

from varipaw.core.policies import LoopPolicy, PolicySet, RetryPolicy, ToolPolicy


class TestCorePolicies(unittest.TestCase):
    def test_retry_policy(self) -> None:
        policy = RetryPolicy(max_attempts=3, retryable_error_codes=frozenset({"TOOL_TIMEOUT"}))
        self.assertTrue(policy.should_retry("TOOL_TIMEOUT", 1))
        self.assertFalse(policy.should_retry("INTERNAL_ERROR", 1))
        self.assertFalse(policy.should_retry("TOOL_TIMEOUT", 3))

    def test_tool_policy(self) -> None:
        policy = ToolPolicy(timeout_seconds=5.0, allowed_tools=frozenset({"web_search"}))
        self.assertTrue(policy.is_allowed("web_search"))
        self.assertFalse(policy.is_allowed("shell"))

    def test_policy_set_defaults(self) -> None:
        policy_set = PolicySet()
        self.assertIsInstance(policy_set.loop, LoopPolicy)
        self.assertIsInstance(policy_set.tool_default, ToolPolicy)
        self.assertIsInstance(policy_set.retry, RetryPolicy)


if __name__ == "__main__":
    unittest.main()
