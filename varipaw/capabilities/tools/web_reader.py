"""Web page reader tool for VariPaw."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from lxml.html import fromstring
from readability import Document

from varipaw.capabilities.tools.base import (
    ArgumentValidationError,
    BaseTool,
    ToolSpec,
    VariPawToolError,
)
from varipaw.core.contracts import ErrorEnvelope

__all__ = ["WebReaderTool", "WebReaderConfig"]

logger = logging.getLogger(__name__)

_SPEC = ToolSpec(
    name="web_reader",
    description="Fetch a web page and extract its main text content.",
    parameters_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL of the web page to read.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters of content to return.",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

_ALLOWED_SCHEMES = {"http", "https"}


@dataclass(frozen=True, slots=True)
class WebReaderConfig:
    default_max_chars: int = 8000
    max_max_chars: int = 30000
    timeout_seconds: float = 15.0
    max_response_bytes: int = 5 * 1024 * 1024
    user_agent: str = _DEFAULT_UA

    def __post_init__(self) -> None:
        if self.default_max_chars <= 0:
            raise ValueError(
                f"default_max_chars must be > 0, got {self.default_max_chars}"
            )
        if self.max_max_chars < self.default_max_chars:
            raise ValueError(
                f"max_max_chars ({self.max_max_chars}) "
                f"must be >= default_max_chars ({self.default_max_chars})"
            )
        if self.timeout_seconds <= 0:
            raise ValueError(
                f"timeout_seconds must be > 0, got {self.timeout_seconds}"
            )
        if self.max_response_bytes <= 0:
            raise ValueError(
                f"max_response_bytes must be > 0, got {self.max_response_bytes}"
            )
        if not self.user_agent.strip():
            raise ValueError("user_agent must not be blank")


class WebReaderTool(BaseTool):
    """Fetch and extract main content from a web page."""

    def __init__(self, config: WebReaderConfig | None = None) -> None:
        self._config = config or WebReaderConfig()

    @property
    def spec(self) -> ToolSpec:
        return _SPEC

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        url = arguments.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ArgumentValidationError("'url' must be a non-empty string")

        parsed = urlparse(url.strip())
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ArgumentValidationError(
                f"'url' scheme must be http or https, got {parsed.scheme!r}"
            )
        if not parsed.netloc:
            raise ArgumentValidationError("'url' must have a valid host")

        max_chars = arguments.get("max_chars")
        if max_chars is not None:
            if isinstance(max_chars, bool) or not isinstance(max_chars, int):
                raise ArgumentValidationError("'max_chars' must be an integer")
            if max_chars <= 0:
                raise ArgumentValidationError("'max_chars' must be > 0")
            if max_chars > self._config.max_max_chars:
                raise ArgumentValidationError(
                    f"'max_chars' must be <= {self._config.max_max_chars}"
                )

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        url = arguments["url"].strip()
        max_chars = arguments.get("max_chars", self._config.default_max_chars)

        html = await self._fetch(url)
        title, content = await asyncio.to_thread(self._extract, html, url)

        original_content_length = len(content)
        truncated = original_content_length > max_chars
        if truncated:
            content = content[:max_chars]

        logger.debug(
            "web_reader url=%s title=%r chars=%d truncated=%s",
            url,
            title,
            len(content),
            truncated,
        )

        return {
            "url": url,
            "title": title,
            "content": content,
            "content_length": len(content),
            "original_content_length": original_content_length,
            "truncated": truncated,
        }

    async def _fetch(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(
                timeout=self._config.timeout_seconds,
                follow_redirects=True,
                max_redirects=5,
                headers={"User-Agent": self._config.user_agent},
            ) as client:
                response = await client.get(url)
        except httpx.TimeoutException:
            raise VariPawToolError(
                ErrorEnvelope(
                    code="TOOL_TIMEOUT",
                    message=f"Request timed out after {self._config.timeout_seconds}s",
                    retriable=True,
                    details={
                        "url": url,
                        "timeout_seconds": self._config.timeout_seconds,
                    },
                )
            )
        except httpx.TooManyRedirects:
            raise VariPawToolError(
                ErrorEnvelope(
                    code="TOOL_EXEC_ERROR",
                    message="Too many redirects",
                    retriable=False,
                    details={"url": url},
                )
            )
        except httpx.HTTPError as exc:
            raise VariPawToolError(
                ErrorEnvelope(
                    code="TOOL_EXEC_ERROR",
                    message=f"HTTP request failed: {exc}",
                    retriable=False,
                    details={
                        "url": url,
                        "exception_type": type(exc).__name__,
                    },
                )
            ) from exc

        if response.status_code >= 400:
            retriable = response.status_code in {429, 500, 502, 503, 504}
            raise VariPawToolError(
                ErrorEnvelope(
                    code="TOOL_EXEC_ERROR",
                    message=f"HTTP {response.status_code}",
                    retriable=retriable,
                    details={"url": url, "status_code": response.status_code},
                )
            )

        content_length = len(response.content)
        if content_length > self._config.max_response_bytes:
            raise VariPawToolError(
                ErrorEnvelope(
                    code="TOOL_EXEC_ERROR",
                    message=f"Response too large: {content_length} bytes",
                    retriable=False,
                    details={
                        "url": url,
                        "content_length": content_length,
                        "max_bytes": self._config.max_response_bytes,
                    },
                )
            )

        return response.text

    def _extract(self, html: str, url: str) -> tuple[str, str]:
        try:
            return self._extract_readability(html, url)
        except Exception:
            logger.warning(
                "readability extraction failed for %s, using fallback",
                url,
            )
            return self._extract_fallback(html)

    def _extract_readability(self, html: str, url: str) -> tuple[str, str]:
        doc = Document(html, url=url)
        title = (doc.short_title() or "").strip()

        summary_html = doc.summary()
        text = self._html_to_text(summary_html)

        if not text.strip():
            raise ValueError("readability produced empty content")

        return title, text.strip()

    def _extract_fallback(self, html: str) -> tuple[str, str]:
        try:
            tree = fromstring(html)
        except Exception:
            return "", ""

        title_el = tree.find(".//title")
        title = title_el.text_content().strip() if title_el is not None else ""

        body = tree.find(".//body")
        if body is None:
            return title, ""

        for tag in list(body.iter("script", "style", "noscript")):
            parent = tag.getparent()
            if parent is not None:
                parent.remove(tag)

        return title, self._collapse_whitespace(body.text_content())

    def _html_to_text(self, html: str) -> str:
        try:
            tree = fromstring(html)
        except Exception:
            return ""
        return self._collapse_whitespace(tree.text_content())

    @staticmethod
    def _collapse_whitespace(text: str) -> str:
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)