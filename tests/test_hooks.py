"""Unit tests for hooks.py — EventBus, priority, error isolation, global hooks."""

import asyncio

import pytest

from miniclaw.hooks import (
    EventBus, Hook, HookEvent,
    EVENT_MESSAGE_RECEIVED, EVENT_MESSAGE_SENT,
    EVENT_TOOL_EXECUTED, EVENT_HEARTBEAT_ALERT,
)


@pytest.mark.asyncio
class TestEventBus:
    async def test_register_and_emit(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.register(Hook(
            name="test", event_type=EVENT_MESSAGE_RECEIVED,
            handler=handler,
        ))
        await bus.emit(HookEvent(type=EVENT_MESSAGE_RECEIVED, payload={"text": "hi"}))
        assert len(received) == 1
        assert received[0].payload["text"] == "hi"

    async def test_targeted_hook_only_fires_on_match(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event.type)

        bus.register(Hook(name="sent-only", event_type=EVENT_MESSAGE_SENT, handler=handler))

        await bus.emit(HookEvent(type=EVENT_MESSAGE_RECEIVED, payload={}))
        await bus.emit(HookEvent(type=EVENT_MESSAGE_SENT, payload={}))
        assert received == [EVENT_MESSAGE_SENT]

    async def test_global_hook_fires_on_all(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event.type)

        bus.register(Hook(name="global", event_type="*", handler=handler))

        await bus.emit(HookEvent(type=EVENT_MESSAGE_RECEIVED, payload={}))
        await bus.emit(HookEvent(type=EVENT_TOOL_EXECUTED, payload={}))
        assert len(received) == 2

    async def test_priority_ordering(self):
        bus = EventBus()
        order = []

        async def make_handler(label):
            async def h(event):
                order.append(label)
            return h

        bus.register(Hook(name="last", event_type="test", handler=await make_handler("C"), priority=300))
        bus.register(Hook(name="first", event_type="test", handler=await make_handler("A"), priority=100))
        bus.register(Hook(name="middle", event_type="test", handler=await make_handler("B"), priority=200))

        await bus.emit(HookEvent(type="test", payload={}))
        assert order == ["A", "B", "C"]

    async def test_error_isolation(self):
        bus = EventBus()
        good_received = []

        async def bad_handler(event):
            raise ValueError("intentional error")

        async def good_handler(event):
            good_received.append(True)

        bus.register(Hook(name="bad", event_type="test", handler=bad_handler, priority=1))
        bus.register(Hook(name="good", event_type="test", handler=good_handler, priority=2))

        await bus.emit(HookEvent(type="test", payload={}))
        assert len(good_received) == 1  # good hook still fired

    async def test_unregister(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(True)

        bus.register(Hook(name="temp", event_type="test", handler=handler))
        await bus.emit(HookEvent(type="test", payload={}))
        assert len(received) == 1

        bus.unregister("temp")
        await bus.emit(HookEvent(type="test", payload={}))
        assert len(received) == 1  # no new events

    async def test_unregister_nonexistent_no_error(self):
        bus = EventBus()
        bus.unregister("nonexistent")  # should not raise

    async def test_list_hooks(self):
        bus = EventBus()

        async def h(e): pass

        bus.register(Hook(name="h1", event_type="a", handler=h, description="desc1"))
        bus.register(Hook(name="h2", event_type="b", handler=h))

        hooks = bus.list_hooks()
        assert len(hooks) == 2
        names = {h["name"] for h in hooks}
        assert names == {"h1", "h2"}
        assert any(h["description"] == "desc1" for h in hooks)

    async def test_emit_no_handlers(self):
        bus = EventBus()
        # Should not raise
        await bus.emit(HookEvent(type="no-listeners", payload={}))

    async def test_sync_handler_works(self):
        bus = EventBus()
        received = []

        def sync_handler(event):
            received.append(event.type)

        bus.register(Hook(name="sync", event_type="test", handler=sync_handler))
        await bus.emit(HookEvent(type="test", payload={}))
        assert len(received) == 1

    async def test_hook_event_source(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event.source)

        bus.register(Hook(name="src", event_type="test", handler=handler))
        await bus.emit(HookEvent(type="test", payload={}, source="heartbeat"))
        assert received == ["heartbeat"]

    async def test_multiple_hooks_same_event(self):
        bus = EventBus()
        count = []

        async def h1(e): count.append("h1")
        async def h2(e): count.append("h2")

        bus.register(Hook(name="a", event_type="test", handler=h1))
        bus.register(Hook(name="b", event_type="test", handler=h2))

        await bus.emit(HookEvent(type="test", payload={}))
        assert len(count) == 2
