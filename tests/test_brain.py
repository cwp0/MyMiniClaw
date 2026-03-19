"""Unit tests for brain.py — message format conversion and tool schema conversion."""

import pytest

from miniclaw.brain import Brain, BrainResponse, Message, ToolCall
from miniclaw.config import BrainConfig


class TestMessageConversion:
    """Test internal message format conversions (no LLM calls needed)."""

    def make_brain(self):
        return Brain(BrainConfig(provider="openai", api_key="fake"))

    def test_to_openai_user_message(self):
        brain = self.make_brain()
        msgs = [Message(role="user", content="hello")]
        result = brain._to_openai_messages(msgs)
        assert result == [{"role": "user", "content": "hello"}]

    def test_to_openai_assistant_with_tool_calls(self):
        brain = self.make_brain()
        tc = ToolCall(id="tc1", name="file_read", arguments={"path": "x.py"})
        msgs = [Message(role="assistant", content="", tool_calls=[tc])]
        result = brain._to_openai_messages(msgs)
        assert result[0]["role"] == "assistant"
        assert len(result[0]["tool_calls"]) == 1
        assert result[0]["tool_calls"][0]["function"]["name"] == "file_read"

    def test_to_openai_tool_result(self):
        brain = self.make_brain()
        msgs = [Message(role="tool_result", content="file data", tool_call_id="tc1")]
        result = brain._to_openai_messages(msgs)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "tc1"

    def test_to_anthropic_user_message(self):
        brain = self.make_brain()
        msgs = [Message(role="user", content="hello")]
        result = brain._to_anthropic_messages(msgs)
        assert result == [{"role": "user", "content": "hello"}]

    def test_to_anthropic_assistant_with_tool_calls(self):
        brain = self.make_brain()
        tc = ToolCall(id="tc1", name="file_read", arguments={"path": "x.py"})
        msgs = [Message(role="assistant", content="thinking...", tool_calls=[tc])]
        result = brain._to_anthropic_messages(msgs)
        assert result[0]["role"] == "assistant"
        content = result[0]["content"]
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "tool_use"

    def test_to_anthropic_tool_result(self):
        brain = self.make_brain()
        msgs = [Message(role="tool_result", content="data", tool_call_id="tc1")]
        result = brain._to_anthropic_messages(msgs)
        assert result[0]["role"] == "user"
        assert result[0]["content"][0]["type"] == "tool_result"
        assert result[0]["content"][0]["tool_use_id"] == "tc1"

    def test_full_conversation_openai(self):
        brain = self.make_brain()
        tc = ToolCall(id="tc1", name="file_read", arguments={"path": "x"})
        msgs = [
            Message(role="user", content="read x"),
            Message(role="assistant", content="", tool_calls=[tc]),
            Message(role="tool_result", content="content of x", tool_call_id="tc1"),
            Message(role="assistant", content="Here is x"),
        ]
        result = brain._to_openai_messages(msgs)
        assert len(result) == 4
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "tool"
        assert result[3]["role"] == "assistant"


class TestToolSchemaConversion:
    def make_brain(self):
        return Brain(BrainConfig(provider="openai", api_key="fake"))

    def test_to_openai_tools(self):
        brain = self.make_brain()
        tools = [{"name": "test", "description": "A test", "parameters": {"type": "object"}}]
        result = brain._to_openai_tools(tools)
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "test"

    def test_to_anthropic_tools(self):
        brain = self.make_brain()
        tools = [{"name": "test", "description": "A test", "parameters": {"type": "object"}}]
        result = brain._to_anthropic_tools(tools)
        assert result[0]["name"] == "test"
        assert result[0]["input_schema"] == {"type": "object"}

    def test_to_openai_tools_missing_description(self):
        brain = self.make_brain()
        tools = [{"name": "test", "parameters": {"type": "object"}}]
        result = brain._to_openai_tools(tools)
        assert result[0]["function"]["description"] == ""

    def test_to_anthropic_tools_missing_params(self):
        brain = self.make_brain()
        tools = [{"name": "test", "description": "A test"}]
        result = brain._to_anthropic_tools(tools)
        assert result[0]["input_schema"] == {"type": "object", "properties": {}}


class TestBrainResponse:
    def test_dataclass_fields(self):
        r = BrainResponse(
            text="hello",
            tool_calls=[],
            stop_reason="end_turn",
            usage={"input_tokens": 10, "output_tokens": 5},
        )
        assert r.text == "hello"
        assert r.tool_calls == []
        assert r.stop_reason == "end_turn"
        assert r.usage["input_tokens"] == 10


class TestBrainProviderRouting:
    async def test_unsupported_provider_raises(self):
        brain = Brain(BrainConfig(provider="unknown", api_key="fake"))
        with pytest.raises(ValueError, match="Unsupported provider"):
            await brain.think(
                messages=[Message(role="user", content="hi")],
                system_prompt="test",
            )
