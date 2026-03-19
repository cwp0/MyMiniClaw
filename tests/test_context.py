"""Unit tests for context.py — context assembly, compaction, message sanitization."""

import pytest

from miniclaw.brain import Message, ToolCall
from miniclaw.context import ContextManager, ContextWindow


class TestContextWindow:
    def test_estimate_tokens(self):
        window = ContextWindow(
            system_prompt="Hello world",
            messages=[Message(role="user", content="test message")],
        )
        tokens = window.estimate_tokens()
        assert tokens > 0
        assert window.total_chars == len("Hello world") + len("test message")


class TestContextManager:
    def test_add_and_build(self):
        ctx = ContextManager()
        ctx.add_message(Message(role="user", content="hello"))
        window = ctx.build(bootstrap_prompt="You are a bot.")
        assert len(window.messages) == 1
        assert window.messages[0].content == "hello"
        assert "You are a bot" in window.system_prompt

    def test_build_with_skill_prompt(self):
        ctx = ContextManager()
        ctx.add_message(Message(role="user", content="hello"))
        window = ctx.build(
            bootstrap_prompt="Base prompt",
            skill_prompt="Skill instructions here",
        )
        assert "Base prompt" in window.system_prompt
        assert "Skill instructions here" in window.system_prompt

    def test_build_with_skill_index(self):
        ctx = ContextManager()
        ctx.add_message(Message(role="user", content="hello"))
        window = ctx.build(
            bootstrap_prompt="Base prompt",
            skill_index="## Available Skills\n- greeting: Hello",
        )
        assert "Base prompt" in window.system_prompt
        assert "Available Skills" in window.system_prompt
        assert "greeting" in window.system_prompt

    def test_build_progressive_disclosure_order(self):
        """Skill index should appear before matched skill body."""
        ctx = ContextManager()
        ctx.add_message(Message(role="user", content="hello"))
        window = ctx.build(
            bootstrap_prompt="Bootstrap",
            skill_index="INDEX_MARKER",
            skill_prompt="BODY_MARKER",
        )
        idx_pos = window.system_prompt.index("INDEX_MARKER")
        body_pos = window.system_prompt.index("BODY_MARKER")
        assert idx_pos < body_pos

    def test_build_with_compacted_summary(self):
        ctx = ContextManager()
        ctx._compacted_summary = "Previous discussion about Python."
        ctx.add_message(Message(role="user", content="continue"))
        window = ctx.build(bootstrap_prompt="You are a bot.")
        assert len(window.messages) == 2
        assert "Previous discussion" in window.messages[0].content
        assert window.messages[1].content == "continue"

    def test_needs_compaction_false(self):
        ctx = ContextManager(max_context_chars=1000)
        ctx.add_message(Message(role="user", content="short"))
        assert ctx.needs_compaction() is False

    def test_needs_compaction_true(self):
        ctx = ContextManager(max_context_chars=100)
        ctx.add_message(Message(role="user", content="x" * 80))
        assert ctx.needs_compaction() is True

    def test_clear(self):
        ctx = ContextManager()
        ctx.add_message(Message(role="user", content="hello"))
        ctx._compacted_summary = "old summary"
        ctx.clear()
        assert len(ctx.history) == 0
        assert ctx._compacted_summary is None

    def test_history_property(self):
        ctx = ContextManager()
        ctx.add_message(Message(role="user", content="msg1"))
        ctx.add_message(Message(role="assistant", content="reply1"))
        assert len(ctx.history) == 2


class TestSanitizeMessages:
    def test_empty_messages(self):
        ctx = ContextManager()
        assert ctx._sanitize_messages([]) == []

    def test_valid_sequence(self):
        tc = ToolCall(id="tc1", name="file_read", arguments={"path": "x"})
        messages = [
            Message(role="user", content="read file"),
            Message(role="assistant", content="", tool_calls=[tc]),
            Message(role="tool_result", content="file content", tool_call_id="tc1"),
            Message(role="assistant", content="Here is the file."),
        ]
        ctx = ContextManager()
        result = ctx._sanitize_messages(messages)
        assert len(result) == 4

    def test_orphaned_tool_result_dropped(self):
        messages = [
            Message(role="tool_result", content="orphaned", tool_call_id="tc0"),
            Message(role="user", content="hello"),
        ]
        ctx = ContextManager()
        result = ctx._sanitize_messages(messages)
        assert len(result) == 1
        assert result[0].role == "user"

    def test_tool_result_after_user_dropped(self):
        messages = [
            Message(role="user", content="hello"),
            Message(role="tool_result", content="orphaned", tool_call_id="tc0"),
        ]
        ctx = ContextManager()
        result = ctx._sanitize_messages(messages)
        assert len(result) == 1

    def test_multiple_tool_results_valid(self):
        tc1 = ToolCall(id="tc1", name="f1", arguments={})
        tc2 = ToolCall(id="tc2", name="f2", arguments={})
        messages = [
            Message(role="assistant", content="", tool_calls=[tc1, tc2]),
            Message(role="tool_result", content="r1", tool_call_id="tc1"),
            Message(role="tool_result", content="r2", tool_call_id="tc2"),
        ]
        ctx = ContextManager()
        result = ctx._sanitize_messages(messages)
        assert len(result) == 3


class TestFindSafeSplit:
    def test_short_history(self):
        ctx = ContextManager()
        ctx._history = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ]
        assert ctx._find_safe_split(target_keep=4) == 0

    def test_split_at_user_boundary(self):
        ctx = ContextManager()
        ctx._history = [
            Message(role="user", content="msg1"),
            Message(role="assistant", content="reply1"),
            Message(role="user", content="msg2"),
            Message(role="assistant", content="reply2"),
            Message(role="user", content="msg3"),
            Message(role="assistant", content="reply3"),
        ]
        split = ctx._find_safe_split(target_keep=4)
        assert ctx._history[split].role == "user"

    def test_split_avoids_tool_result(self):
        tc = ToolCall(id="tc1", name="f", arguments={})
        ctx = ContextManager()
        ctx._history = [
            Message(role="user", content="msg1"),
            Message(role="assistant", content="reply1"),
            Message(role="user", content="msg2"),
            Message(role="assistant", content="", tool_calls=[tc]),
            Message(role="tool_result", content="result", tool_call_id="tc1"),
            Message(role="assistant", content="final"),
        ]
        split = ctx._find_safe_split(target_keep=3)
        # Should not split between tool_calls assistant and tool_result
        assert ctx._history[split].role == "user"

    def test_split_no_user_messages(self):
        tc = ToolCall(id="tc1", name="f", arguments={})
        ctx = ContextManager()
        ctx._history = [
            Message(role="assistant", content="a1"),
            Message(role="assistant", content="", tool_calls=[tc]),
            Message(role="tool_result", content="result", tool_call_id="tc1"),
            Message(role="assistant", content="a2"),
            Message(role="assistant", content="a3"),
            Message(role="assistant", content="a4"),
            Message(role="assistant", content="a5"),
        ]
        split = ctx._find_safe_split(target_keep=4)
        # Should not crash; returns 0 when no safe boundary
        assert split >= 0
