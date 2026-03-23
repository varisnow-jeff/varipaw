"""In-memory tool registry."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from typing import Any

from varipaw.capabilities.tools.base import BaseTool, ToolSpec
from varipaw.core.contracts import ErrorEnvelope, ToolCall, ToolResult
from varipaw.core.validation import require_non_empty_str, require_tool_name

__all__ = ["ToolRegistry", "ToolRegistryError", "DuplicateToolError", "ToolNotFoundError"]

logger = logging.getLogger(__name__)


class ToolRegistryError(Exception):
    """Base exception for registry operations."""


class DuplicateToolError(ToolRegistryError):
    """Raised when a tool name is already registered."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Tool already registered: {name!r}")


class ToolNotFoundError(ToolRegistryError):
    """Raised when a tool name is not found."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Tool not found: {name!r}")


class ToolRegistry:
    """In-memory registry of tool names to ``BaseTool`` instances."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool, *, override: bool = False) -> None:
        """Register a tool instance."""
        if not isinstance(tool, BaseTool):
            raise TypeError(f"expected BaseTool instance, got {type(tool).__name__}")

        name = tool.name
        require_tool_name(name, "tool.name")

        if name in self._tools and not override:
            raise DuplicateToolError(name)

        self._tools[name] = tool
        logger.info("Registered tool %r (override=%s)", name, override)

    def register_all(self, *tools: BaseTool, override: bool = False) -> None:
        """Register multiple tools in one call."""
        for tool in tools:
            self.register(tool, override=override)

    def unregister(self, name: str) -> BaseTool:
        """Remove and return a tool by name."""
        require_non_empty_str(name, "name")
        try:
            tool = self._tools.pop(name)
        except KeyError:
            raise ToolNotFoundError(name) from None
        logger.info("Unregistered tool %r", name)
        return tool

    def get(self, name: str) -> BaseTool | None:
        """Return the tool or ``None`` if not found."""
        return self._tools.get(name)

    def __getitem__(self, name: str) -> BaseTool:
        """Return the tool or raise ``ToolNotFoundError``."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(name)
        return tool

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self) -> Iterator[str]:
        return iter(self._tools)

    async def dispatch(self, call: ToolCall) -> ToolResult:
        """Look up and invoke the tool referenced by ``call``."""
        tool = self._tools.get(call.name)
        if tool is None:
            logger.warning("Dispatch failed: tool %r not found", call.name)
            return ToolResult(
                call_id=call.call_id,
                ok=False,
                data=None,
                error=ErrorEnvelope(
                    code="TOOL_NOT_FOUND",
                    message=f"Tool not found: {call.name!r}",
                    retriable=False,
                    details={"tool": call.name, "available": sorted(self._tools.keys())},
                ),
            )
        return await tool.invoke(call)

    def list_specs(self) -> list[ToolSpec]:
        """Return all registered tool specs."""
        return [tool.spec for tool in self._tools.values()]

    def list_schemas(self) -> list[dict[str, Any]]:
        """Return all registered tool schemas."""
        return [tool.to_schema() for tool in self._tools.values()]

    def list_names(self) -> list[str]:
        """Return sorted tool names."""
        return sorted(self._tools.keys())

    def __repr__(self) -> str:
        return f"ToolRegistry(tools={self.list_names()!r})"
