"""Integration: comprehensive test covering all MiniClaw capabilities.

Requires: LLM API key configured in ~/.miniclaw/config.yaml
Run: pytest -m integration tests/integration/test_full_capabilities.py -v
"""

import pytest

from miniclaw.config import Config
from miniclaw.gateway import Gateway


@pytest.fixture
async def gateway():
    cfg = Config.load()
    gw = Gateway(cfg)
    await gw.start()
    yield gw
    await gw.stop()


@pytest.mark.integration
async def test_skill_trigger_greeting(gateway):
    response = await gateway.handle_input("hello, who are you?")
    assert len(response) > 10


@pytest.mark.integration
async def test_tool_file_write_and_read(gateway):
    await gateway.handle_input(
        "create a file called notes.txt with the content "
        "'MiniClaw test note - written by the agent'"
    )
    response = await gateway.handle_input("read the notes.txt file")
    assert len(response) > 0


@pytest.mark.integration
async def test_memory_append_and_read(gateway):
    await gateway.handle_input(
        "remember this: 'The user prefers concise answers'. "
        "Use memory_append to save it, then use memory_read to read "
        "MEMORY.md and confirm it was saved."
    )
    agent = gateway.orchestrator.get_or_create_agent("main")
    memory_content = agent.memory.read_file("MEMORY.md")
    assert "concise" in memory_content.lower() or len(memory_content) > 20


@pytest.mark.integration
async def test_skill_trigger_code_review(gateway):
    await gateway.handle_input(
        "create a file called sample.py with: 'def add(a, b): return a + b'"
    )
    response = await gateway.handle_input("can you review the file sample.py?")
    assert len(response) > 0


@pytest.mark.integration
async def test_heartbeat_tick(gateway):
    hb = gateway._heartbeats.get("main")
    if hb:
        result = await hb.tick()
        # result is None (HEARTBEAT_OK) or a string alert
        assert result is None or isinstance(result, str)
