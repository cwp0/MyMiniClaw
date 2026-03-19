"""Unit tests for gateway.py — Gateway coordination logic (mocked Brain)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from miniclaw.agents import Agent
from miniclaw.brain import BrainResponse, Message
from miniclaw.config import AgentDef, BrainConfig, Config, HeartbeatConfig
from miniclaw.gateway import Gateway
from miniclaw.hooks import Hook, HookEvent, EVENT_MESSAGE_RECEIVED, EVENT_MESSAGE_SENT


def make_config(tmp_path: Path) -> Config:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "SOUL.md").write_text("# Soul\nTest.\n")
    (ws / "IDENTITY.md").write_text("# Identity\nTestBot\n")
    (ws / "MEMORY.md").write_text("# Memory\n")
    (ws / "HEARTBEAT.md").write_text("# Heartbeat\nReply HEARTBEAT_OK\n")
    (ws / "skills").mkdir()

    return Config(
        config_dir=tmp_path / ".miniclaw",
        workspace=ws,
        agents={
            "main": AgentDef(
                id="main",
                brain=BrainConfig(provider="openai", api_key="fake"),
                heartbeat=HeartbeatConfig(enabled=False),
            ),
        },
    )


def mock_brain_think():
    """Return an AsyncMock that always returns a simple text response."""
    return AsyncMock(return_value=BrainResponse(
        text="mocked response",
        tool_calls=[],
        stop_reason="end_turn",
        usage={"input_tokens": 10, "output_tokens": 5},
    ))


class TestGateway:
    async def test_start_and_stop(self, tmp_path):
        cfg = make_config(tmp_path)
        gw = Gateway(cfg)
        await gw.start()
        assert gw._running is True
        await gw.stop()
        assert gw._running is False

    async def test_handle_input(self, tmp_path):
        cfg = make_config(tmp_path)
        gw = Gateway(cfg)
        await gw.start()
        agent = gw.orchestrator.get_or_create_agent("main")
        agent.brain.think = mock_brain_think()

        response = await gw.handle_input("hello")
        assert response == "mocked response"
        assert gw._request_count == 1
        await gw.stop()

    async def test_message_handlers_called(self, tmp_path):
        cfg = make_config(tmp_path)
        gw = Gateway(cfg)
        await gw.start()
        agent = gw.orchestrator.get_or_create_agent("main")
        agent.brain.think = mock_brain_think()

        delivered = []

        async def handler(agent_id, response):
            delivered.append({"agent_id": agent_id, "response": response})

        gw.on_message(handler)
        await gw.handle_input("test")
        assert len(delivered) == 1
        assert delivered[0]["agent_id"] == "main"
        await gw.stop()

    async def test_session_persistence(self, tmp_path):
        cfg = make_config(tmp_path)
        gw = Gateway(cfg)
        await gw.start()
        agent = gw.orchestrator.get_or_create_agent("main")
        agent.brain.think = mock_brain_think()

        await gw.handle_input("persist me")

        session_file = cfg.config_dir / "sessions" / "main.jsonl"
        assert session_file.exists()
        content = session_file.read_text()
        entry = json.loads(content.strip().split("\n")[-1])
        assert entry["user"] == "persist me"
        assert entry["assistant"] == "mocked response"
        await gw.stop()

    async def test_health_endpoint(self, tmp_path):
        cfg = make_config(tmp_path)
        gw = Gateway(cfg)
        await gw.start()
        agent = gw.orchestrator.get_or_create_agent("main")
        agent.brain.think = mock_brain_think()

        await gw.handle_input("hi")
        health = gw.health()
        assert health["status"] == "healthy"
        assert health["requests"] == 1
        assert "main" in health["agents"]
        await gw.stop()

    async def test_hooks_fire_on_message(self, tmp_path):
        cfg = make_config(tmp_path)
        gw = Gateway(cfg)
        await gw.start()
        agent = gw.orchestrator.get_or_create_agent("main")
        agent.brain.think = mock_brain_think()

        events: list[HookEvent] = []

        async def capture(event: HookEvent):
            events.append(event)

        gw.register_hook(Hook(name="test", event_type="*", handler=capture))
        await gw.handle_input("hook test")

        types = [e.type for e in events]
        assert EVENT_MESSAGE_RECEIVED in types
        assert EVENT_MESSAGE_SENT in types
        await gw.stop()

    async def test_error_increments_count(self, tmp_path):
        cfg = make_config(tmp_path)
        gw = Gateway(cfg)
        await gw.start()
        agent = gw.orchestrator.get_or_create_agent("main")
        agent.brain.think = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError):
            await gw.handle_input("cause error")

        assert gw._error_count == 1
        await gw.stop()

    async def test_session_restore(self, tmp_path):
        cfg = make_config(tmp_path)
        session_dir = cfg.config_dir / "sessions"
        session_dir.mkdir(parents=True)
        session_file = session_dir / "main.jsonl"
        entry = json.dumps({
            "ts": "2026-01-01T00:00:00",
            "user": "previous message",
            "assistant": "previous reply",
        })
        session_file.write_text(entry + "\n")

        gw = Gateway(cfg)
        await gw.start()
        agent = gw.orchestrator.get_or_create_agent("main")
        # Should have restored 2 messages (user + assistant)
        assert len(agent.context.history) == 2
        assert agent.context.history[0].content == "previous message"
        assert agent.context.history[1].content == "previous reply"
        await gw.stop()

    async def test_cron_tools_registered(self, tmp_path):
        """cron_add and cron_list tools should be registered after gateway.start()."""
        cfg = make_config(tmp_path)
        gw = Gateway(cfg)
        await gw.start()
        agent = gw.orchestrator.get_or_create_agent("main")
        tool_names = [s["name"] for s in agent.hands.get_tool_schemas()]
        assert "cron_add" in tool_names
        assert "cron_list" in tool_names
        await gw.stop()

    async def test_cron_add_via_tool(self, tmp_path):
        """Agent can dynamically add a cron job via the cron_add tool."""
        cfg = make_config(tmp_path)
        gw = Gateway(cfg)
        await gw.start()
        agent = gw.orchestrator.get_or_create_agent("main")

        result = await agent.hands.execute("cron_add", {
            "name": "test-reminder",
            "schedule": "*/5",
            "prompt": "Remind the user to take a break",
        })
        assert "test-reminder" in result
        assert "main" in gw._cron_schedulers
        scheduler = gw._cron_schedulers["main"]
        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "test-reminder"
        await gw.stop()

    async def test_cron_list_via_tool(self, tmp_path):
        """cron_list tool returns scheduled jobs."""
        cfg = make_config(tmp_path)
        gw = Gateway(cfg)
        await gw.start()
        agent = gw.orchestrator.get_or_create_agent("main")

        empty = await agent.hands.execute("cron_list", {})
        assert "no cron jobs" in empty.lower()

        await agent.hands.execute("cron_add", {
            "name": "daily-report",
            "schedule": "09:00",
            "prompt": "Generate daily report",
        })
        listing = await agent.hands.execute("cron_list", {})
        assert "daily-report" in listing
        assert "09:00" in listing
        await gw.stop()
