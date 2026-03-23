"""Core ReAct loop for VariPaw."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, replace
from typing import Any, Protocol, runtime_checkable

from varipaw.capabilities.memory.base import MemoryContext
from varipaw.capabilities.tools.registry import ToolRegistry
from varipaw.core.contracts import (
    AgentResponse,
    AgentStep,
    ToolCall,
    ToolResult,
    UserMessage,
)
from varipaw.core.policies import LoopPolicy, PolicySet
from varipaw.core.provider import (
    AssistantMessage,
    BaseProvider,
    HumanMessage,
    LLMResponse,
    Message,
    ProviderError,
    SystemMessage,
    ToolResultMessage,
)
from varipaw.runtime.errors import tool_exec_error, tool_timeout, validation_error
from varipaw.runtime.logger import LogContext, log_event, setup_logger
from varipaw.runtime.replay import ReplayStore
from varipaw.runtime.trace import TraceCollector

__all__ = [
    "LoopConfig",
    "AgentLoop",
    "SupportsMemory",
    "SupportsReplayStore",
    "SupportsSkills",
]

logger = logging.getLogger(__name__)

_CONFIRMATION_REQUIRED_STATUS = "REQUIRES_CONFIRMATION"
_CONFIRMATION_REQUIRED_OBSERVATION = "confirmation required"


@runtime_checkable
class SupportsReplayStore(Protocol):
    def add(self, response: AgentResponse) -> None: ...


@runtime_checkable
class SupportsMemory(Protocol):
    async def build_context(self, user_message: UserMessage) -> MemoryContext: ...

    async def remember_turn(
        self,
        user_message: UserMessage,
        response: AgentResponse,
    ) -> None: ...


@runtime_checkable
class SupportsSkills(Protocol):
    async def select_for_user_text(self, user_text: str, limit: int = 3) -> list[Any]: ...


@dataclass(frozen=True, slots=True)
class LoopConfig:
    max_steps: int = 6
    system_prompt: str = (
        "You are VariPaw, a helpful tool-using assistant. "
        "Use tools when you need up-to-date web information or need to read a webpage in detail. "
        "Use web_search to find relevant pages, and use web_reader to read a specific page."
    )
    provider_failure_text: str = "抱歉，我现在暂时无法完成这个请求，请稍后再试。"
    max_steps_text: str = "抱歉，我暂时没能在步数限制内完成这个请求。"
    include_thought_in_steps: bool = True

    def __post_init__(self) -> None:
        if self.max_steps <= 0:
            raise ValueError(f"max_steps must be > 0, got {self.max_steps}")
        if not self.system_prompt.strip():
            raise ValueError("system_prompt must not be blank")


class AgentLoop:
    """Minimal ReAct loop for a single agent run."""

    def __init__(
        self,
        *,
        provider: BaseProvider,
        tool_registry: ToolRegistry,
        config: LoopConfig | None = None,
        memory: SupportsMemory | None = None,
        policies: PolicySet | None = None,
        runtime_logger: logging.Logger | None = None,
        replay_store: SupportsReplayStore | None = None,
        skills: SupportsSkills | None = None,
    ) -> None:
        self._provider = provider
        self._tool_registry = tool_registry
        self._config = config or LoopConfig()
        self._policies = policies or PolicySet(
            loop=LoopPolicy(
                max_steps=self._config.max_steps,
                include_thought_in_steps=self._config.include_thought_in_steps,
            )
        )
        self._config = replace(
            self._config,
            max_steps=self._policies.loop.max_steps,
            include_thought_in_steps=self._policies.loop.include_thought_in_steps,
        )
        self._memory = memory
        self._skills = skills
        self._runtime_logger = runtime_logger or setup_logger("varipaw.runtime.loop")
        self._replay_store = replay_store or ReplayStore()

    async def run(self, user_message: UserMessage) -> AgentResponse:
        trace = TraceCollector.start(session_id=user_message.session_id)
        history = await self._build_initial_history(user_message)
        return await self._continue_loop(
            user_message=user_message,
            trace=trace,
            history=history,
            steps=[],
            start_step_index=0,
        )

    async def resume_confirmed_tool(
        self,
        *,
        user_message: UserMessage,
        original_call: ToolCall,
    ) -> AgentResponse:
        trace = TraceCollector.start(session_id=user_message.session_id)

        confirmed_arguments = dict(original_call.arguments)
        confirmed_arguments["confirmed"] = True
        confirmed_call = ToolCall(
            call_id=original_call.call_id,
            name=original_call.name,
            arguments=confirmed_arguments,
        )

        history = await self._build_initial_history(user_message)
        steps: list[AgentStep] = []

        history.append(
            self._assistant_tool_call_message(
                confirmed_call,
                thought=None,
            )
        )

        tool_result, tool_ms = await self._dispatch_tool(confirmed_call)

        if self._is_confirmation_required(tool_result):
            step = self._make_step(
                trace_id=trace.trace_id,
                session_id=user_message.session_id,
                step_index=0,
                llm=None,
                action=confirmed_call,
                observation=_CONFIRMATION_REQUIRED_OBSERVATION,
                duration_ms=tool_ms,
                error_code=None,
            )
            steps.append(step)
            trace.add_from_agent_step(step)
            return await self._finish(
                user_message,
                self._confirmation_response(
                    trace_id=trace.trace_id,
                    steps=steps,
                    tool_call=confirmed_call,
                    tool_result=tool_result,
                ),
            )

        history.append(self._tool_result_message(confirmed_call, tool_result))

        step = self._make_step(
            trace_id=trace.trace_id,
            session_id=user_message.session_id,
            step_index=0,
            llm=None,
            action=confirmed_call,
            observation=self._summarize_tool_result(confirmed_call, tool_result),
            duration_ms=tool_ms,
            error_code=tool_result.error.code if not tool_result.ok and tool_result.error else None,
        )
        steps.append(step)
        trace.add_from_agent_step(step)

        return await self._continue_loop(
            user_message=user_message,
            trace=trace,
            history=history,
            steps=steps,
            start_step_index=1,
        )

    async def _continue_loop(
        self,
        *,
        user_message: UserMessage,
        trace: TraceCollector,
        history: list[Message],
        steps: list[AgentStep],
        start_step_index: int,
    ) -> AgentResponse:
        trace_id = trace.trace_id

        logger.info(
            "Starting agent loop trace_id=%s session_id=%s max_steps=%d start_step=%d",
            trace_id,
            user_message.session_id,
            self._config.max_steps,
            start_step_index,
        )

        for step_index in range(start_step_index, self._config.max_steps):
            try:
                llm = await self._provider.generate(
                    history,
                    self._tool_registry.list_schemas(),
                )
            except ProviderError as exc:
                logger.warning(
                    "Provider failed trace_id=%s step=%d code=%s",
                    trace_id,
                    step_index,
                    exc.envelope.code,
                )
                step = self._make_step(
                    trace_id=trace_id,
                    session_id=user_message.session_id,
                    step_index=step_index,
                    llm=None,
                    action=None,
                    observation=exc.envelope.message,
                    duration_ms=0,
                    error_code=exc.envelope.code,
                )
                steps.append(step)
                trace.add_from_agent_step(step)
                return await self._finish(
                    user_message,
                    self._provider_failure_response(trace_id=trace_id, steps=steps),
                )

            if llm.is_text:
                step = self._make_step(
                    trace_id=trace_id,
                    session_id=user_message.session_id,
                    step_index=step_index,
                    llm=llm,
                    action=None,
                    observation=None,
                    duration_ms=llm.duration_ms or 0,
                    error_code=None,
                )
                steps.append(step)
                trace.add_from_agent_step(step)

                logger.info(
                    "Agent loop finished trace_id=%s session_id=%s steps=%d",
                    trace_id,
                    user_message.session_id,
                    len(steps),
                )
                return await self._finish(
                    user_message,
                    AgentResponse(
                        trace_id=trace_id,
                        text=llm.text,
                        steps=tuple(steps),
                    ),
                )

            tool_call = llm.tool_call
            if tool_call is None:
                logger.error(
                    "Invalid LLMResponse trace_id=%s step=%d: neither text nor tool_call",
                    trace_id,
                    step_index,
                )
                step = self._make_step(
                    trace_id=trace_id,
                    session_id=user_message.session_id,
                    step_index=step_index,
                    llm=llm,
                    action=None,
                    observation="Provider returned neither text nor tool call",
                    duration_ms=llm.duration_ms or 0,
                    error_code="INTERNAL_ERROR",
                )
                steps.append(step)
                trace.add_from_agent_step(step)
                return await self._finish(
                    user_message,
                    self._provider_failure_response(trace_id=trace_id, steps=steps),
                )

            history.append(self._assistant_tool_call_message(tool_call, llm.thought))

            tool_result, tool_ms = await self._dispatch_tool(tool_call)

            if self._is_confirmation_required(tool_result):
                step = self._make_step(
                    trace_id=trace_id,
                    session_id=user_message.session_id,
                    step_index=step_index,
                    llm=llm,
                    action=tool_call,
                    observation=_CONFIRMATION_REQUIRED_OBSERVATION,
                    duration_ms=(llm.duration_ms or 0) + tool_ms,
                    error_code=None,
                )
                steps.append(step)
                trace.add_from_agent_step(step)
                return await self._finish(
                    user_message,
                    self._confirmation_response(
                        trace_id=trace_id,
                        steps=steps,
                        tool_call=tool_call,
                        tool_result=tool_result,
                    ),
                )

            history.append(self._tool_result_message(tool_call, tool_result))

            step = self._make_step(
                trace_id=trace_id,
                session_id=user_message.session_id,
                step_index=step_index,
                llm=llm,
                action=tool_call,
                observation=self._summarize_tool_result(tool_call, tool_result),
                duration_ms=(llm.duration_ms or 0) + tool_ms,
                error_code=tool_result.error.code if not tool_result.ok and tool_result.error else None,
            )
            steps.append(step)
            trace.add_from_agent_step(step)

            logger.debug(
                "Completed tool step trace_id=%s step=%d tool=%s ok=%s",
                trace_id,
                step_index,
                tool_call.name,
                tool_result.ok,
            )

        logger.warning(
            "Agent loop hit max steps trace_id=%s session_id=%s max_steps=%d",
            trace_id,
            user_message.session_id,
            self._config.max_steps,
        )
        return await self._finish(
            user_message,
            self._max_steps_response(trace_id=trace_id, steps=steps),
        )

    async def _dispatch_tool(self, tool_call: ToolCall) -> tuple[ToolResult, int]:
        t0 = time.monotonic()
        tool_policy = self._policies.tool_policy_for(tool_call.name)
        if not tool_policy.is_allowed(tool_call.name):
            tool_result = ToolResult(
                call_id=tool_call.call_id,
                ok=False,
                data=None,
                error=validation_error(
                    f"Tool not allowed by policy: {tool_call.name}",
                    retriable=False,
                    details={"tool": tool_call.name},
                ),
            )
            tool_ms = int((time.monotonic() - t0) * 1000)
            return tool_result, tool_ms

        attempts = 0
        tool_result: ToolResult
        while True:
            attempts += 1
            try:
                tool_result = await asyncio.wait_for(
                    self._tool_registry.dispatch(tool_call),
                    timeout=tool_policy.timeout_seconds,
                )
            except asyncio.TimeoutError:
                tool_result = ToolResult(
                    call_id=tool_call.call_id,
                    ok=False,
                    data=None,
                    error=tool_timeout(
                        tool_name=tool_call.name,
                        timeout_ms=int(tool_policy.timeout_seconds * 1000),
                    ),
                )
            except Exception as exc:
                logger.exception(
                    "Unexpected error dispatching tool %s",
                    tool_call.name,
                )
                tool_result = ToolResult(
                    call_id=tool_call.call_id,
                    ok=False,
                    data=None,
                    error=tool_exec_error(
                        tool_name=tool_call.name,
                        reason=f"Unexpected dispatch error: {exc}",
                        retriable=False,
                        details={"exception_type": type(exc).__name__},
                    ),
                )

            error_code = tool_result.error.code if not tool_result.ok and tool_result.error else None
            if not self._policies.retry.should_retry(error_code, attempts):
                break
            if self._policies.retry.backoff_seconds > 0:
                await asyncio.sleep(self._policies.retry.backoff_seconds)

        tool_ms = int((time.monotonic() - t0) * 1000)
        return tool_result, tool_ms

    async def _build_initial_history(self, user_message: UserMessage) -> list[Message]:
        system_prompt = self._config.system_prompt
        tz_offset = int(os.environ.get("TZ_OFFSET", "8"))
        tz = timezone(timedelta(hours=tz_offset))
        now_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M %A")
        
        system_prompt = (
            f"{system_prompt}\n\n"
            f"Current time: {now_str} (UTC+{tz_offset}). "
            f"You already know the current time. Do NOT use web_search to look up the current time."
        )

        skills_text = await self._render_skills_for_prompt(user_message.text)
        if skills_text:
            system_prompt = f"{system_prompt}\n\nRelevant skills:\n{skills_text}"

        memory_context = await self._get_memory_context(user_message)
        if memory_context is not None:
            memory_text = self._render_memory_context(memory_context)
            if memory_text:
                system_prompt = f"{system_prompt}\n\nRelevant memory:\n{memory_text}"

        return [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message.text),
        ]

    async def _render_skills_for_prompt(self, user_text: str) -> str:
        if self._skills is None:
            return ""
        try:
            selected = await self._skills.select_for_user_text(user_text, limit=3)
        except Exception:
            logger.exception("skills.select_for_user_text failed")
            return ""
        rendered: list[str] = []
        for item in selected:
            render = getattr(item, "render", None)
            if callable(render):
                text = str(render()).strip()
                if text:
                    rendered.append(text)
                continue
            content = str(getattr(item, "content", "")).strip()
            if content:
                rendered.append(content)
        return "\n\n".join(rendered).strip()

    async def _get_memory_context(
        self,
        user_message: UserMessage,
    ) -> MemoryContext | None:
        if self._memory is None:
            return None

        try:
            value = await self._memory.build_context(user_message)
        except Exception:
            logger.exception("memory.build_context failed")
            return None

        if not isinstance(value, MemoryContext):
            logger.warning(
                "memory.build_context returned non-MemoryContext: %s",
                type(value).__name__,
            )
            return None

        if value.is_empty():
            return None

        return value

    def _render_memory_context(self, ctx: MemoryContext) -> str:
        sections: list[str] = []

        if ctx.recent_turns:
            lines = ["Recent conversation:"]
            for turn in ctx.recent_turns:
                lines.append(f"- User: {turn.user_text}")
                lines.append(f"  Assistant: {turn.assistant_text}")
            sections.append("\n".join(lines))

        if ctx.semantic_hits:
            lines = ["Relevant long-term memory:"]
            for hit in ctx.semantic_hits:
                lines.append(f"- ({hit.score:.3f}) {hit.text}")
            sections.append("\n".join(lines))

        non_empty_notes = [note for note in ctx.notes if note.strip()]
        if non_empty_notes:
            lines = ["Notes:"]
            lines.extend(f"- {note}" for note in non_empty_notes)
            sections.append("\n".join(lines))

        return "\n\n".join(sections).strip()

    async def _remember_turn(
        self,
        user_message: UserMessage,
        response: AgentResponse,
    ) -> None:
        if self._memory is None:
            return

        try:
            await self._memory.remember_turn(user_message, response)
        except Exception:
            logger.exception("memory.remember_turn failed")

    async def _finish(
        self,
        user_message: UserMessage,
        response: AgentResponse,
    ) -> AgentResponse:
        await self._remember_turn(user_message, response)
        self._replay_store.add(response)
        log_event(
            self._runtime_logger,
            logging.INFO,
            "agent_finish",
            context=LogContext(
                trace_id=response.trace_id,
                step_index=len(response.steps),
            ),
            extra={"session_id": user_message.session_id},
        )
        return response

    def _assistant_tool_call_message(
        self,
        tool_call: ToolCall,
        thought: str | None,
    ) -> AssistantMessage:
        payload = {
            "id": tool_call.call_id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
            },
        }
        return AssistantMessage(
            content=thought or "",
            tool_calls=[payload],
        )

    def _tool_result_to_message_content(self, result: ToolResult) -> str:
        if result.ok:
            payload: dict[str, Any] = {"ok": True, "data": result.data}
        else:
            payload = {
                "ok": False,
                "error": result.error.to_dict() if result.error else None,
            }
        return json.dumps(payload, ensure_ascii=False)

    def _tool_result_message(
        self,
        tool_call: ToolCall,
        result: ToolResult,
    ) -> ToolResultMessage:
        return ToolResultMessage(
            tool_name=tool_call.name,
            call_id=tool_call.call_id,
            content=self._tool_result_to_message_content(result),
        )

    def _is_confirmation_required(self, result: ToolResult) -> bool:
        return (
            result.ok
            and isinstance(result.data, dict)
            and result.data.get("status") == _CONFIRMATION_REQUIRED_STATUS
        )

    def _confirmation_response(
        self,
        *,
        trace_id: str,
        steps: list[AgentStep],
        tool_call: ToolCall,
        tool_result: ToolResult,
    ) -> AgentResponse:
        reason = "This command requires confirmation."
        command_preview = tool_call.name

        if isinstance(tool_result.data, dict):
            raw_reason = tool_result.data.get("reason")
            if isinstance(raw_reason, str) and raw_reason.strip():
                reason = raw_reason.strip()

            argv = tool_result.data.get("argv")
            if isinstance(argv, list) and argv:
                try:
                    command_preview = " ".join(str(x) for x in argv)
                except Exception:
                    command_preview = tool_call.name

        return AgentResponse(
            trace_id=trace_id,
            text=(
                "该命令需要确认后才能执行。\n"
                f"命令: {command_preview}\n"
                f"原因: {reason}\n"
                "请输入 yes 确认，或输入 no 取消。"
            ),
            steps=tuple(steps),
        )

    def _summarize_tool_result(
        self,
        tool_call: ToolCall,
        result: ToolResult,
    ) -> str:
        if result.ok:
            if isinstance(result.data, dict):
                keys = sorted(result.data.keys())
                return f"tool {tool_call.name} succeeded keys={keys}"
            if result.data is None:
                return f"tool {tool_call.name} succeeded (no data)"
            return f"tool {tool_call.name} succeeded"

        code = result.error.code if result.error else "UNKNOWN"
        msg = result.error.message if result.error else "unknown"
        return f"tool {tool_call.name} failed: {code} — {msg}"

    def _make_step(
        self,
        *,
        trace_id: str,
        session_id: str,
        step_index: int,
        llm: LLMResponse | None,
        action: ToolCall | None,
        observation: str | None,
        duration_ms: int,
        error_code: str | None,
    ) -> AgentStep:
        thought = None
        token_in = None
        token_out = None

        if llm is not None:
            thought = llm.thought if self._config.include_thought_in_steps else None
            token_in = llm.token_in
            token_out = llm.token_out

        step = AgentStep(
            trace_id=trace_id,
            session_id=session_id,
            step_index=step_index,
            thought=thought,
            action=action,
            observation=observation,
            duration_ms=duration_ms,
            token_in=token_in,
            token_out=token_out,
            error_code=error_code,
        )
        log_event(
            self._runtime_logger,
            logging.INFO,
            "agent_step",
            context=LogContext(
                trace_id=trace_id,
                step_index=step_index,
                duration_ms=duration_ms,
                error_code=error_code,
            ),
            extra={"session_id": session_id, "action": action.name if action else None},
        )
        return step

    def _provider_failure_response(
        self,
        *,
        trace_id: str,
        steps: list[AgentStep],
    ) -> AgentResponse:
        return AgentResponse(
            trace_id=trace_id,
            text=self._config.provider_failure_text,
            steps=tuple(steps),
        )

    def _max_steps_response(
        self,
        *,
        trace_id: str,
        steps: list[AgentStep],
    ) -> AgentResponse:
        return AgentResponse(
            trace_id=trace_id,
            text=self._config.max_steps_text,
            steps=tuple(steps),
        )
