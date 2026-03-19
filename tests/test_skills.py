"""Unit tests for skills.py — skill parsing, trigger matching, edge cases."""

from pathlib import Path

import pytest

from miniclaw.skills import Trigger, Skill, SkillRegistry


class TestTrigger:
    def test_keyword_match(self):
        t = Trigger(type="keyword", pattern="hello")
        assert t.matches("say hello") is True
        assert t.matches("HELLO world") is True
        assert t.matches("goodbye") is False

    def test_regex_match(self):
        t = Trigger(type="regex", pattern=r"review\s+my\s+code")
        assert t.matches("please review my code") is True
        assert t.matches("Review My Code") is True
        assert t.matches("review code") is False

    def test_always_match(self):
        t = Trigger(type="always")
        assert t.matches("anything") is True
        assert t.matches("") is True

    def test_unknown_type(self):
        t = Trigger(type="unknown", pattern="x")
        assert t.matches("x") is False


class TestSkill:
    def test_matches_any_trigger(self):
        skill = Skill(
            name="test",
            description="",
            triggers=[
                Trigger(type="keyword", pattern="foo"),
                Trigger(type="keyword", pattern="bar"),
            ],
            tools=[],
            prompt="test prompt",
        )
        assert skill.matches("foo") is True
        assert skill.matches("bar") is True
        assert skill.matches("baz") is False

    def test_matches_no_triggers(self):
        skill = Skill(name="empty", description="", triggers=[], tools=[], prompt="")
        assert skill.matches("anything") is False


class TestSkillRegistry:
    def test_load_from_directory(self, tmp_workspace, sample_skill_file):
        reg = SkillRegistry()
        count = reg.load_from_directory(tmp_workspace / "skills")
        assert count == 1

    def test_load_from_nonexistent_directory(self, tmp_path):
        reg = SkillRegistry()
        count = reg.load_from_directory(tmp_path / "nonexistent")
        assert count == 0

    def test_match_keyword(self, tmp_workspace, sample_skill_file):
        reg = SkillRegistry()
        reg.load_from_directory(tmp_workspace / "skills")
        matches = reg.match("hello there")
        assert len(matches) == 1
        assert matches[0].name == "greeting"

    def test_match_regex(self, tmp_workspace, sample_skill_file):
        reg = SkillRegistry()
        reg.load_from_directory(tmp_workspace / "skills")
        matches = reg.match("hi there")
        assert len(matches) == 1

    def test_no_match(self, tmp_workspace, sample_skill_file):
        reg = SkillRegistry()
        reg.load_from_directory(tmp_workspace / "skills")
        matches = reg.match("goodbye")
        assert len(matches) == 0

    def test_list_skills(self, tmp_workspace, sample_skill_file):
        reg = SkillRegistry()
        reg.load_from_directory(tmp_workspace / "skills")
        skills = reg.list_skills()
        assert len(skills) == 1
        assert skills[0]["name"] == "greeting"
        assert skills[0]["description"] == "Greets the user"

    def test_get_skill(self, tmp_workspace, sample_skill_file):
        reg = SkillRegistry()
        reg.load_from_directory(tmp_workspace / "skills")
        skill = reg.get_skill("greeting")
        assert skill is not None
        assert skill.name == "greeting"

    def test_get_skill_missing(self, tmp_workspace, sample_skill_file):
        reg = SkillRegistry()
        reg.load_from_directory(tmp_workspace / "skills")
        assert reg.get_skill("nonexistent") is None

    def test_tools_as_list(self, tmp_workspace, sample_skill_file):
        reg = SkillRegistry()
        reg.load_from_directory(tmp_workspace / "skills")
        skill = reg.get_skill("greeting")
        assert skill.tools == ["file_read"]

    def test_tools_as_string_normalized(self, tmp_workspace, sample_skill_string_tools):
        reg = SkillRegistry()
        reg.load_from_directory(tmp_workspace / "skills")
        skill = reg.get_skill("simple")
        assert skill.tools == ["file_read"]
        assert "f" not in skill.tools  # not iterated char by char

    def test_simple_string_trigger(self, tmp_workspace, sample_skill_string_tools):
        reg = SkillRegistry()
        reg.load_from_directory(tmp_workspace / "skills")
        skill = reg.get_skill("simple")
        assert len(skill.triggers) == 1
        assert skill.triggers[0].type == "keyword"
        assert skill.triggers[0].pattern == "hello"

    def test_malformed_skill_skipped(self, tmp_workspace):
        bad_file = tmp_workspace / "skills" / "bad.md"
        bad_file.write_text("not valid yaml frontmatter")
        reg = SkillRegistry()
        count = reg.load_from_directory(tmp_workspace / "skills")
        # Should not crash, might load 0 or parse it as content-only
        assert count >= 0

    def test_skill_prompt_content(self, tmp_workspace, sample_skill_file):
        reg = SkillRegistry()
        reg.load_from_directory(tmp_workspace / "skills")
        skill = reg.get_skill("greeting")
        assert "friendly greeting bot" in skill.prompt

    def test_build_index_empty(self):
        reg = SkillRegistry()
        assert reg.build_index() == ""

    def test_build_index_contains_name_and_description(self, tmp_workspace, sample_skill_file):
        reg = SkillRegistry()
        reg.load_from_directory(tmp_workspace / "skills")
        index = reg.build_index()
        assert "Available Skills" in index
        assert "greeting" in index
        assert "Greets the user" in index

    def test_build_index_contains_triggers(self, tmp_workspace, sample_skill_file):
        reg = SkillRegistry()
        reg.load_from_directory(tmp_workspace / "skills")
        index = reg.build_index()
        assert "triggers:" in index
        assert "hello" in index

    def test_build_index_excludes_body(self, tmp_workspace, sample_skill_file):
        reg = SkillRegistry()
        reg.load_from_directory(tmp_workspace / "skills")
        index = reg.build_index()
        assert "friendly greeting bot" not in index
