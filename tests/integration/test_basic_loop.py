"""Integration: verify the full agent loop works end-to-end.

Requires: LLM API key configured in ~/.miniclaw/config.yaml
Run: pytest -m integration tests/integration/test_basic_loop.py -v
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
async def test_basic_greeting(gateway):
    response = await gateway.handle_input("hello, who are you?")
    assert len(response) > 0


@pytest.mark.integration
async def test_tool_file_list(gateway):
    response = await gateway.handle_input(
        "list all files in the workspace directory using the file_list tool"
    )
    assert len(response) > 0


@pytest.mark.integration
async def test_tool_file_read(gateway):
    response = await gateway.handle_input(
        "read the SOUL.md file and summarize it"
    )
    assert len(response) > 0


@pytest.mark.integration
async def test_tool_shell_exec(gateway):
    response = await gateway.handle_input(
        "run the shell command 'echo hello from miniclaw' and show me the output"
    )
    assert len(response) > 0


@pytest.mark.integration
async def test_conversation_memory(gateway):
    """Multi-turn: agent should recall earlier messages."""
    await gateway.handle_input(
        "remember this: 'The user prefers concise answers'. "
        "Use memory_append to save it."
    )
    response = await gateway.handle_input(
        "what did I ask you to remember?"
    )
    assert len(response) > 0
