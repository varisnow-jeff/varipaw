"""Application bootstrap and dependency wiring for VariPaw."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from varipaw.adapters.providers.openai_provider import OpenAIProvider, load_provider_config
from varipaw.capabilities.memory.base import MemoryProvider
from varipaw.capabilities.memory.router import build_default_memory_router
from varipaw.capabilities.skills.router import KeywordSkillRouter, SkillRouterConfig
from varipaw.capabilities.skills.store import FileSkillStore
from varipaw.capabilities.tools.registry import ToolRegistry
from varipaw.capabilities.tools.shell import ShellConfig, ShellTool
from varipaw.capabilities.tools.web_reader import WebReaderTool
from varipaw.capabilities.tools.web_search import WebSearchTool
from varipaw.core.loop import AgentLoop, LoopConfig
from varipaw.core.policies import PolicySet
from varipaw.core.provider import BaseProvider
from varipaw.runtime.logger import setup_logger
from varipaw.runtime.replay import ReplayStore

__all__ = ["AppContainer", "bootstrap_app", "build_loop", "build_policies", "build_skills"]


@dataclass(frozen=True, slots=True)
class AppContainer:
    provider: BaseProvider
    tool_registry: ToolRegistry
    loop: AgentLoop
    memory: MemoryProvider | None = None
    replay_store: ReplayStore | None = None
    skills: KeywordSkillRouter | None = None


def _to_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid bool value: {value!r}")


def _to_str_tuple(value: str) -> tuple[str, ...]:
    items = [item.strip() for item in value.split(",")]
    return tuple(item for item in items if item)


def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in update.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def build_provider() -> BaseProvider:
    config = load_provider_config()
    return OpenAIProvider(config)


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(WebSearchTool())
    registry.register(WebReaderTool())
    registry.register(
        ShellTool(
            ShellConfig(
                sandbox_dir="./sandbox",
            )
        )
    )
    return registry


def build_memory() -> MemoryProvider | None:
    explicit_db_path = os.environ.get("VARIPAW_MEMORY_DB_PATH", "").strip()
    if explicit_db_path:
        db_path = Path(explicit_db_path).expanduser()
    else:
        data_dir = os.environ.get("VARIPAW_DATA_DIR", "").strip()
        base_dir = Path(data_dir).expanduser() if data_dir else Path(".varipaw/state")
        db_path = base_dir / "varipaw_memory.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return build_default_memory_router(db_path=str(db_path))


def build_skills() -> KeywordSkillRouter:
    configured_dir = os.environ.get("VARIPAW_SKILLS_DIR", "").strip()
    directories: list[Path] = []
    if configured_dir:
        for part in configured_dir.split(os.pathsep):
            part = part.strip()
            if not part:
                continue
            directories.append(Path(part).expanduser())
    else:
        directories.append(Path("skills"))
        directories.append(Path(".varipaw/skills"))
    store = FileSkillStore(directories)
    max_skills = int(os.environ.get("VARIPAW_MAX_SKILLS", "3"))
    return KeywordSkillRouter(store=store, config=SkillRouterConfig(max_skills=max_skills))


def build_policies() -> PolicySet:
    raw: dict[str, Any] = {}

    policy_file = os.environ.get("VARIPAW_POLICY_FILE", "").strip()
    if policy_file:
        file_path = Path(policy_file)
        if not file_path.exists():
            raise FileNotFoundError(f"Policy file not found: {policy_file}")
        loaded = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("Policy file must contain a JSON object")
        raw = _deep_merge(raw, loaded)

    policy_json = os.environ.get("VARIPAW_POLICY_JSON", "").strip()
    if policy_json:
        loaded = json.loads(policy_json)
        if not isinstance(loaded, dict):
            raise ValueError("VARIPAW_POLICY_JSON must be a JSON object")
        raw = _deep_merge(raw, loaded)

    if "VARIPAW_MAX_STEPS" in os.environ:
        raw = _deep_merge(raw, {"loop": {"max_steps": int(os.environ["VARIPAW_MAX_STEPS"])}})
    if "VARIPAW_INCLUDE_THOUGHT_IN_STEPS" in os.environ:
        raw = _deep_merge(
            raw,
            {
                "loop": {
                    "include_thought_in_steps": _to_bool(
                        os.environ["VARIPAW_INCLUDE_THOUGHT_IN_STEPS"]
                    )
                }
            },
        )
    if "VARIPAW_TOOL_TIMEOUT_SECONDS" in os.environ:
        raw = _deep_merge(
            raw,
            {"tool_default": {"timeout_seconds": float(os.environ["VARIPAW_TOOL_TIMEOUT_SECONDS"])}},
        )
    if "VARIPAW_ALLOWED_TOOLS" in os.environ:
        raw = _deep_merge(
            raw,
            {
                "tool_default": {
                    "allowed_tools": frozenset(
                        _to_str_tuple(os.environ["VARIPAW_ALLOWED_TOOLS"])
                    )
                }
            },
        )
    if "VARIPAW_RETRY_MAX_ATTEMPTS" in os.environ:
        raw = _deep_merge(
            raw,
            {"retry": {"max_attempts": int(os.environ["VARIPAW_RETRY_MAX_ATTEMPTS"])}},
        )
    if "VARIPAW_RETRY_BACKOFF_SECONDS" in os.environ:
        raw = _deep_merge(
            raw,
            {"retry": {"backoff_seconds": float(os.environ["VARIPAW_RETRY_BACKOFF_SECONDS"])}},
        )
    if "VARIPAW_RETRYABLE_ERROR_CODES" in os.environ:
        raw = _deep_merge(
            raw,
            {
                "retry": {
                    "retryable_error_codes": frozenset(
                        _to_str_tuple(os.environ["VARIPAW_RETRYABLE_ERROR_CODES"])
                    )
                }
            },
        )

    return PolicySet.from_dict(raw)


def build_loop(
    *,
    provider: BaseProvider,
    tool_registry: ToolRegistry,
    memory: MemoryProvider | None = None,
    config: LoopConfig | None = None,
    policies: PolicySet | None = None,
    runtime_logger: logging.Logger | None = None,
    replay_store: ReplayStore | None = None,
    skills: KeywordSkillRouter | None = None,
) -> AgentLoop:
    return AgentLoop(
        provider=provider,
        tool_registry=tool_registry,
        config=config or LoopConfig(),
        memory=memory,
        policies=policies,
        runtime_logger=runtime_logger,
        replay_store=replay_store,
        skills=skills,
    )


def bootstrap_app() -> AppContainer:
    load_dotenv(override=False)

    provider = build_provider()
    tool_registry = build_tool_registry()
    memory = build_memory()
    skills = build_skills()
    policies = build_policies()
    runtime_logger = setup_logger("varipaw.runtime.loop")
    replay_store = ReplayStore()
    loop = build_loop(
        provider=provider,
        tool_registry=tool_registry,
        memory=memory,
        policies=policies,
        runtime_logger=runtime_logger,
        replay_store=replay_store,
        skills=skills,
    )

    return AppContainer(
        provider=provider,
        tool_registry=tool_registry,
        loop=loop,
        memory=memory,
        replay_store=replay_store,
        skills=skills,
    )
