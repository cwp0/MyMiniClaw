#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: context.py
# @Description: 上下文组装和压缩
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/16 11:29
# @Version: 1.0

"""Context assembly and compaction.

Manages the full context that goes into each LLM call:
1. Bootstrap context (SOUL.md, IDENTITY.md, etc.)
2. Skill-specific context (from matched skills)
3. Conversation history
4. Compaction (summarize old messages when context is too large)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from miniclaw.brain import Message

logger = logging.getLogger(__name__)


CHARS_PER_TOKEN_ESTIMATE = 4


@dataclass
class ContextWindow:
    """上下文窗口数据容器，代表一次LLM调用的完整输入。
    
    Attributes:
        system_prompt: 系统提示词（包含人格设定、技能索引等）
        messages: 对话消息列表
        total_chars: 总字符数缓存

    ContextWindow
    ├── system_prompt: str     # 系统提示词（人格 + 技能 + 索引）
    ├── messages: list[Message] # 对话消息列表
    ├── total_chars: int        # 总字符数缓存
    └── estimate_tokens()       # 用 chars/4 粗估 token 数

    """
    system_prompt: str
    messages: list[Message]
    total_chars: int = 0

    def estimate_tokens(self) -> int:
        """
        估算token数量（使用字符数/4的粗略计算）

        :return: 估算的token数量

        """
        # 初始化总字符数，从system_prompt开始计算
        total = len(self.system_prompt)
        # 遍历所有消息，累加每条消息的内容长度
        for m in self.messages:
            total += len(m.content)
        # 将计算结果缓存到total_chars属性中，供后续使用
        self.total_chars = total
        # 用总字符数除以4得到估算的token数量并返回
        return total // CHARS_PER_TOKEN_ESTIMATE


class ContextManager:
    """上下文管理器，负责组装和管理每次LLM调用的上下文窗口。
    
    核心职责是在有限的上下文窗口内，组装出最有价值的上下文内容。

    ContextManager
    ├── 状态
    │   ├── _history: list[Message]      # 完整对话历史
    │   ├── _compacted_summary: str|None # 压缩后的旧消息摘要
    │   └── max_context_chars: int       # 上下文字符上限
    │
    ├── 基础操作
    │   ├── add_message()    # 追加消息
    │   ├── clear()          # 清空一切
    │   └── history (property)
    │
    ├── 核心方法
    │   ├── build()              # 组装完整上下文窗口
    │   ├── needs_compaction()   # 判断是否需要压缩
    │   └── compact()            # 执行压缩（调用 LLM 做摘要）
    │
    └── 内部方法
        ├── _find_safe_split()     # 找安全的消息切分点
        └── _sanitize_messages()   # 清洗无效的消息序列

    """

    def __init__(self, max_context_chars: int = 100_000):
        """初始化上下文管理器
        
        Args:
            max_context_chars: 上下文最大字符数限制
        """
        # 设置上下文窗口的最大字符数上限
        self.max_context_chars = max_context_chars
        # 初始化空的历史消息列表
        self._history: list[Message] = []
        # 初始化压缩摘要为None（尚未进行任何压缩）
        self._compacted_summary: str | None = None

    @property
    def history(self) -> list[Message]:
        """
        获取完整的对话历史记录

        :return: 对话历史记录列表
        """

        return self._history

    def add_message(self, message: Message) -> None:
        """
        向对话历史中添加新消息

        :param message: 要添加的消息对象
        :return: None
        """
        # 将新消息追加到历史记录列表末尾
        self._history.append(message)

    def build(
            self,
            bootstrap_prompt: str,
            skill_prompt: str = "",
            skill_index: str = "",
    ) -> ContextWindow:
        """
        组装完整的上下文窗口

        采用渐进式披露策略：先展示技能索引概览，再展示具体技能指令。
        如果存在压缩摘要，会作为用户消息插入到对话开头。

        :param bootstrap_prompt: 基础提示词（SOUL.md + IDENTITY.md + MEMORY.md）
        :param skill_prompt: 匹配到的具体技能指令
        :param skill_index: 所有技能的摘要索引
        :return: 组装好的ContextWindow对象
        """

        # 将bootstrap_prompt作为系统提示词的基础部分
        system_parts = [bootstrap_prompt]
        # 如果存在技能索引，追加到系统提示词中（渐进式披露：先看概览）
        if skill_index:
            system_parts.append(skill_index)
        # 如果存在具体技能指令，追加到系统提示词中（在概览之后看详细指令）
        if skill_prompt:
            system_parts.append(skill_prompt)

        # 用分隔符将各部分系统提示词连接起来
        system_prompt = "\n\n---\n\n".join(system_parts)

        # 清洗历史消息，确保消息序列符合LLM API要求（处理孤立的tool_result）
        messages = self._sanitize_messages(list(self._history))
        # 如果存在之前压缩的摘要，将其作为用户消息插入到对话开头
        if self._compacted_summary:
            # 创建一条带有摘要内容的用户消息
            summary_msg = Message(
                role="user",
                content=f"[Previous conversation summary]\n{self._compacted_summary}",
            )
            # 将摘要消息前置到消息列表开头
            messages = [summary_msg] + messages

        # 创建ContextWindow对象，封装系统提示词和消息列表
        window = ContextWindow(
            system_prompt=system_prompt,
            messages=messages,
        )

        # 估算当前token数量，检查是否接近上限，超过则记录警告日志
        if window.estimate_tokens() * CHARS_PER_TOKEN_ESTIMATE > self.max_context_chars:
            logger.warning(
                f"Context approaching limit: ~{window.estimate_tokens()} tokens "
                f"({window.total_chars} chars / {self.max_context_chars} max)"
            )

        # 返回组装好的上下文窗口对象
        return window

    def needs_compaction(self) -> bool:
        """
        判断是否需要进行上下文压缩

        当历史消息总字符数超过上限的70%时触发压缩，
        预留30%空间给系统提示词。

        :return: 是否需要压缩
        """

        # 遍历所有历史消息，累加每条消息的内容长度
        total = sum(len(m.content) for m in self._history)
        # 判断总字符数是否超过上限的70%，返回布尔结果
        return total > self.max_context_chars * 0.7

    async def compact(self, brain, bootstrap_prompt: str) -> str:
        """执行上下文压缩，将旧消息摘要化，保留最近消息

        通过调用LLM对旧消息进行智能摘要，相比简单截断能更好地保留
        关键决策、事实和待办事项等重要信息。
        
        Args:
            brain: Brain实例，用于调用LLM进行摘要
            bootstrap_prompt: 基础提示词
            
        Returns:
            压缩状态信息
        """
        # 检查历史消息数量是否少于4条，如果是则无需压缩直接返回
        if len(self._history) < 4:
            return "Nothing to compact"

        # 寻找安全的消息切分点，保留最近4条消息
        split = self._find_safe_split(target_keep=4)
        # 根据切分点将消息分为旧消息（待压缩）和新消息（保留）
        old_messages = self._history[:split]
        recent_messages = self._history[split:]

        # 如果没有旧消息需要压缩，直接返回
        if not old_messages:
            return "Nothing to compact"

        # 将旧消息转换为文本格式，每条消息截断到500字符以减少输入长度
        old_text = "\n".join(
            f"[{m.role}] {m.content[:500]}" for m in old_messages
            if m.role in ("user", "assistant")
        )

        # 构建摘要提示词，要求LLM保留关键决策、事实和待办事项
        summary_prompt = (
            "Summarize the following conversation history concisely, "
            "preserving key decisions, facts, and action items:\n\n"
            f"{old_text}"
        )

        # 调用Brain的think方法，使用专门的摘要系统提示词让LLM生成摘要
        response = await brain.think(
            messages=[Message(role="user", content=summary_prompt)],
            system_prompt="You are a conversation summarizer. Be concise and factual.",
        )

        # 将LLM生成的摘要保存到_compacted_summary中
        self._compacted_summary = response.text
        # 更新历史记录，只保留最近的消息（被压缩的旧消息已丢弃）
        self._history = recent_messages

        # 记录压缩日志，包含压缩的消息数量和生成的摘要长度
        logger.info(
            f"Compacted {len(old_messages)} messages → "
            f"{len(response.text)} char summary"
        )
        # 返回压缩状态信息
        return response.text



    def _find_safe_split(self, target_keep: int = 4) -> int:
        """
        寻找安全的消息切分点，确保不破坏tool_call/tool_result配对

        从末尾向前查找'user'消息作为安全边界，因为tool_call/tool_result
        对只存在于assistant消息和后续tool消息之间。


       假设历史消息列表如下（共 8 条，`target_keep=4`）：
        索引  role        内容
         0   user        "帮我查一下天气"
         1   assistant   [tool_call: get_weather]
         2   tool        [tool_result: 晴天 25°C]
         3   assistant   "今天天气晴，25度"
         4   user        "那明天呢？"          ← 候选切分点 candidate = 8-4 = 4
         5   assistant   [tool_call: get_weather]
         6   tool        [tool_result: 多云 20°C]
         7   assistant   "明天多云，20度"

        **第一步**：计算初始候选点 `candidate = 8 - 4 = 4`
        **第二步**：检查索引 4 的消息 role 是否为 `"user"` → ✅ 是！直接返回 `4`
        **结果**：保留索引 4~7 共 4 条消息，索引 0~3 被压缩摘要替代。配对关系完整无损。


        ### 如果候选点恰好落在 tool 消息上怎么办？
        把上面例子稍微改一下，假设 `target_keep=3`：
        索引  role        内容
         0   user        "帮我查一下天气"
         1   assistant   [tool_call: get_weather]
         2   tool        [tool_result: 晴天 25°C]
         3   assistant   "今天天气晴，25度"
         4   user        "那明天呢？"
         5   assistant   [tool_call: get_weather]   ← candidate = 8-3 = 5，不是 user！
         6   tool        [tool_result: 多云 20°C]
         7   assistant   "明天多云，20度"

        **第一步**：`candidate = 8 - 3 = 5`，role 是 `assistant`，不安全
        **第二步**：向前移动 → `candidate = 4`，role 是 `user` ✅，返回 `4`
        **结果**：虽然目标是保留 3 条，但为了安全，实际保留了索引 4~7 共 4 条，避免了把 `tool_call`（索引5）和 `tool_result`（索引6）拆散。


        ### 极端情况：找不到 user 消息

        如果整个历史里全是 `assistant`/`tool` 消息（极少见），方法返回 `0`，表示**不压缩**，宁可不压缩也不破坏配对关系。



        :param target_keep: 目标保留的消息数量
        :return: 安全的切分点索引
        """

        # 如果历史消息数量不足保留数量，直接返回0（不压缩）
        if len(self._history) <= target_keep:
            return 0

        # 计算初始候选切分点位置（从末尾向前数target_keep条消息）
        candidate = len(self._history) - target_keep

        # 从候选位置向前遍历，寻找role为"user"的消息作为安全边界
        while candidate > 0:
            if self._history[candidate].role == "user":
                # 找到user消息，确定这是安全的切分点，退出循环
                break
            # 未找到user消息，继续向前查找
            candidate -= 1

        # 如果从候选点往前没找到user消息，改为从后往前找
        if candidate == 0:
            # 在保留窗口范围内向前查找user消息
            for i in range(len(self._history) - target_keep, len(self._history)):
                if self._history[i].role == "user":
                    # 找到则返回该位置作为切分点
                    return i
            # 实在找不到安全的user消息边界，返回0不进行压缩
            return 0  # 无法安全压缩

        # 返回找到的安全切分点索引
        return candidate

    def _sanitize_messages(self, messages: list[Message]) -> list[Message]:
        """
        清洗消息序列，确保符合LLM API要求

        规则：tool_result消息必须跟在包含tool_calls的assistant消息之后，
        删除孤立的tool_result消息。

        :param messages: 待清洗的消息列表
        :return: 清洗后的有效消息列表
        """

        # 如果消息列表为空，直接返回空列表
        if not messages:
            return messages
        # 初始化结果列表和工具调用状态标志
        result = []
        has_pending_tool_calls = False
        # 遍历每一条消息进行清洗
        for msg in messages:
            # 如果当前消息是tool_result类型
            if msg.role == "tool_result":
                # 检查前面是否有待处理的tool_calls，如果没有则是孤立的tool_result
                if not has_pending_tool_calls:
                    # 跳过（丢弃）孤立的tool_result消息
                    continue  # 删除孤立的tool_result
                # 有对应的tool_calls，将此tool_result加入结果
                result.append(msg)
            else:
                # 非tool_result消息直接加入结果列表
                result.append(msg)
                # 更新工具调用状态：如果当前是assistant且有tool_calls，标记为有待处理
                has_pending_tool_calls = (
                        msg.role == "assistant" and msg.tool_calls
                )
        # 返回清洗后的有效消息列表
        return result

    def clear(self) -> None:
        """
        清空所有对话历史和压缩摘要

        :return: None
        """

        # 清空对话历史列表
        self._history.clear()
        # 重置压缩摘要为None
        self._compacted_summary = None



