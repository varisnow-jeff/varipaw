from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    name: str
    description: str
    content: str
    triggers: tuple[str, ...] = field(default_factory=tuple)
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    always: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("skill name must not be blank")
        if not self.description.strip():
            raise ValueError("skill description must not be blank")
        if not self.content.strip():
            raise ValueError("skill content must not be blank")
        if not isinstance(self.metadata, dict):
            raise ValueError("skill metadata must be a dict")

    def render(self) -> str:
        trigger_text = ", ".join(self.triggers) if self.triggers else "none"
        return (
            f"Skill: {self.name}\n"
            f"Description: {self.description}\n"
            f"Triggers: {trigger_text}\n"
            f"Guidance:\n{self.content.strip()}"
        )


class SkillProvider(ABC):
    @abstractmethod
    async def select_for_user_text(self, user_text: str, limit: int = 3) -> list[SkillDefinition]:
        ...
