import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests._offline_imports import offline_dependencies

with offline_dependencies():
    from varipaw.adapters.providers.openai_provider import OpenAIProvider, ProviderConfig, load_provider_config


class TestAdaptersProvidersOpenAI(unittest.TestCase):
    def test_provider_config_repr_hides_api_key(self) -> None:
        cfg = ProviderConfig(
            provider_name="openai",
            base_url="https://api.openai.com/v1",
            api_key="secret-key",
            model="gpt-4o-mini",
            temperature=0.7,
            max_completion_tokens=8192,
        )
        text = repr(cfg)
        self.assertIn("openai", text)
        self.assertNotIn("secret-key", text)

    def test_load_provider_config_from_env(self) -> None:
        env = {
            "LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "k",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
            "OPENAI_MODEL": "gpt-4o-mini",
            "LLM_TEMPERATURE": "0.5",
            "LLM_max_completion_tokens": "8192",
        }
        with patch.dict("os.environ", env, clear=True):
            cfg = load_provider_config()
        self.assertEqual(cfg.provider_name, "openai")
        self.assertEqual(cfg.temperature, 0.5)
        self.assertEqual(cfg.max_completion_tokens, 8192)

    def test_load_provider_config_missing_key_raises(self) -> None:
        env = {"LLM_PROVIDER": "openai"}
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(EnvironmentError):
                load_provider_config()

    def test_parse_tool_arguments(self) -> None:
        cfg = ProviderConfig(
            provider_name="openai",
            base_url="https://api.openai.com/v1",
            api_key="k",
            model="gpt-4o-mini",
            temperature=0.7,
            max_completion_tokens=8192,
        )
        provider = object.__new__(OpenAIProvider)
        provider._config = cfg
        self.assertEqual(provider._parse_tool_arguments("", "t"), {})
        self.assertEqual(provider._parse_tool_arguments('{"x":1}', "t"), {"x": 1})
        self.assertEqual(provider._parse_tool_arguments("[1,2]", "t"), {"_value": [1, 2]})

    def test_extract_thought(self) -> None:
        msg = SimpleNamespace(reasoning_content="  think  ", tool_calls=None, content=None)
        self.assertEqual(OpenAIProvider._extract_thought(msg), "think")


if __name__ == "__main__":
    unittest.main()
