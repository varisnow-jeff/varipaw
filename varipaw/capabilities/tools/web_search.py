"""DuckDuckGo web search tool for VariPaw."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from ddgs import DDGS

from varipaw.capabilities.tools.base import (
    ArgumentValidationError,
    BaseTool,
    ToolSpec,
    VariPawToolError,
)
from varipaw.core.contracts import ErrorEnvelope

__all__ = ["WebSearchTool", "WebSearchConfig"]

logger = logging.getLogger(__name__)

_SPEC = ToolSpec(
    name="web_search",
    description="Search the web using DuckDuckGo and return top results.",
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)


@dataclass(frozen=True, slots=True)
class WebSearchConfig:
    default_max_results: int = 5
    max_max_results: int = 10
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.default_max_results <= 0:
            raise ValueError(
                f"default_max_results must be > 0, got {self.default_max_results}"
            )
        if self.max_max_results < self.default_max_results:
            raise ValueError(
                f"max_max_results ({self.max_max_results}) "
                f"must be >= default_max_results ({self.default_max_results})"
            )
        if self.timeout_seconds <= 0:
            raise ValueError(
                f"timeout_seconds must be > 0, got {self.timeout_seconds}"
            )


class WebSearchTool(BaseTool):
    """DuckDuckGo web search tool."""

    def __init__(self, config: WebSearchConfig | None = None) -> None:
        self._config = config or WebSearchConfig()

    @property
    def spec(self) -> ToolSpec:
        return _SPEC

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ArgumentValidationError("'query' must be a non-empty string")

        max_results = arguments.get("max_results")
        if max_results is not None:
            if isinstance(max_results, bool) or not isinstance(max_results, int):
                raise ArgumentValidationError("'max_results' must be an integer")
            if max_results <= 0:
                raise ArgumentValidationError("'max_results' must be > 0")
            if max_results > self._config.max_max_results:
                raise ArgumentValidationError(
                    f"'max_results' must be <= {self._config.max_max_results}"
                )

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments["query"].strip()
        max_results = arguments.get("max_results", self._config.default_max_results)

        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._search_sync, query, max_results),
                timeout=self._config.timeout_seconds,
            )
        except TimeoutError:
            raise VariPawToolError(
                ErrorEnvelope(
                    code="TOOL_TIMEOUT",
                    message=f"DuckDuckGo search timed out after {self._config.timeout_seconds}s",
                    retriable=True,
                    details={
                        "query": query,
                        "timeout_seconds": self._config.timeout_seconds,
                    },
                )
            )
        except Exception as exc:
            raise VariPawToolError(
                ErrorEnvelope(
                    code="TOOL_EXEC_ERROR",
                    message=f"DuckDuckGo search failed: {exc}",
                    retriable=False,
                    details={
                        "query": query,
                        "exception_type": type(exc).__name__,
                    },
                )
            ) from exc

        results: list[dict[str, Any]] = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                logger.warning(
                    "web_search returned non-dict result at index %d: %s",
                    idx,
                    type(item).__name__,
                )
                continue

            results.append(
                {
                    "rank": idx + 1,
                    "title": str(item.get("title", "")).strip(),
                    "url": str(item.get("href", "")).strip(),
                    "snippet": str(item.get("body", "")).strip(),
                }
            )

        logger.debug("web_search returned %d results", len(results))

        return {
            "query": query,
            "count": len(results),
            "results": results,
        }

    def _search_sync(self, query: str, max_results: int) -> list[dict[str, Any]]:
        """Blocking DuckDuckGo search, executed in a worker thread."""
        with DDGS(timeout=self._config.timeout_seconds) as ddgs:
            return list(ddgs.text(query, max_results=max_results))