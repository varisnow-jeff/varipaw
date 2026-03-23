"""Sandboxed shell command execution tool for VariPaw."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from varipaw.capabilities.tools.base import (
    ArgumentValidationError,
    BaseTool,
    ToolSpec,
    VariPawToolError,
)
from varipaw.core.contracts import ErrorEnvelope

__all__ = ["ShellTool", "ShellConfig"]

logger = logging.getLogger(__name__)

_SPEC = ToolSpec(
    name="shell",
    description=(
        "Execute a command in a sandboxed environment. "
        "Only whitelisted commands are allowed. "
        "If the command matches a blacklist rule, the tool returns a "
        "REQUIRES_CONFIRMATION result. Re-invoke with confirmed=true "
        "to proceed after obtaining user approval."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "argv": {
                "type": "array",
                "description": "Command and arguments as a list of strings.",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "cwd": {
                "type": "string",
                "description": "Working directory, relative to the sandbox root.",
            },
            "timeout_seconds": {
                "type": "number",
                "description": "Max execution time in seconds.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Max characters for stdout/stderr output.",
            },
            "confirmed": {
                "type": "boolean",
                "description": (
                    "Set to true to confirm a blacklisted command "
                    "after user approval."
                ),
            },
        },
        "required": ["argv"],
        "additionalProperties": False,
    },
)

_DEFAULT_WHITELIST = frozenset({
    "pwd",
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    "find",
    "echo",
    "date",
    "env",
    "sort",
    "uniq",
    "cut",
    "tr",
    "diff",
    "file",
})

_DEFAULT_BLACKLIST_PATTERNS = (
    r"\brm\s+-[^\s]*r",
    r"\brm\s+-[^\s]*f",
    r"\bsudo\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bmkfs\b",
    r"\bdd\b",
    r">\s*/dev/",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bkill\b",
    r"\bkillall\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bsystemctl\b",
)


@dataclass(frozen=True, slots=True)
class ShellConfig:
    sandbox_dir: str = "./sandbox"
    default_timeout_seconds: float = 30.0
    max_timeout_seconds: float = 120.0
    default_max_chars: int = 10000
    max_max_chars: int = 50000
    whitelist: frozenset[str] = _DEFAULT_WHITELIST
    blacklist_patterns: tuple[str, ...] = _DEFAULT_BLACKLIST_PATTERNS
    minimal_env: dict[str, str] = field(default_factory=lambda: {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "LANG": "en_US.UTF-8",
    })

    def __post_init__(self) -> None:
        if self.default_timeout_seconds <= 0:
            raise ValueError(
                f"default_timeout_seconds must be > 0, got {self.default_timeout_seconds}"
            )
        if self.max_timeout_seconds < self.default_timeout_seconds:
            raise ValueError(
                f"max_timeout_seconds ({self.max_timeout_seconds}) "
                f"must be >= default_timeout_seconds ({self.default_timeout_seconds})"
            )
        if self.default_max_chars <= 0:
            raise ValueError(
                f"default_max_chars must be > 0, got {self.default_max_chars}"
            )
        if self.max_max_chars < self.default_max_chars:
            raise ValueError(
                f"max_max_chars ({self.max_max_chars}) "
                f"must be >= default_max_chars ({self.default_max_chars})"
            )
        if not self.sandbox_dir.strip():
            raise ValueError("sandbox_dir must not be blank")

        for pattern in self.blacklist_patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    f"Invalid blacklist pattern {pattern!r}: {exc}"
                ) from exc


class ShellTool(BaseTool):
    """Sandboxed command execution via subprocess_exec."""

    def __init__(self, config: ShellConfig | None = None) -> None:
        self._config = config or ShellConfig()
        self._blacklist_compiled = [
            re.compile(pattern) for pattern in self._config.blacklist_patterns
        ]
        self._sandbox_path = Path(self._config.sandbox_dir).expanduser().resolve()
        self._sandbox_path.mkdir(parents=True, exist_ok=True)

    @property
    def spec(self) -> ToolSpec:
        return _SPEC

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        argv = arguments.get("argv")
        if not isinstance(argv, list) or not argv:
            raise ArgumentValidationError("'argv' must be a non-empty list of strings")

        for i, item in enumerate(argv):
            if not isinstance(item, str) or not item.strip():
                raise ArgumentValidationError(
                    f"'argv[{i}]' must be a non-empty string"
                )

        cwd = arguments.get("cwd")
        if cwd is not None:
            if not isinstance(cwd, str) or not cwd.strip():
                raise ArgumentValidationError("'cwd' must be a non-empty string")
            if Path(cwd).is_absolute():
                raise ArgumentValidationError("'cwd' must be relative to the sandbox root")

        timeout = arguments.get("timeout_seconds")
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise ArgumentValidationError("'timeout_seconds' must be a number")
            if timeout <= 0:
                raise ArgumentValidationError("'timeout_seconds' must be > 0")
            if timeout > self._config.max_timeout_seconds:
                raise ArgumentValidationError(
                    f"'timeout_seconds' must be <= {self._config.max_timeout_seconds}"
                )

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

        confirmed = arguments.get("confirmed")
        if confirmed is not None and not isinstance(confirmed, bool):
            raise ArgumentValidationError("'confirmed' must be a boolean")

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        argv = [item.strip() for item in arguments["argv"]]
        confirmed = arguments.get("confirmed", False)
        timeout = arguments.get(
            "timeout_seconds", self._config.default_timeout_seconds,
        )
        max_chars = arguments.get(
            "max_chars", self._config.default_max_chars,
        )

        cwd = self._resolve_cwd(arguments.get("cwd"))
        self._check_whitelist(argv[0])

        full_command = " ".join(argv)
        blacklist_match = self._check_blacklist(full_command)

        if blacklist_match is not None and not confirmed:
            return {
                "status": "REQUIRES_CONFIRMATION",
                "argv": argv,
                "reason": f"Command matched blacklist rule: {blacklist_match}",
                "message": (
                    "This command requires user confirmation before execution. "
                    "Re-invoke with confirmed=true after obtaining approval."
                ),
            }

        if blacklist_match is not None:
            logger.warning(
                "Executing blacklisted command after confirmation: %s (rule: %s)",
                argv,
                blacklist_match,
            )

        return await self._execute(argv, cwd, timeout, max_chars)

    def _resolve_cwd(self, cwd_arg: str | None) -> Path:
        if cwd_arg is None:
            return self._sandbox_path

        requested = (self._sandbox_path / cwd_arg).expanduser().resolve()

        try:
            requested.relative_to(self._sandbox_path)
        except ValueError:
            raise VariPawToolError(
                ErrorEnvelope(
                    code="VALIDATION_ERROR",
                    message=f"'cwd' must be within sandbox: {self._sandbox_path}",
                    retriable=False,
                    details={
                        "requested": str(requested),
                        "sandbox": str(self._sandbox_path),
                    },
                )
            )

        if not requested.is_dir():
            raise VariPawToolError(
                ErrorEnvelope(
                    code="VALIDATION_ERROR",
                    message=f"'cwd' directory does not exist: {requested}",
                    retriable=False,
                    details={"requested": str(requested)},
                )
            )

        return requested

    def _check_whitelist(self, base_command: str) -> None:
        cmd = base_command.split("/")[-1]
        if cmd not in self._config.whitelist:
            raise VariPawToolError(
                ErrorEnvelope(
                    code="VALIDATION_ERROR",
                    message=f"Command {cmd!r} is not in the whitelist",
                    retriable=False,
                    details={
                        "base_command": cmd,
                        "whitelist": sorted(self._config.whitelist),
                    },
                )
            )

    def _check_blacklist(self, full_command: str) -> str | None:
        for pattern in self._blacklist_compiled:
            if pattern.search(full_command):
                return pattern.pattern
        return None

    async def _execute(
        self,
        argv: list[str],
        cwd: Path,
        timeout: float,
        max_chars: int,
    ) -> dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env=self._config.minimal_env,
            )
        except FileNotFoundError as exc:
            raise VariPawToolError(
                ErrorEnvelope(
                    code="TOOL_EXEC_ERROR",
                    message=f"Command not found: {argv[0]}",
                    retriable=False,
                    details={"argv": argv, "cwd": str(cwd)},
                )
            ) from exc
        except OSError as exc:
            raise VariPawToolError(
                ErrorEnvelope(
                    code="TOOL_EXEC_ERROR",
                    message=f"Failed to start process: {exc}",
                    retriable=False,
                    details={
                        "argv": argv,
                        "cwd": str(cwd),
                        "exception_type": type(exc).__name__,
                    },
                )
            ) from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except TimeoutError as exc:
            proc.kill()
            try:
                await asyncio.wait_for(proc.communicate(), timeout=5.0)
            except TimeoutError:
                pass
            raise VariPawToolError(
                ErrorEnvelope(
                    code="TOOL_TIMEOUT",
                    message=f"Command timed out after {timeout}s",
                    retriable=True,
                    details={
                        "argv": argv,
                        "cwd": str(cwd),
                        "timeout_seconds": timeout,
                    },
                )
            ) from exc

        stdout = self._truncate_output(self._decode(stdout_bytes), max_chars)
        stderr = self._truncate_output(self._decode(stderr_bytes), max_chars)
        exit_code = proc.returncode if proc.returncode is not None else -1

        logger.debug(
            "shell argv=%r exit_code=%d stdout_len=%d stderr_len=%d",
            argv,
            exit_code,
            len(stdout),
            len(stderr),
        )

        return {
            "argv": argv,
            "cwd": str(cwd),
            "exit_code": exit_code,
            "command_succeeded": exit_code == 0,
            "stdout": stdout,
            "stderr": stderr,
        }

    @staticmethod
    def _decode(data: bytes) -> str:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace")

    @staticmethod
    def _truncate_output(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "\n...[truncated]..."