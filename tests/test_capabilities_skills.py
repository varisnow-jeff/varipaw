import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from varipaw.capabilities.skills.base import SkillDefinition
from varipaw.capabilities.skills.router import KeywordSkillRouter, SkillRouterConfig
from varipaw.capabilities.skills.store import FileSkillStore


class TestCapabilitiesSkills(unittest.TestCase):
    def test_file_skill_store_loads_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "time.md"
            path.write_text(
                "---\n"
                "name: time-helper\n"
                "description: answer current time questions\n"
                "triggers: time, clock, now\n"
                "---\n"
                "Use local clock and avoid web search.\n",
                encoding="utf-8",
            )
            store = FileSkillStore([Path(tmp)])
            skills = store.list_skills()
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].name, "time-helper")
        self.assertEqual(skills[0].triggers, ("time", "clock", "now"))

    def test_file_skill_store_supports_nested_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "weather"
            nested.mkdir(parents=True, exist_ok=True)
            path = nested / "SKILL.md"
            path.write_text(
                "---\n"
                "name: weather\n"
                "description: weather helper\n"
                "triggers: weather, forecast\n"
                "---\n"
                "Use weather skill.\n",
                encoding="utf-8",
            )
            store = FileSkillStore([Path(tmp)])
            skills = store.list_skills()
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].name, "weather")

    def test_parse_nanobot_metadata(self) -> None:
        store = FileSkillStore([])
        meta = store._parse_nanobot_metadata('{"nanobot":{"requires":{"bins":["curl"]}}}')
        self.assertIn("requires", meta)
        meta2 = store._parse_nanobot_metadata('{"openclaw":{"always":true}}')
        self.assertEqual(meta2.get("always"), True)
        self.assertEqual(store._parse_nanobot_metadata("bad"), {})

    def test_store_filters_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.md"
            path.write_text(
                "---\n"
                "name: x\n"
                "description: d\n"
                "metadata: {\"nanobot\":{\"requires\":{\"bins\":[\"nonexistent_bin_abc\"]}}}\n"
                "---\n"
                "body\n",
                encoding="utf-8",
            )
            store = FileSkillStore([Path(tmp)])
            skills = store.list_skills()
        self.assertEqual(skills, [])

    def test_store_accepts_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.md"
            path.write_text(
                "---\n"
                "name: x\n"
                "description: d\n"
                "metadata: {\"nanobot\":{\"requires\":{\"bins\":[],\"env\":[\"X_ENV\"]}}}\n"
                "---\n"
                "body\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"X_ENV": "1"}, clear=False):
                store = FileSkillStore([Path(tmp)])
                skills = store.list_skills()
        self.assertEqual(len(skills), 1)

    def test_keyword_router_selects_relevant_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "time.md").write_text(
                "---\nname: time-helper\ndescription: answer time\ntriggers: time, now\n---\nUse local time.\n",
                encoding="utf-8",
            )
            Path(tmp, "code.md").write_text(
                "---\nname: code-helper\ndescription: code review\ntriggers: review, refactor\n---\nReview code.\n",
                encoding="utf-8",
            )
            router = KeywordSkillRouter(
                FileSkillStore([Path(tmp)]),
                SkillRouterConfig(max_skills=2),
            )
            selected = asyncio.run(router.select_for_user_text("what time is it now?", limit=2))
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].name, "time-helper")

    def test_keyword_router_includes_always_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "always.md").write_text(
                "---\nname: always-one\ndescription: always\nalways: true\n---\nAlways skill.\n",
                encoding="utf-8",
            )
            Path(tmp, "time.md").write_text(
                "---\nname: time-helper\ndescription: answer time\ntriggers: time\n---\nUse local time.\n",
                encoding="utf-8",
            )
            router = KeywordSkillRouter(FileSkillStore([Path(tmp)]), SkillRouterConfig(max_skills=3))
            selected = asyncio.run(router.select_for_user_text("hello", limit=3))
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].name, "always-one")

    def test_keyword_router_includes_always_and_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "always.md").write_text(
                "---\nname: always-one\ndescription: always\nalways: true\n---\nAlways skill.\n",
                encoding="utf-8",
            )
            Path(tmp, "time.md").write_text(
                "---\nname: time-helper\ndescription: answer time\ntriggers: time, now\n---\nUse local time.\n",
                encoding="utf-8",
            )
            router = KeywordSkillRouter(FileSkillStore([Path(tmp)]), SkillRouterConfig(max_skills=3))
            selected = asyncio.run(router.select_for_user_text("time now", limit=3))
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0].name, "always-one")
        self.assertEqual(selected[1].name, "time-helper")

    def test_skill_definition_render(self) -> None:
        skill = SkillDefinition(
            name="x",
            description="y",
            content="z",
            triggers=("a", "b"),
            metadata={"k": "v"},
            always=True,
        )
        rendered = skill.render()
        self.assertIn("Skill: x", rendered)
        self.assertIn("Triggers: a, b", rendered)


if __name__ == "__main__":
    unittest.main()
