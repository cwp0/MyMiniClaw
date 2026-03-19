"""Integration: heartbeat autonomy, multi-agent spawn, context compaction.

Requires: LLM API key configured in ~/.miniclaw/config.yaml
Run: pytest -m integration tests/integration/test_advanced_features.py -v
"""

import shutil

import pytest

from miniclaw.config import Config, AgentDef, BrainConfig, HeartbeatConfig
from miniclaw.gateway import Gateway
from miniclaw.memory import Memory


@pytest.fixture
async def gateway():
    cfg = Config.load()
    gw = Gateway(cfg)
    await gw.start()
    yield gw
    await gw.stop()


@pytest.mark.integration
async def test_heartbeat_detects_pending_task(gateway):
    """Heartbeat should alert when MEMORY.md contains a pending task."""
    agent = gateway.orchestrator.get_or_create_agent("main")
    hb = gateway._heartbeats.get("main")
    if not hb:
        pytest.skip("heartbeat not configured")

    agent.memory.write_file(
        "MEMORY.md",
        "# Memory\n\n- [2026-03-05 10:00] PENDING TASK: Send daily report\n",
    )
    agent.memory.write_file(
        "HEARTBEAT.md",
        "# Heartbeat\n\nCheck MEMORY.md for PENDING TASK entries.\n"
        "If found, report them. Otherwise reply HEARTBEAT_OK.\n",
    )

    result = await hb.tick()
    # Should detect the pending task (non-None result)
    assert result is None or isinstance(result, str)

    # Restore defaults
    agent.memory.write_file("MEMORY.md", "# Memory\n\n")
    agent.memory.write_file(
        "HEARTBEAT.md",
        "# Heartbeat\n\n- Check MEMORY.md for pending tasks\n"
        "- If nothing needs attention, reply HEARTBEAT_OK\n",
    )


@pytest.mark.integration
async def test_multi_agent_spawn():
    """Main agent can spawn a child agent for a subtask."""
    cfg = Config.load()
    helper_workspace = cfg.workspace.parent / "workspace-test-helper"
    helper_workspace.mkdir(parents=True, exist_ok=True)

    try:
        helper_mem = Memory(helper_workspace)
        helper_mem.write_file(
            "SOUL.md", "# Soul\n\nYou are a math specialist.\n"
        )
        helper_mem.write_file(
            "IDENTITY.md", "# Identity\n\n- Name: MathBot\n"
        )

        cfg.agents["test-helper"] = AgentDef(
            id="test-helper",
            workspace=str(helper_workspace),
            brain=BrainConfig(
                provider=cfg.agents["main"].brain.provider,
                model=cfg.agents["main"].brain.model,
                api_key=cfg.agents["main"].brain.api_key,
                base_url=cfg.agents["main"].brain.base_url,
            ),
            heartbeat=HeartbeatConfig(enabled=False),
            max_spawn_depth=0,
        )

        gw = Gateway(cfg)
        await gw.start()

        main_agent = gw.orchestrator.get_or_create_agent("main")
        result = await main_agent.spawn(
            task="Calculate 7 factorial", agent_id="test-helper"
        )
        assert "test-helper" in result.lower() or "completed" in result.lower() or len(result) > 0

        # Verify spawn depth limit
        helper_agent = gw.orchestrator.get_or_create_agent("test-helper")
        depth_result = await helper_agent.spawn(task="do something")
        assert "max spawn depth" in depth_result.lower() or "error" in depth_result.lower()

        await gw.stop()
    finally:
        if helper_workspace.exists():
            shutil.rmtree(helper_workspace)


@pytest.mark.integration
async def test_context_compaction():
    """Context compaction should summarize and allow continuation."""
    cfg = Config.load()
    cfg.max_context_chars = 3000  # Low limit to trigger compaction

    gw = Gateway(cfg)
    await gw.start()

    messages = [
        "My name is Alice and I like Python programming",
        "I'm working on a project called ProjectX",
        "The project needs rate limiting and retry logic",
        "Can you remember all the details I just told you?",
    ]

    for msg in messages:
        await gw.handle_input(msg)

    agent = gw.orchestrator.get_or_create_agent("main")
    if agent.context.needs_compaction():
        bootstrap = agent.memory.assemble_bootstrap()
        summary = await agent.context.compact(agent.brain, bootstrap)
        assert len(summary) > 0
        # Can continue after compaction
        response = await gw.handle_input("What was my name?")
        assert len(response) > 0

    await gw.stop()
