"""Unit tests for router.py — routing, skill matching, cross-agent routing."""

import pytest

from miniclaw.router import Router, RouteResult
from miniclaw.skills import SkillRegistry, Skill, Trigger


class TestRouter:
    def _make_registry(self, *skills):
        reg = SkillRegistry()
        for s in skills:
            reg._skills.append(s)
        return reg

    def test_route_no_skills(self):
        reg = self._make_registry()
        router = Router(reg)
        result = router.route("hello", "main")
        assert result.target_agent == "main"
        assert result.extra_system_prompt == ""
        assert len(result.matched_skills) == 0

    def test_route_with_matched_skill(self):
        skill = Skill(
            name="greeting",
            description="Greets",
            triggers=[Trigger(type="keyword", pattern="hello")],
            tools=["file_read"],
            prompt="Be friendly.",
        )
        reg = self._make_registry(skill)
        router = Router(reg)
        result = router.route("say hello", "main")
        assert len(result.matched_skills) == 1
        assert "Be friendly" in result.extra_system_prompt
        assert "file_read" in result.extra_tools

    def test_route_multiple_skills(self):
        s1 = Skill(name="s1", description="", triggers=[Trigger(type="keyword", pattern="hello")],
                    tools=["file_read"], prompt="P1")
        s2 = Skill(name="s2", description="", triggers=[Trigger(type="always")],
                    tools=["shell_exec"], prompt="P2")
        reg = self._make_registry(s1, s2)
        router = Router(reg)
        result = router.route("hello", "main")
        assert len(result.matched_skills) == 2
        assert "P1" in result.extra_system_prompt
        assert "P2" in result.extra_system_prompt
        assert "file_read" in result.extra_tools
        assert "shell_exec" in result.extra_tools

    def test_route_agent_routing_keyword(self):
        reg = self._make_registry()
        router = Router(reg)
        router.add_agent_binding("math", ["calculate", "math"])
        result = router.route("calculate 2+2", "main")
        assert result.target_agent == "math"

    def test_route_agent_routing_no_match(self):
        reg = self._make_registry()
        router = Router(reg)
        router.add_agent_binding("math", ["calculate"])
        result = router.route("hello there", "main")
        assert result.target_agent == "main"

    def test_route_preserves_source_agent(self):
        reg = self._make_registry()
        router = Router(reg)
        result = router.route("hello", "custom-agent")
        assert result.target_agent == "custom-agent"

    def test_route_result_no_tools_default(self):
        reg = self._make_registry()
        router = Router(reg)
        result = router.route("hello", "main")
        assert result.extra_tools == []
