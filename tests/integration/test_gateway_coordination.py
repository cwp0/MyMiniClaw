"""Integration: Gateway as central coordinator.

Verifies multi-channel delivery, cross-agent routing, cron execution,
session persistence, and agent lifecycle management.

Requires: LLM API key configured in ~/.miniclaw/config.yaml
Run: pytest -m integration tests/integration/test_gateway_coordination.py -v
"""

import shutil

import pytest

from miniclaw.config import Config, AgentDef, BrainConfig, HeartbeatConfig
from miniclaw.cron import CronJob
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
async def test_multi_channel_broadcast(gateway):
    """Both message handlers should receive the broadcast."""
    channel_a, channel_b = [], []

    async def handler_a(agent_id, response):
        channel_a.append(response)

    async def handler_b(agent_id, response):
        channel_b.append(response)

    gateway.on_message(handler_a)
    gateway.on_message(handler_b)

    await gateway.handle_input("hello!")
    assert len(channel_a) > 0
    assert len(channel_b) > 0


@pytest.mark.integration
async def test_cron_manual_execution(gateway):
    gateway.add_cron_job(
        "main",
        CronJob(
            name="test-status",
            schedule="*/5",
            prompt="List the files in your workspace using file_list",
        ),
    )
    scheduler = gateway._cron_schedulers.get("main")
    assert scheduler is not None
    result = await scheduler.run_job_now("test-status")
    assert result is not None and len(result) > 0


@pytest.mark.integration
async def test_session_persistence(gateway):
    await gateway.handle_input("session persistence test")
    session_file = gateway.config.config_dir / "sessions" / "main.jsonl"
    assert session_file.exists()
    content = session_file.read_text()
    assert "session persistence test" in content


@pytest.mark.integration
async def test_health_endpoint(gateway):
    await gateway.handle_input("hello")
    health = gateway.health()
    assert health["status"] == "healthy"
    assert health["requests"] >= 1
    assert "main" in health["agents"]


@pytest.mark.integration
async def test_cross_agent_routing():
    """Messages routed to a specific agent go to that agent."""
    cfg = Config.load()
    helper_ws = cfg.workspace.parent / "workspace-route-test"
    helper_ws.mkdir(parents=True, exist_ok=True)

    try:
        mem = Memory(helper_ws)
        mem.write_file("SOUL.md", "# Soul\n\nYou are a math specialist.\n")
        mem.write_file("IDENTITY.md", "# Identity\n\n- Name: MathBot\n")

        cfg.agents["math"] = AgentDef(
            id="math",
            workspace=str(helper_ws),
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

        response = await gw.handle_input("what is 2+2?", agent_id="math")
        assert len(response) > 0

        await gw.stop()
    finally:
        if helper_ws.exists():
            shutil.rmtree(helper_ws)
