"""OpenAI-compatible provider adapter."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import openai
from openai import AsyncOpenAI

from varipaw.adapters.providers.base import (
    AssistantMessage,
    BaseProvider,
    HumanMessage,
    LLMResponse,
    Message,
    ProviderError,
    SystemMessage,
    ToolResultMessage,
)
from varipaw.core.contracts import ToolCall
from varipaw.core.validation import frozen_setattr as _set, require_non_empty_str
from varipaw.runtime.errors import provider_error

__all__ = ["OpenAIProvider", "ProviderConfig", "load_provider_config"]

logger = logging.getLogger(__name__)


_PROVIDER_ENV_MAP: dict[str, tuple[str, str, str]] = {
    "openai": ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"),
    "deepseek": ("DEEPSEEK_BASE_URL", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"),
}

_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
}


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Resolved configuration for one provider."""

    provider_name: str
    base_url: str
    api_key: str
    model: str
    temperature: float
    max_completion_tokens: int

    def __post_init__(self) -> None:
        _set(self, "provider_name", require_non_empty_str(self.provider_name, "provider_name"))
        _set(self, "base_url", require_non_empty_str(self.base_url, "base_url"))
        _set(self, "api_key", require_non_empty_str(self.api_key, "api_key"))
        _set(self, "model", require_non_empty_str(self.model, "model"))

        if self.temperature < 0:
            raise ValueError("temperature must be >= 0")
        if self.max_completion_tokens <= 0:
            raise ValueError("max_completion_tokens must be > 0")

    def __repr__(self) -> str:
        return (
            f"ProviderConfig(provider={self.provider_name!r}, "
            f"model={self.model!r}, base_url={self.base_url!r}, "
            f"temperature={self.temperature}, max_completion_tokens={self.max_completion_tokens})"
        )


def load_provider_config(provider_name: str | None = None) -> ProviderConfig:
    """Load provider config from environment."""
    name = (provider_name or os.environ.get("LLM_PROVIDER", "openai")).strip().lower()

    if name not in _PROVIDER_ENV_MAP:
        available = sorted(_PROVIDER_ENV_MAP.keys())
        raise ValueError(f"Unknown provider {name!r}. Available: {available}")

    base_url_env, api_key_env, model_env = _PROVIDER_ENV_MAP[name]
    defaults = _DEFAULTS[name]

    base_url = os.environ.get(base_url_env, "").strip() or defaults["base_url"]
    model = os.environ.get(model_env, "").strip() or defaults["model"]
    api_key = os.environ.get(api_key_env, "").strip()
    if not api_key:
        raise EnvironmentError(f"Missing required environment variable: {api_key_env}")

    try:
        temperature = float(os.environ.get("LLM_TEMPERATURE", "0.7"))
    except ValueError as exc:
        raise ValueError("LLM_TEMPERATURE must be a valid float") from exc

    try:
        max_completion_tokens = int(os.environ.get("LLM_max_completion_tokens", "8192"))
    except ValueError as exc:
        raise ValueError("LLM_max_completion_tokens must be a valid int") from exc

    return ProviderConfig(
        provider_name=name,
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_completion_tokens=max_completion_tokens,
    )


class OpenAIProvider(BaseProvider):
    """OpenAI chat completions provider."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

        logger.info(
            "Initialized %s(provider=%s, model=%s, base_url=%s)",
            self.__class__.__name__,
            config.provider_name,
            config.model,
            config.base_url,
        )

    @property
    def name(self) -> str:
        return self._config.provider_name

    @property
    def model(self) -> str:
        return self._config.model

    async def generate(
        self,
        messages: Sequence[Message],
        tool_schemas: Sequence[dict[str, Any]],
    ) -> LLMResponse:
        api_messages = self._build_messages(messages)
        api_tools = self._build_tools_param(tool_schemas) if tool_schemas else None

        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": api_messages,
            "temperature": self._config.temperature,
            "max_completion_tokens": self._config.max_completion_tokens,
        }
        if api_tools:
            kwargs["tools"] = api_tools
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = False

        logger.debug(
            "Calling chat.completions.create model=%s messages=%d tools=%d",
            self._config.model,
            len(api_messages),
            len(tool_schemas),
        )

        t0 = time.monotonic()
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            envelope = provider_error(
                f"Authentication failed: {exc}",
                retriable=False,
                details={"provider": self._config.provider_name},
            )
            raise ProviderError(envelope) from exc
        except openai.RateLimitError as exc:
            envelope = provider_error(
                f"Rate limited: {exc}",
                retriable=True,
                details={
                    "provider": self._config.provider_name,
                    "status_code": 429,
                },
            )
            raise ProviderError(envelope) from exc
        except openai.APITimeoutError as exc:
            envelope = provider_error(
                f"Request timed out: {exc}",
                retriable=True,
                details={"provider": self._config.provider_name},
            )
            raise ProviderError(envelope) from exc
        except openai.APIError as exc:
            status_code = getattr(exc, "status_code", None)
            retriable = isinstance(status_code, int) and (
                status_code >= 500 or status_code == 429
            )
            envelope = provider_error(
                f"API error: {exc}",
                retriable=retriable,
                details={
                    "provider": self._config.provider_name,
                    "status_code": status_code,
                },
            )
            raise ProviderError(envelope) from exc

        duration_ms = int((time.monotonic() - t0) * 1000)
        return self._parse_response(response, duration_ms=duration_ms)

    def _build_messages(self, messages: Sequence[Message]) -> list[dict[str, Any]]:
        """Convert internal messages to OpenAI payload."""
        api_messages: list[dict[str, Any]] = []

        for message in messages:
            if isinstance(message, SystemMessage):
                api_messages.append({"role": "system", "content": message.content})

            elif isinstance(message, HumanMessage):
                api_messages.append({"role": "user", "content": message.content})

            elif isinstance(message, AssistantMessage):
                msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": message.content,
                }
                raw_tool_calls = getattr(message, "tool_calls", None)
                if raw_tool_calls:
                    msg["tool_calls"] = raw_tool_calls
                api_messages.append(msg)

            elif isinstance(message, ToolResultMessage):
                api_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.call_id,
                        "name": message.tool_name,
                        "content": message.content,
                    }
                )
            else:
                raise TypeError(f"Unsupported message type: {type(message).__name__}")

        return api_messages

    def _build_tools_param(
        self,
        tool_schemas: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert VariPaw tool schemas to OpenAI function-calling format."""
        tools: list[dict[str, Any]] = []

        for schema in tool_schemas:
            function_def: dict[str, Any] = {
                "name": schema["name"],
                "description": schema.get("description", ""),
            }
            params = schema.get("parameters_schema", {})
            if params:
                function_def["parameters"] = params
            tools.append({"type": "function", "function": function_def})

        return tools

    def _parse_response(
        self,
        response: Any,
        *,
        duration_ms: int,
    ) -> LLMResponse:
        """Parse the raw SDK response into a ``LLMResponse``."""
        choices = getattr(response, "choices", None)
        if not isinstance(choices, Sequence) or not choices:
            raise ProviderError(
                provider_error(
                    "Provider returned no choices",
                    retriable=False,
                    details={"provider": self._config.provider_name},
                )
            )

        choice = choices[0]
        message = getattr(choice, "message", None)
        if message is None:
            raise ProviderError(
                provider_error(
                    "Provider choice missing message",
                    retriable=False,
                    details={"provider": self._config.provider_name},
                )
            )

        finish_reason = getattr(choice, "finish_reason", None)
        logger.debug("finish_reason=%s", finish_reason)

        token_in, token_out = self._extract_usage(response)
        thought = self._extract_thought(message)
        raw = self._dump_response(response)

        tool_calls = getattr(message, "tool_calls", None)
        if (
            isinstance(tool_calls, Sequence)
            and not isinstance(tool_calls, (str, bytes))
            and tool_calls
        ):
            return self._parse_tool_call(
                tool_calls,
                thought=thought,
                token_in=token_in,
                token_out=token_out,
                duration_ms=duration_ms,
                finish_reason=finish_reason,
                raw=raw,
            )

        text = getattr(message, "content", None)
        if not isinstance(text, str) or not text.strip():
            logger.warning("Model returned empty text, using fallback")
            text = "(empty response from model)"

        return LLMResponse(
            thought=thought,
            text=text,
            token_in=token_in,
            token_out=token_out,
            duration_ms=duration_ms,
            finish_reason=finish_reason,
            raw=raw,
        )

    @staticmethod
    def _dump_response(response: Any) -> dict[str, Any]:
        """Serialize provider response."""
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if hasattr(response, "to_dict"):
            return response.to_dict()
        return {}

    @staticmethod
    def _extract_usage(response: Any) -> tuple[int | None, int | None]:
        """Extract prompt and completion token counts from the response."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return None, None

        token_in = getattr(usage, "prompt_tokens", None)
        token_out = getattr(usage, "completion_tokens", None)
        return token_in, token_out

    @staticmethod
    def _extract_thought(message: Any) -> str | None:
        """Extract thought text from provider message."""
        reasoning = getattr(message, "reasoning_content", None)
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning.strip()

        tool_calls = getattr(message, "tool_calls", None)
        content = getattr(message, "content", None)
        if tool_calls and isinstance(content, str):
            content = content.strip()
            if content:
                return content

        return None

    def _parse_tool_call(
        self,
        tool_calls: Sequence[Any],
        *,
        thought: str | None,
        token_in: int | None,
        token_out: int | None,
        duration_ms: int,
        finish_reason: str | None,
        raw: dict[str, Any],
    ) -> LLMResponse:
        """Parse first tool call from provider response."""
        if len(tool_calls) > 1:
            names = [
                getattr(getattr(tc, "function", None), "name", None)
                for tc in tool_calls
            ]
            logger.warning(
                "Model returned %d tool calls %s; using first only",
                len(tool_calls),
                names,
            )

        tc = tool_calls[0]
        function_obj = getattr(tc, "function", None)
        if function_obj is None:
            raise ProviderError(
                provider_error(
                    "Tool call missing function payload",
                    retriable=False,
                    details={"provider": self._config.provider_name},
                )
            )

        name = getattr(function_obj, "name", None)
        raw_args = getattr(function_obj, "arguments", None)

        if not isinstance(name, str) or not name.strip():
            raise ProviderError(
                provider_error(
                    "Tool call has empty or missing function name",
                    retriable=False,
                    details={
                        "provider": self._config.provider_name,
                        "raw_name": name,
                    },
                )
            )

        tool_name = name.strip()
        arguments = self._parse_tool_arguments(raw_args, tool_name)
        call_id = getattr(tc, "id", None) or uuid4().hex

        return LLMResponse(
            thought=thought,
            tool_call=ToolCall(
                call_id=call_id,
                name=tool_name,
                arguments=arguments,
            ),
            token_in=token_in,
            token_out=token_out,
            duration_ms=duration_ms,
            finish_reason=finish_reason,
            raw=raw,
        )

    def _parse_tool_arguments(
        self,
        raw_args: str | None,
        tool_name: str,
    ) -> dict[str, Any]:
        """Parse tool arguments as JSON dict."""
        if not raw_args or not raw_args.strip():
            return {}

        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                provider_error(
                    f"Failed to parse tool arguments for {tool_name!r} as JSON: {exc}",
                    retriable=False,
                    details={
                        "provider": self._config.provider_name,
                        "tool_name": tool_name,
                        "raw_args": raw_args[:500],
                    },
                )
            ) from exc

        if isinstance(parsed, dict):
            return parsed

        logger.warning(
            "Tool args for %r parsed as %s instead of dict, wrapping",
            tool_name,
            type(parsed).__name__,
        )
        return {"_value": parsed}

    def __repr__(self) -> str:
        return (
            f"OpenAIProvider(provider={self._config.provider_name!r}, "
            f"model={self._config.model!r}, base_url={self._config.base_url!r})"
        )
