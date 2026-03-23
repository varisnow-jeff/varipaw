from __future__ import annotations

import json
import os
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from varipaw.capabilities.skills.base import SkillDefinition

_FRONTMATTER_RE = re.compile(r"^---\n(?P<meta>[\s\S]*?)\n---\n?(?P<body>[\s\S]*)$", re.MULTILINE)


class SkillStore(ABC):
    @abstractmethod
    def list_skills(self) -> list[SkillDefinition]:
        ...


class FileSkillStore(SkillStore):
    def __init__(self, directories: list[Path] | tuple[Path, ...]) -> None:
        self._directories = tuple(directories)

    def list_skills(self) -> list[SkillDefinition]:
        result: list[SkillDefinition] = []
        seen: set[str] = set()
        for directory in self._directories:
            if not directory.exists() or not directory.is_dir():
                continue
            for path in self._iter_skill_files(directory):
                try:
                    skill = self._load_skill_file(path)
                except Exception:
                    continue
                if not self._check_requirements(skill.metadata):
                    continue
                if skill.name in seen:
                    continue
                seen.add(skill.name)
                result.append(skill)
        return result

    def _iter_skill_files(self, directory: Path) -> list[Path]:
        candidates: set[Path] = set()
        for path in directory.glob("*.md"):
            if path.is_file():
                candidates.add(path)
        for path in directory.rglob("SKILL.md"):
            if path.is_file():
                candidates.add(path)
        return sorted(candidates)

    def _load_skill_file(self, path: Path) -> SkillDefinition:
        raw = path.read_text(encoding="utf-8")
        matched = _FRONTMATTER_RE.match(raw)
        metadata: dict[str, str] = {}
        body = raw
        if matched:
            metadata = self._parse_meta(matched.group("meta"))
            body = matched.group("body")
        name = metadata.get("name", path.stem).strip()
        description = metadata.get("description", "").strip()
        if not description:
            description = f"Skill from {path.name}"
        triggers_value = metadata.get("triggers", "").strip()
        triggers = tuple(part.strip().lower() for part in triggers_value.split(",") if part.strip())
        raw_meta = metadata.get("metadata", "").strip()
        parsed_meta = self._parse_nanobot_metadata(raw_meta) if raw_meta else {}
        always = self._to_bool(metadata.get("always", "").strip()) or bool(parsed_meta.get("always", False))
        return SkillDefinition(
            name=name,
            description=description,
            content=body.strip(),
            triggers=triggers,
            source=str(path),
            metadata=parsed_meta,
            always=always,
        )

    def _parse_meta(self, text: str) -> dict[str, str]:
        parsed: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            parsed[key.strip().lower()] = value.strip().strip("\"'")
        return parsed

    def _parse_nanobot_metadata(self, raw: str) -> dict[str, Any]:
        try:
            data = json.loads(raw)
            return data.get("nanobot", data.get("openclaw", {})) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def _check_requirements(self, meta: dict[str, Any]) -> bool:
        requires = meta.get("requires", {})
        if not isinstance(requires, dict):
            return True
        bins = requires.get("bins", [])
        if isinstance(bins, list):
            for b in bins:
                if isinstance(b, str) and b and not shutil.which(b):
                    return False
        envs = requires.get("env", [])
        if isinstance(envs, list):
            for env in envs:
                if isinstance(env, str) and env and not os.environ.get(env):
                    return False
        return True

    def _to_bool(self, value: str) -> bool:
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
