#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: brain.py
# @Description: 脑，负责处理用户请求，调用各种插件
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/12 16:26
# @Version: 1.0


"""LLM provider abstraction.

Wraps Anthropic and OpenAI APIs with a unified tool-use interface.
The Brain handles:
1. System prompt construction (from Memory bootstrap)
2. Tool schema injection
3. The tool-use loop: model responds → tool call → execute → feed result back
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from miniclaw.config import BrainConfig

logger = logging.getLogger(__name__)


@dataclass # 数据类，自动生成 __init__ __repr__ 等方法
class ToolCall:
    """
    LLM 发起的一次工具调用请求
    """
    id: str          # 工具调用的唯一标识（用于后续回传结果时匹配）
    name: str        # 工具名称，如 "search_web"
    arguments: dict  # 工具参数，如 {"query": "天气"}


@dataclass
class BrainResponse:
    """
    统一的返回格式，不管底层是 Anthropic 还是 OpenAI，上层拿到的都是同一个结构。
    """
    text: str                  # LLM 的文本回复
    tool_calls: list[ToolCall] # LLM 请求调用的工具列表（可能为空）
    stop_reason: str           # 停止原因：正常结束 "end_turn" / 需要工具 "tool_use" / 达到 token 上限 "max_tokens"
    usage: dict[str, int]      # token 消耗统计 {"input_tokens": N, "output_tokens": M}


@dataclass
class Message:
    """
    统一的消息格式，是整个对话历史的基本单元。tool_result 角色用于把工具执行结果喂回给 LLM。
    """
    role: str                              # "user" | "assistant" | "tool_result"
    content: str                           # 消息内容
    tool_call_id: str | None = None        # 工具结果回传时的关联 ID
    tool_calls: list[ToolCall] | None = None  # assistant 消息中携带的工具调用

class Brain:
    """
    LLM 调用核心，封装 Anthropic 和 OpenAI 两套 API，对外暴露统一的 think() 接口。

    上层调用者无需关心底层使用的是哪家模型服务，只需传入标准的 Message 列表、
    系统提示词和工具 schema，即可获得统一格式的 BrainResponse。
    """

    def __init__(self, config: BrainConfig):
        """
        初始化 Brain。

        :param config: 包含 provider、model、api_key、max_tokens 等配置的 BrainConfig 对象
        """
        self.config = config
        self._client = None  # 延迟初始化，首次调用时才创建 API 客户端

    async def think(
            self,
            messages: list[Message],
            system_prompt: str,
            tools: list[dict[str, Any]] | None = None,
    ) -> BrainResponse:
        """
        根据配置的 provider，调用相应的 API 完成一次"思考"，返回统一的 BrainResponse。

        :param messages: 一个典型的多轮对话 + 工具调用的 messages 序列
            [
                Message(role="user", content="今天北京天气怎么样？"),
                Message(role="assistant", content="", tool_calls=[ToolCall(id="1", name="get_weather", arguments={"city": "北京"})]),
                Message(role="tool_result", content='{"temp": 25, "desc": "晴"}', tool_call_id="1"),
                Message(role="assistant", content="北京今天25°C，晴天☀️"),
                Message(role="user", content="那上海呢？"),
            ]
        :param system_prompt: 系统提示词，定义 LLM 的角色、行为规则和能力边界
            "你是 MiniClaw，一个有个性的 AI 助手。你可以使用工具来完成任务..."
        :param tools: 可用工具的 schema 列表，告诉 LLM 它能调用哪些工具。
            {
                "name": "get_weather",                    # 工具名称
                "description": "查询指定城市的天气",        # 工具描述，帮助 LLM 理解何时使用
                "parameters": {                           # JSON Schema 格式的参数定义
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称"
                        }
                    },
                "required": ["city"]
                }
            }
        :return: 统一的返回格式，包含文本回复、工具调用列表、停止原因和 token 消耗统计
            text	LLM 的文本回复（可能为空，如只调工具不说话）
            tool_calls	LLM 请求调用的工具列表（为空则表示不需要工具）
            stop_reason	"end_turn"=正常结束，"tool_use"=需要执行工具后继续，"max_tokens"=被截断
            usage	{"input_tokens": N, "output_tokens": M} token 消耗

            BrainResponse {
                text: "北京今天25°C，晴天☀️",
                tool_calls: [
                    ToolCall(id="1", name="get_weather", arguments={"city": "北京"})
                ],
                stop_reason: "end_turn",
                usage: {
                    "input_tokens": 10,
                    "output_tokens": 15
                }
            }
        """
        if self.config.provider == "anthropic":
            return await self._think_anthropic(messages, system_prompt, tools)
        elif self.config.provider in ("openai", "dashscope", "dashscope-coding"):
            return await self._think_openai(messages, system_prompt, tools)
        else:
            raise ValueError(f"Unsupported provider: {self.config.provider}")

    async def _think_anthropic(
            self,
            messages: list[Message],
            system_prompt: str,
            tools: list[dict[str, Any]] | None,
    ) -> BrainResponse:
        """
        调用 Anthropic（Claude）的 API 完成一次"思考"，返回统一的 BrainResponse。
        """
        import anthropic

        # 首次调用时创建异步客户端，后续复用，避免重复创建连接。
        if not self._client:
            self._client = anthropic.AsyncAnthropic(
                api_key=self.config.resolve_api_key()
            )

        # 将内部统一的 Message 对象转为 Anthropic API 要求的消息格式。
        api_messages = self._to_anthropic_messages(messages)

        # 构建请求参数
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": system_prompt,
            "messages": api_messages,
        }

        # 如果有 tools（函数调用能力），通过 _to_anthropic_tools 转换后追加到参数中。
        if tools:
            kwargs["tools"] = self._to_anthropic_tools(tools)

        # 调用 Anthropic API
        response = await self._client.messages.create(**kwargs)

        text_parts = []
        tool_calls = []
        # Anthropic 的响应 response.content 是一个 block 列表，每个 block 有 type 字段
        for block in response.content:
            # 普通文本回复，收集到 text_parts
            if block.type == "text":
                text_parts.append(block.text)
            # 模型请求调用工具，解析出 id、name、input（已经是 dict，无需 JSON 解析）
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    )
                )

        # 封装返回统一的 BrainResponse
        return BrainResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )



    async def _think_openai(
            self,
            messages: list[Message],
            system_prompt: str,
            tools: list[dict[str, Any]] | None,
    ) -> BrainResponse:
        """
        调用 OpenAI（或兼容 OpenAI 协议的服务）的 API，返回统一的 BrainResponse。
        """

        from openai import AsyncOpenAI

        if not self._client:
            kwargs = {"api_key": self.config.resolve_api_key()}
            base_url = self.config.resolve_base_url()
            # 如果指定了 base_url，则追加到 kwargs 中，意味着可以接入任何 OpenAI 兼容的第三方服务（如本地 Ollama、Azure OpenAI 等）。
            if base_url:
                kwargs["base_url"] = base_url
            self._client = AsyncOpenAI(**kwargs)

        # OpenAI 的 system prompt 是作为 {"role": "system", "content": ...} 消息放在列表最前面的，这是和 Anthropic 的关键区别。
        api_messages = [{"role": "system", "content": system_prompt}]
        api_messages.extend(self._to_openai_messages(messages))

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": api_messages,
        }
        if tools:
            kwargs["tools"] = self._to_openai_tools(tools)

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Malformed tool arguments from LLM: {tc.function.arguments!r}")
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        return BrainResponse(
            text=choice.message.content or "",
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage={
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        )



    def _to_anthropic_messages(self, messages: list[Message]) -> list[dict]:
        """
        将内部统一的 Message 对象转为 Anthropic API 要求的消息格式。

        :param messages:
        :return:
        """
        result = []
        for msg in messages:
            if msg.role == "user":
                result.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                content = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        content.append({
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        })
                result.append({"role": "assistant", "content": content})
            elif msg.role == "tool_result":
                result.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }],
                })
        return result

    def _to_openai_messages(self, messages: list[Message]) -> list[dict]:
        """
        将内部统一的 Message 对象转为 OpenAI Chat Completions API 要求的消息格式。

        与 Anthropic 的主要差异：
        - tool_result 角色映射为 "tool"，并通过 tool_call_id 关联对应的工具调用
        - assistant 消息中的工具调用需将 arguments 序列化为 JSON 字符串

        :param messages: 内部统一格式的消息列表
        :return: OpenAI API 接受的消息列表
        """
        result = []
        for msg in messages:
            if msg.role == "user":
                result.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content or "",
                }
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                result.append(entry)
            elif msg.role == "tool_result":
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
        return result

    def _to_anthropic_tools(self, tools: list[dict]) -> list[dict]:
        """
        将通用工具 schema 转换为 Anthropic API 要求的格式。

        Anthropic 使用 input_schema 字段（而非 parameters）描述工具入参的 JSON Schema。

        :param tools: 通用格式的工具 schema 列表
        :return: Anthropic API 接受的工具列表
        """
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]

    def _to_openai_tools(self, tools: list[dict]) -> list[dict]:
        """
        将通用工具 schema 转换为 OpenAI Function Calling API 要求的格式。

        OpenAI 要求工具以 {"type": "function", "function": {...}} 的结构包裹，
        参数 schema 字段名为 parameters（与通用格式一致，无需重命名）。

        :param tools: 通用格式的工具 schema 列表
        :return: OpenAI API 接受的工具列表
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]


async def main() -> None:
    """
    Brain 功能测试入口。

    测试流程：
      1. 构造一个最小化的 BrainConfig（使用 dashscope provider）
      2. 验证消息格式转换（_to_anthropic_messages / _to_openai_messages）是否正确
      3. 验证工具 schema 转换（_to_anthropic_tools / _to_openai_tools）是否正确
      4. 若环境变量中存在有效 API Key，则发起一次真实的 think() 调用并打印结果
    """
    import os

    print("=== Brain 功能测试 ===\n")

    # ── 1. 构造测试用 BrainConfig ──────────────────────────────────────────
    # 不显式传入 api_key / base_url，让 resolve_api_key() / resolve_base_url()
    # 自动从 PROVIDER_DEFAULTS 和环境变量中读取，确保 dashscope 的 base_url 也被正确设置。
    config = BrainConfig(
        provider="dashscope-coding",
        model="qwen3.5-plus",
        max_tokens=512,
    )
    brain = Brain(config)

    has_api_key = bool(os.environ.get("DASHSCOPE_API_KEY"))
    print(f"provider : {config.provider}")
    print(f"model    : {config.model}")
    print(f"base_url : {config.resolve_base_url()}")
    print(f"api_key  : {config.resolve_api_key()}")
    print(f"api_key  : {'已设置 ✅' if has_api_key else '未设置（跳过真实调用）⚠️'}\n")

    # ── 2. 测试消息格式转换 ────────────────────────────────────────────────
    test_messages = [
        Message(role="user", content="今天北京天气怎么样？"),
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="tc_001", name="get_weather", arguments={"city": "北京"})],
        ),
        Message(role="tool_result", content='{"temp": 25, "desc": "晴"}', tool_call_id="tc_001"),
        Message(role="assistant", content="北京今天25°C，晴天☀️"),
        Message(role="user", content="那上海呢？"),
    ]

    anthropic_messages = brain._to_anthropic_messages(test_messages)
    openai_messages = brain._to_openai_messages(test_messages)

    print("── Anthropic 消息格式转换结果 ──")
    for item in anthropic_messages:
        print(f"  {json.dumps(item, ensure_ascii=False)}")

    print("\n── OpenAI 消息格式转换结果 ──")
    for item in openai_messages:
        print(f"  {json.dumps(item, ensure_ascii=False)}")

    # ── 3. 测试工具 schema 转换 ────────────────────────────────────────────
    test_tools = [
        {
            "name": "get_weather",
            "description": "查询指定城市的实时天气",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称"},
                },
                "required": ["city"],
            },
        }
    ]

    anthropic_tools = brain._to_anthropic_tools(test_tools)
    openai_tools = brain._to_openai_tools(test_tools)

    print("\n── Anthropic 工具 schema 转换结果 ──")
    print(f"  {json.dumps(anthropic_tools, ensure_ascii=False, indent=2)}")

    print("\n── OpenAI 工具 schema 转换结果 ──")
    print(f"  {json.dumps(openai_tools, ensure_ascii=False, indent=2)}")

    # ── 4. 真实 API 调用（需要有效 API Key）────────────────────────────────
    if not has_api_key:
        print("\n⚠️  未检测到 DASHSCOPE_API_KEY，跳过真实 API 调用测试。")
        print("   可通过 `export DASHSCOPE_API_KEY=your_key` 设置后重新运行。")
    else:
        print("\n── 真实 think() 调用测试 ──")
        simple_messages = [Message(role="user", content="用一句话介绍你自己。")]
        system_prompt = "你是 MiniClaw，一个简洁高效的 AI 助手。"
        try:
            response = await brain.think(simple_messages, system_prompt)
            print(f"  stop_reason : {response.stop_reason}")
            print(f"  usage       : {response.usage}")
            print(f"  text        : {response.text}")
            print(f"  tool_calls  : {response.tool_calls}")
        except Exception as error:
            print(f"  ❌ 调用失败：{error}")

    print("\n✅ Brain 测试完成！")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
