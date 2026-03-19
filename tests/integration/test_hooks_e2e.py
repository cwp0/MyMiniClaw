"""Integration: Hooks (EventBus) end-to-end with real Gateway.

Requires: LLM API key configured in ~/.miniclaw/config.yaml
Run: pytest -m integration tests/integration/test_hooks_e2e.py -v
"""

import pytest

from miniclaw.config import Config
from miniclaw.gateway import Gateway
from miniclaw.hooks import (
    Hook, HookEvent,
    EVENT_MESSAGE_RECEIVED, EVENT_MESSAGE_SENT,
)


@pytest.fixture
async def gateway():
    cfg = Config.load()
    gw = Gateway(cfg)
    await gw.start()
    yield gw
    await gw.stop()


@pytest.mark.integration
async def test_events_fire_on_message(gateway):
    """Both message.received and message.sent events should fire."""
    received_events: list[HookEvent] = []

    async def log_all(event: HookEvent) -> None:
        received_events.append(event)

    gateway.register_hook(Hook(
        name="test-logger",
        event_type="*",
        handler=log_all,
    ))

    await gateway.handle_input("hello, test hooks!")

    types = [e.type for e in received_events]
    assert EVENT_MESSAGE_RECEIVED in types
    assert EVENT_MESSAGE_SENT in types


@pytest.mark.integration
async def test_targeted_hook(gateway):
    """Hook with specific event_type only fires for that event."""
    sent_events: list[HookEvent] = []

    async def on_sent(event: HookEvent) -> None:
        sent_events.append(event)

    gateway.register_hook(Hook(
        name="sent-only",
        event_type=EVENT_MESSAGE_SENT,
        handler=on_sent,
    ))

    await gateway.handle_input("targeted hook test")
    assert len(sent_events) == 1
    assert "response_length" in sent_events[0].payload


@pytest.mark.integration
async def test_hook_priority_ordering(gateway):
    """Hooks execute in priority order (lower number = higher priority)."""
    order: list[str] = []

    async def low(event: HookEvent) -> None:
        order.append("low")

    async def high(event: HookEvent) -> None:
        order.append("high")

    async def medium(event: HookEvent) -> None:
        order.append("medium")

    gateway.register_hook(Hook(
        name="low-pri", event_type=EVENT_MESSAGE_RECEIVED,
        handler=low, priority=200,
    ))
    gateway.register_hook(Hook(
        name="high-pri", event_type=EVENT_MESSAGE_RECEIVED,
        handler=high, priority=10,
    ))
    gateway.register_hook(Hook(
        name="med-pri", event_type=EVENT_MESSAGE_RECEIVED,
        handler=medium, priority=100,
    ))

    await gateway.handle_input("priority test")
    assert order == ["high", "medium", "low"]


@pytest.mark.integration
async def test_error_isolation(gateway):
    """A broken hook should not crash other hooks or the gateway response."""
    good_ran = []

    async def bad_hook(event: HookEvent) -> None:
        raise RuntimeError("broken hook!")

    async def good_hook(event: HookEvent) -> None:
        good_ran.append(True)

    gateway.register_hook(Hook(
        name="bad", event_type=EVENT_MESSAGE_RECEIVED,
        handler=bad_hook, priority=1,
    ))
    gateway.register_hook(Hook(
        name="good", event_type=EVENT_MESSAGE_RECEIVED,
        handler=good_hook, priority=50,
    ))

    response = await gateway.handle_input("error isolation test")
    assert len(good_ran) > 0
    assert response
