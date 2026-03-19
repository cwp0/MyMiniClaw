"""Unit tests for agents.py — Agent, SpawnResult, AgentOrchestrator."""

from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from miniclaw.agents import Agent, AgentOrchestrator, SpawnResult
from miniclaw.brain import BrainResponse, Message, ToolCall
from miniclaw.config import AgentDef, BrainConfig, Config, HeartbeatConfig


def make_config(tmp_path: Path) -> Config:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "SOUL.md").write_text("# Soul\nTest agent.\n")
    (ws / "IDENTITY.md").write_text("# Identity\nName: TestBot\n")
    (ws / "MEMORY.md").write_text("# Memory\n")
    (ws / "HEARTBEAT.md").write_text("# Heartbeat\nReply HEARTBEAT_OK\n")
    (ws / "skills").mkdir()

    cfg = Config(
        config_dir=tmp_path / ".miniclaw",
        workspace=ws,
        agents={
            "main": AgentDef(
                id="main",
                brain=BrainConfig(provider="openai", api_key="fake-key"),
                heartbeat=HeartbeatConfig(enabled=False),
                max_spawn_depth=1,
            ),
        },
    )
    return cfg


class TestSpawnResult:
    def test_dataclass(self):
        r = SpawnResult(run_id="abc", status="completed", result="ok", agent_id="main")
        assert r.run_id == "abc"
        assert r.status == "completed"


class TestAgent:
    def test_init(self, tmp_path):
        cfg = make_config(tmp_path)
        agent = Agent(
            agent_def=cfg.agents["main"],
            workspace=cfg.workspace,
            config=cfg,
        )
        assert agent.id == "main"
        assert agent.spawn_depth == 0
        assert agent._turn_count == 0

    def test_spawn_tool_registered(self, tmp_path):
        cfg = make_config(tmp_path)
        agent = Agent(
            agent_def=cfg.agents["main"],
            workspace=cfg.workspace,
            config=cfg,
        )
        schemas = agent.hands.get_tool_schemas()
        tool_names = [s["name"] for s in schemas]
        assert "spawn_agent" in tool_names

    def test_spawn_tool_not_registered_at_max_depth(self, tmp_path):
        cfg = make_config(tmp_path)
        agent = Agent(
            agent_def=cfg.agents["main"],
            workspace=cfg.workspace,
            config=cfg,
            spawn_depth=1,
        )
        schemas = agent.hands.get_tool_schemas()
        tool_names = [s["name"] for s in schemas]
        assert "spawn_agent" not in tool_names

    def test_skill_index_built(self, tmp_path):
        cfg = make_config(tmp_path)
        skill_dir = cfg.workspace / "skills"
        (skill_dir / "test.md").write_text(
            "---\nname: test-skill\ndescription: A test\n"
            "triggers:\n  - type: keyword\n    pattern: test\n---\nDo test.\n"
        )
        agent = Agent(
            agent_def=cfg.agents["main"],
            workspace=cfg.workspace,
            config=cfg,
        )
        assert "test-skill" in agent._skill_index
        assert "A test" in agent._skill_index

    async def test_process_message_simple(self, tmp_path):
        cfg = make_config(tmp_path)
        agent = Agent(
            agent_def=cfg.agents["main"],
            workspace=cfg.workspace,
            config=cfg,
        )
        mock_response = BrainResponse(
            text="Hello! I am TestBot.",
            tool_calls=[],
            stop_reason="end_turn",
            usage={"input_tokens": 10, "output_tokens": 5},
        )
        agent.brain.think = AsyncMock(return_value=mock_response)

        result = await agent.process_message("hello")
        assert result == "Hello! I am TestBot."
        assert agent._turn_count == 1
        agent.brain.think.assert_called_once()

    async def test_process_message_with_tool_call(self, tmp_path):
        cfg = make_config(tmp_path)
        agent = Agent(
            agent_def=cfg.agents["main"],
            workspace=cfg.workspace,
            config=cfg,
        )

        tc = ToolCall(id="tc1", name="file_list", arguments={"path": "."})
        tool_response = BrainResponse(
            text="",
            tool_calls=[tc],
            stop_reason="tool_use",
            usage={"input_tokens": 10, "output_tokens": 5},
        )
        final_response = BrainResponse(
            text="Here are the files.",
            tool_calls=[],
            stop_reason="end_turn",
            usage={"input_tokens": 20, "output_tokens": 10},
        )
        agent.brain.think = AsyncMock(side_effect=[tool_response, final_response])

        result = await agent.process_message("list files")
        assert result == "Here are the files."
        assert agent.brain.think.call_count == 2

    async def test_spawn_depth_limit(self, tmp_path):
        cfg = make_config(tmp_path)
        cfg.agents["main"].max_spawn_depth = 0
        agent = Agent(
            agent_def=cfg.agents["main"],
            workspace=cfg.workspace,
            config=cfg,
        )
        result = await agent.spawn(task="do something")
        assert "max spawn depth" in result.lower() or "error" in result.lower()

    async def test_spawn_disallowed_agent(self, tmp_path):
        cfg = make_config(tmp_path)
        cfg.agents["main"].subagents_allow = ["helper"]
        agent = Agent(
            agent_def=cfg.agents["main"],
            workspace=cfg.workspace,
            config=cfg,
        )
        result = await agent.spawn(task="test", agent_id="forbidden")
        assert "not allowed" in result.lower() or "error" in result.lower()


class TestAgentOrchestrator:
    def test_get_or_create(self, tmp_path):
        cfg = make_config(tmp_path)
        orch = AgentOrchestrator(cfg)
        agent = orch.get_or_create_agent("main")
        assert agent.id == "main"
        same = orch.get_or_create_agent("main")
        assert same is agent

    def test_list_agents(self, tmp_path):
        cfg = make_config(tmp_path)
        orch = AgentOrchestrator(cfg)
        assert "main" in orch.list_agents()

    def test_get_missing_agent_raises(self, tmp_path):
        cfg = make_config(tmp_path)
        orch = AgentOrchestrator(cfg)
        with pytest.raises(ValueError, match="not defined"):
            orch.get_or_create_agent("nonexistent")
