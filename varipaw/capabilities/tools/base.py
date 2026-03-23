"""Abstract base class and spec for all VariPaw tools."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from varipaw.core.contracts import ContractParseError, ErrorEnvelope, ToolCall, ToolResult
from varipaw.core.validation import (
    deep_copy_mapping,
    mapping_to_dict,
    require_keys,
    require_mapping,
    require_non_empty_str,
    require_tool_name,
)

__all__ = ["ToolSpec", "BaseTool", "VariPawToolError", "ArgumentValidationError"]

logger = logging.getLogger(__name__)


class VariPawToolError(Exception):
    """Tool error with explicit envelope."""

    def __init__(self, envelope: ErrorEnvelope) -> None:
        if not isinstance(envelope, ErrorEnvelope):
            raise TypeError("envelope must be an ErrorEnvelope")
        self.envelope = envelope
        super().__init__(envelope.message)


class ArgumentValidationError(ValueError):
    """Argument validation error."""

    def __init__(self, message: str, *, retriable: bool = False) -> None:
        self.retriable = retriable
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Tool metadata."""

    name: str
    description: str
    parameters_schema: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_tool_name(self.name, "ToolSpec.name"))
        object.__setattr__(self, "description", require_non_empty_str(self.description, "ToolSpec.description"))
        object.__setattr__(self, "parameters_schema", deep_copy_mapping(self.parameters_schema, "ToolSpec.parameters_schema"))

    def __repr__(self) -> str:
        keys = list(self.parameters_schema.keys())
        return f"ToolSpec(name={self.name!r}, description={self.description!r}, schema_keys={keys!r})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters_schema": deep_copy_mapping(self.parameters_schema, "parameters_schema"),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ToolSpec:
        try:
            raw = require_mapping(raw, "ToolSpec raw")
            require_keys(raw, "name", "description")
            return cls(
                name=raw["name"],
                description=raw["description"],
                parameters_schema=mapping_to_dict(raw.get("parameters_schema", {}), "parameters_schema"),
            )
        except (ValueError, TypeError) as exc:
            raise ContractParseError("ToolSpec", str(exc)) from exc


class BaseTool(ABC):
    """Abstract base for every tool in the capabilities layer."""

    @property
    @abstractmethod
    def spec(self) -> ToolSpec: ...

    @abstractmethod
    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]: ...

    @property
    def name(self) -> str:
        return self.spec.name

    async def invoke(self, call: ToolCall) -> ToolResult:
        """Run tool with guard-rails."""
        try:
            return await self._invoke_inner(call)
        except Exception as exc:
            logger.critical(
                "invoke() breached error boundary for tool %r: %s",
                self.name, exc, exc_info=True,
            )
            call_id = getattr(call, "call_id", "unknown")
            return self._fail(
                call_id=call_id,
                code="INTERNAL_ERROR",
                message=f"Unexpected internal error in tool {self.name!r}: {exc}",
                details={"tool": self.name, "exception_type": type(exc).__name__},
            )

    async def _invoke_inner(self, call: ToolCall) -> ToolResult:
        """Run core invoke flow."""
        if call.name != self.name:
            return self._fail(
                call_id=call.call_id,
                code="VALIDATION_ERROR",
                message=f"tool name mismatch: expected {self.name!r}, got {call.name!r}",
                details={"expected": self.name, "received": call.name},
            )

        try:
            args = mapping_to_dict(call.arguments, "arguments")
        except (ValueError, TypeError):
            return self._fail(
                call_id=call.call_id,
                code="VALIDATION_ERROR",
                message="Tool arguments must be a mapping",
                details={"tool": self.name, "type": type(call.arguments).__name__},
            )

        err = self._guard_sync(call.call_id, "validate", lambda: self.validate_arguments(args))
        if err is not None:
            return err

        err, raw_data = await self._guard_async_with_result(
            call.call_id, "run", lambda: self.run(args),
        )
        if err is not None:
            return err

        if not isinstance(raw_data, Mapping):
            return self._fail(
                call_id=call.call_id,
                code="TOOL_EXEC_ERROR",
                message=f"Tool {self.name!r} must return a Mapping, got {type(raw_data).__name__}",
                details={"tool": self.name, "return_type": type(raw_data).__name__},
            )

        return ToolResult(call_id=call.call_id, ok=True, data=dict(raw_data))

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        """Optional argument validation hook."""

    def to_schema(self) -> dict[str, Any]:
        return self.spec.to_dict()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"

    def _exception_to_result(
        self, exc: Exception, call_id: str, phase: str,
    ) -> ToolResult:
        """Map exception to failed ToolResult."""

        if isinstance(exc, VariPawToolError):
            return ToolResult(call_id=call_id, ok=False, data=None, error=exc.envelope)

        if isinstance(exc, ArgumentValidationError):
            return self._fail(
                call_id=call_id,
                code="VALIDATION_ERROR",
                message=str(exc) or "Invalid tool arguments",
                retriable=exc.retriable,
                details={"tool": self.name, "phase": phase},
            )

        if isinstance(exc, ContractParseError):
            logger.error(
                "Contract construction failed in %s.%s: %s",
                self.name, phase, exc, exc_info=True,
            )
            return self._fail(
                call_id=call_id,
                code="INTERNAL_ERROR",
                message=f"Internal contract error in tool {self.name!r}: {exc}",
                details={
                    "tool": self.name,
                    "phase": phase,
                    "contract": exc.contract_name,
                },
            )

        if isinstance(exc, TimeoutError):
            return self._fail(
                call_id=call_id,
                code="TOOL_TIMEOUT",
                message=str(exc) or f"Tool {self.name!r} timed out",
                retriable=True,
                details={"tool": self.name, "phase": phase},
            )

        if isinstance(exc, ValueError):
            code = "TOOL_EXEC_ERROR" if phase == "run" else "VALIDATION_ERROR"
            logger.warning("%s.%s raised ValueError: %s", self.name, phase, exc)
            return self._fail(
                call_id=call_id,
                code=code,
                message=str(exc) or f"Tool {phase} failed",
                details={"tool": self.name, "phase": phase},
            )

        logger.error(
            "Unexpected error in %s.%s: %s", self.name, phase, exc, exc_info=True,
        )
        return self._fail(
            call_id=call_id,
            code="TOOL_EXEC_ERROR",
            message=str(exc) or f"Tool {phase} failed",
            details={"tool": self.name, "phase": phase},
        )

    def _guard_sync(
        self,
        call_id: str,
        phase: str,
        fn: Callable[[], None],
    ) -> ToolResult | None:
        """Run sync callable and map errors."""
        try:
            fn()
            return None
        except Exception as exc:
            return self._exception_to_result(exc, call_id, phase)

    async def _guard_async_with_result(
        self,
        call_id: str,
        phase: str,
        coro_fn: Callable[[], Awaitable[Any]],
    ) -> tuple[ToolResult | None, Any]:
        """Run async callable and map errors."""
        try:
            result = await coro_fn()
            return None, result
        except Exception as exc:
            return self._exception_to_result(exc, call_id, phase), None

    def _fail(
        self,
        *,
        call_id: str,
        code: str,
        message: str,
        retriable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> ToolResult: 
        """Build failed ToolResult."""
        return ToolResult(
            call_id=call_id,
            ok=False,
            data=None,
            error=ErrorEnvelope(
                code=code,
                message=message,
                retriable=retriable,
                details=details or {},
            ),
        )
