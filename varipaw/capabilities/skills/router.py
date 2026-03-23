from __future__ import annotations

from dataclasses import dataclass

from varipaw.capabilities.skills.base import SkillDefinition, SkillProvider
from varipaw.capabilities.skills.store import SkillStore


@dataclass(frozen=True, slots=True)
class SkillRouterConfig:
    max_skills: int = 3

    def __post_init__(self) -> None:
        if self.max_skills <= 0:
            raise ValueError("max_skills must be > 0")


class KeywordSkillRouter(SkillProvider):
    def __init__(self, store: SkillStore, config: SkillRouterConfig | None = None) -> None:
        self._store = store
        self._config = config or SkillRouterConfig()

    async def select_for_user_text(self, user_text: str, limit: int = 3) -> list[SkillDefinition]:
        query = user_text.strip().lower()
        max_count = min(limit, self._config.max_skills)
        if max_count <= 0:
            return []
        skills = self._store.list_skills()
        always_skills = [skill for skill in skills if skill.always]
        result: list[SkillDefinition] = always_skills[:max_count]
        if len(result) >= max_count:
            return result
        if not query:
            return result
        scored: list[tuple[int, SkillDefinition]] = []
        always_names = {skill.name for skill in always_skills}
        for skill in skills:
            if skill.name in always_names:
                continue
            score = self._score(query, skill)
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda item: item[0], reverse=True)
        for _, skill in scored:
            if len(result) >= max_count:
                break
            result.append(skill)
        return result

    def _score(self, query: str, skill: SkillDefinition) -> int:
        score = 0
        for trigger in skill.triggers:
            if trigger and trigger in query:
                score += 3
        for word in skill.name.lower().split():
            if word and word in query:
                score += 2
        for word in skill.description.lower().split():
            if word and word in query:
                score += 1
        return score
