from __future__ import annotations

from dataclasses import dataclass

from varipaw.core.contracts import AgentResponse
from varipaw.core.validation import require_non_empty_str
from varipaw.runtime.trace import TraceRecord, TraceStepRecord


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    trace_id: str
    response_text: str
    step_count: int
    created_at: str


def response_to_trace_record(
    response: AgentResponse,
    *,
    session_id: str | None = None,
) -> TraceRecord:
    if not isinstance(response, AgentResponse):
        raise TypeError("response must be an AgentResponse")
    if session_id is not None:
        session_id = require_non_empty_str(session_id, "session_id")

    steps = tuple(
        TraceStepRecord.from_agent_step(step)
        for step in response.steps
    )
    return TraceRecord(
        trace_id=response.trace_id,
        session_id=session_id,
        steps=steps,
    )


class ReplayStore:
    def __init__(self) -> None:
        self._responses: dict[str, AgentResponse] = {}

    def add(self, response: AgentResponse) -> None:
        if not isinstance(response, AgentResponse):
            raise TypeError("response must be an AgentResponse")
        self._responses[response.trace_id] = response

    def get(self, trace_id: str) -> AgentResponse | None:
        trace_id = require_non_empty_str(trace_id, "trace_id")
        return self._responses.get(trace_id)

    def list_trace_ids(self) -> list[str]:
        return sorted(self._responses.keys())

    def snapshot(self, trace_id: str) -> ReplaySnapshot | None:
        trace_id = require_non_empty_str(trace_id, "trace_id")
        response = self._responses.get(trace_id)
        if response is None:
            return None

        return ReplaySnapshot(
            trace_id=response.trace_id,
            response_text=response.text,
            step_count=len(response.steps),
            created_at=response.created_at,
        )

    def clear(self) -> None:
        self._responses.clear()
