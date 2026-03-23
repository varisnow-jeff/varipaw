from __future__ import annotations

import sys
import types
from contextlib import contextmanager


@contextmanager
def offline_dependencies():
    backup = dict(sys.modules)
    try:
        openai_mod = types.ModuleType("openai")

        class AuthenticationError(Exception):
            pass

        class RateLimitError(Exception):
            pass

        class APITimeoutError(Exception):
            pass

        class APIError(Exception):
            def __init__(self, message: str = "", status_code: int | None = None) -> None:
                super().__init__(message)
                self.status_code = status_code

        class AsyncOpenAI:
            def __init__(self, *args, **kwargs) -> None:
                self.chat = types.SimpleNamespace(
                    completions=types.SimpleNamespace(create=self._create)
                )

            async def _create(self, *args, **kwargs):
                raise RuntimeError("not implemented in offline test")

        openai_mod.AuthenticationError = AuthenticationError
        openai_mod.RateLimitError = RateLimitError
        openai_mod.APITimeoutError = APITimeoutError
        openai_mod.APIError = APIError
        openai_mod.AsyncOpenAI = AsyncOpenAI

        ddgs_mod = types.ModuleType("ddgs")

        class DDGS:
            def __init__(self, timeout=None) -> None:
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def text(self, query: str, max_results: int = 5):
                return []

        ddgs_mod.DDGS = DDGS

        dotenv_mod = types.ModuleType("dotenv")
        dotenv_mod.load_dotenv = lambda *args, **kwargs: None

        httpx_mod = types.ModuleType("httpx")

        class TimeoutException(Exception):
            pass

        class TooManyRedirects(Exception):
            pass

        class HTTPError(Exception):
            pass

        class AsyncClient:
            def __init__(self, *args, **kwargs) -> None:
                self.args = args
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url: str):
                return types.SimpleNamespace(status_code=200, content=b"", text="")

        httpx_mod.TimeoutException = TimeoutException
        httpx_mod.TooManyRedirects = TooManyRedirects
        httpx_mod.HTTPError = HTTPError
        httpx_mod.AsyncClient = AsyncClient

        lxml_mod = types.ModuleType("lxml")
        lxml_html_mod = types.ModuleType("lxml.html")
        lxml_html_mod.fromstring = lambda html: types.SimpleNamespace()
        lxml_mod.html = lxml_html_mod

        readability_mod = types.ModuleType("readability")

        class Document:
            def __init__(self, html: str, url: str | None = None) -> None:
                self._html = html
                self._url = url

            def short_title(self) -> str:
                return ""

            def summary(self) -> str:
                return ""

        readability_mod.Document = Document

        sys.modules["openai"] = openai_mod
        sys.modules["ddgs"] = ddgs_mod
        sys.modules["dotenv"] = dotenv_mod
        sys.modules["httpx"] = httpx_mod
        sys.modules["lxml"] = lxml_mod
        sys.modules["lxml.html"] = lxml_html_mod
        sys.modules["readability"] = readability_mod

        yield
    finally:
        sys.modules.clear()
        sys.modules.update(backup)
