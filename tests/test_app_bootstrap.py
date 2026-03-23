import unittest
import json
import tempfile
from unittest.mock import patch

from tests._offline_imports import offline_dependencies

with offline_dependencies():
    import varipaw.app.bootstrap as app_bootstrap
    from varipaw.app.bootstrap import (
        AppContainer,
        build_loop,
        build_policies,
        build_skills,
        bootstrap_app,
    )
    from varipaw.capabilities.skills.router import KeywordSkillRouter
    from varipaw.core.policies import PolicySet
    from varipaw.core.loop import AgentLoop


class TestAppBootstrap(unittest.TestCase):
    def test_build_loop_returns_agent_loop(self) -> None:
        provider = object()
        registry = object()
        loop = build_loop(provider=provider, tool_registry=registry)  # type: ignore[arg-type]
        self.assertIsInstance(loop, AgentLoop)

    def test_bootstrap_app_wiring(self) -> None:
        fake_provider = object()
        fake_registry = object()
        fake_memory = object()
        fake_skills = object()
        fake_policies = object()
        fake_logger = object()
        fake_replay_store = object()
        fake_loop = object()
        with patch.object(app_bootstrap, "load_dotenv") as p_dotenv, patch.object(
            app_bootstrap, "build_provider", return_value=fake_provider
        ), patch.object(app_bootstrap, "build_tool_registry", return_value=fake_registry), patch.object(
            app_bootstrap, "build_memory", return_value=fake_memory
        ), patch.object(app_bootstrap, "build_skills", return_value=fake_skills
        ), patch.object(app_bootstrap, "build_policies", return_value=fake_policies), patch.object(
            app_bootstrap, "setup_logger", return_value=fake_logger
        ), patch.object(app_bootstrap, "ReplayStore", return_value=fake_replay_store), patch.object(
            app_bootstrap, "build_loop", return_value=fake_loop
        ):
            container = bootstrap_app()
        p_dotenv.assert_called_once()
        self.assertIsInstance(container, AppContainer)
        self.assertIs(container.provider, fake_provider)
        self.assertIs(container.tool_registry, fake_registry)
        self.assertIs(container.memory, fake_memory)
        self.assertIs(container.replay_store, fake_replay_store)
        self.assertIs(container.skills, fake_skills)
        self.assertIs(container.loop, fake_loop)

    def test_build_policies_defaults(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            policies = build_policies()
        self.assertIsInstance(policies, PolicySet)

    def test_build_policies_from_env(self) -> None:
        env = {
            "VARIPAW_MAX_STEPS": "9",
            "VARIPAW_INCLUDE_THOUGHT_IN_STEPS": "false",
            "VARIPAW_TOOL_TIMEOUT_SECONDS": "12.5",
            "VARIPAW_ALLOWED_TOOLS": "web_search,web_reader",
            "VARIPAW_RETRY_MAX_ATTEMPTS": "3",
            "VARIPAW_RETRY_BACKOFF_SECONDS": "0.2",
            "VARIPAW_RETRYABLE_ERROR_CODES": "TOOL_TIMEOUT,PROVIDER_ERROR",
        }
        with patch.dict("os.environ", env, clear=True):
            policies = build_policies()
        self.assertEqual(policies.loop.max_steps, 9)
        self.assertFalse(policies.loop.include_thought_in_steps)
        self.assertEqual(policies.tool_default.timeout_seconds, 12.5)
        self.assertEqual(
            policies.tool_default.allowed_tools,
            frozenset({"web_search", "web_reader"}),
        )
        self.assertEqual(policies.retry.max_attempts, 3)
        self.assertEqual(policies.retry.backoff_seconds, 0.2)
        self.assertEqual(
            policies.retry.retryable_error_codes,
            frozenset({"TOOL_TIMEOUT", "PROVIDER_ERROR"}),
        )

    def test_build_policies_from_file(self) -> None:
        data = {"loop": {"max_steps": 7}, "retry": {"max_attempts": 2}}
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/policy.json"
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(json.dumps(data))
            with patch.dict("os.environ", {"VARIPAW_POLICY_FILE": path}, clear=True):
                policies = build_policies()
        self.assertEqual(policies.loop.max_steps, 7)
        self.assertEqual(policies.retry.max_attempts, 2)

    def test_build_policies_file_and_env_override(self) -> None:
        data = {"loop": {"max_steps": 7}}
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/policy.json"
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(json.dumps(data))
            env = {"VARIPAW_POLICY_FILE": path, "VARIPAW_MAX_STEPS": "11"}
            with patch.dict("os.environ", env, clear=True):
                policies = build_policies()
        self.assertEqual(policies.loop.max_steps, 11)

    def test_build_skills_defaults(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            skills = build_skills()
        self.assertIsInstance(skills, KeywordSkillRouter)


if __name__ == "__main__":
    unittest.main()
