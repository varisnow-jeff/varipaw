from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final

from varipaw.core.validation import (
    build_dataclass_from_mapping,
    frozen_setattr,
    require_bool,
    require_frozenset_of_str,
    require_mapping,
    require_non_empty_str_key,
    require_non_negative_float,
    require_positive_float,
    require_positive_int,
    reject_unknown_keys,
)

DEFAULT_RETRYABLE_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {"TOOL_TIMEOUT", "PROVIDER_ERROR"}
)

_POLICYSET_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {"loop", "tool_default", "tool_overrides", "retry"}
)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 0.0
    retryable_error_codes: frozenset[str] = DEFAULT_RETRYABLE_ERROR_CODES

    def __post_init__(self) -> None:
        frozen_setattr(
            self,
            "max_attempts",
            require_positive_int(self.max_attempts, "max_attempts"),
        )
        frozen_setattr(
            self,
            "backoff_seconds",
            require_non_negative_float(
                self.backoff_seconds,
                "backoff_seconds",
            ),
        )
        frozen_setattr(
            self,
            "retryable_error_codes",
            require_frozenset_of_str(
                self.retryable_error_codes,
                "retryable_error_codes",
            ),
        )

    def should_retry(self, error_code: str | None, attempts_so_far: int) -> bool:
        if error_code is None:
            return False
        if attempts_so_far < 1:
            return False
        if attempts_so_far >= self.max_attempts:
            return False
        return error_code in self.retryable_error_codes


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    timeout_seconds: float = 30.0
    allowed_tools: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        frozen_setattr(
            self,
            "timeout_seconds",
            require_positive_float(self.timeout_seconds, "timeout_seconds"),
        )
        frozen_setattr(
            self,
            "allowed_tools",
            require_frozenset_of_str(self.allowed_tools, "allowed_tools"),
        )

    def is_allowed(self, tool_name: str) -> bool:
        return not self.allowed_tools or tool_name in self.allowed_tools


@dataclass(frozen=True, slots=True)
class LoopPolicy:
    max_steps: int = 6
    include_thought_in_steps: bool = True

    def __post_init__(self) -> None:
        frozen_setattr(
            self,
            "max_steps",
            require_positive_int(self.max_steps, "max_steps"),
        )
        frozen_setattr(
            self,
            "include_thought_in_steps",
            require_bool(
                self.include_thought_in_steps,
                "include_thought_in_steps",
            ),
        )


@dataclass(frozen=True, slots=True)
class PolicySet:
    loop: LoopPolicy = field(default_factory=LoopPolicy)
    tool_default: ToolPolicy = field(default_factory=ToolPolicy)
    tool_overrides: Mapping[str, ToolPolicy] = field(
        default_factory=lambda: MappingProxyType({})
    )
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        if not isinstance(self.loop, LoopPolicy):
            raise TypeError("loop must be a LoopPolicy")
        if not isinstance(self.tool_default, ToolPolicy):
            raise TypeError("tool_default must be a ToolPolicy")
        if not isinstance(self.retry, RetryPolicy):
            raise TypeError("retry must be a RetryPolicy")

        overrides = require_mapping(self.tool_overrides, "tool_overrides")

        validated: dict[str, ToolPolicy] = {}
        for key, policy in overrides.items():
            tool_name = require_non_empty_str_key(key, "tool_overrides")
            if not isinstance(policy, ToolPolicy):
                raise TypeError(
                    f"tool_overrides[{tool_name!r}] must be a ToolPolicy"
                )
            validated[tool_name] = policy

        frozen_setattr(self, "tool_overrides", MappingProxyType(validated))

    def tool_policy_for(self, tool_name: str) -> ToolPolicy:
        return self.tool_overrides.get(tool_name, self.tool_default)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PolicySet:
        mapping = require_mapping(data, "PolicySet.from_dict() argument")
        reject_unknown_keys(
            mapping,
            allowed_keys=_POLICYSET_TOP_LEVEL_KEYS,
            field_name="PolicySet.from_dict() argument",
        )

        raw_overrides = require_mapping(
            mapping.get("tool_overrides", {}),
            "tool_overrides",
        )

        overrides: dict[str, ToolPolicy] = {}
        for key, raw_policy in raw_overrides.items():
            tool_name = require_non_empty_str_key(key, "tool_overrides")
            overrides[tool_name] = build_dataclass_from_mapping(
                ToolPolicy,
                raw_policy,
                field_name=f"tool_overrides[{tool_name!r}]",
            )

        return cls(
            loop=build_dataclass_from_mapping(
                LoopPolicy,
                mapping.get("loop", {}),
                field_name="loop",
            ),
            tool_default=build_dataclass_from_mapping(
                ToolPolicy,
                mapping.get("tool_default", {}),
                field_name="tool_default",
            ),
            tool_overrides=overrides,
            retry=build_dataclass_from_mapping(
                RetryPolicy,
                mapping.get("retry", {}),
                field_name="retry",
            ),
        )
