#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: router.py.py
# @Description: 路由器
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/19 14:39
# @Version: 1.0

"""Message routing — dispatches incoming messages to appropriate handlers.

The Router is responsible for:
1. Matching incoming messages against Skill triggers
2. Assembling context for matched skills (injecting skill prompts)
3. Determining which agent should handle a message (multi-agent routing)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from miniclaw.skills import Skill, SkillRegistry

# 使用模块级 logger，便于按模块粒度控制日志输出
logger = logging.getLogger(__name__)


@dataclass
class RouteResult:
    """路由结果，封装一次消息路由的完整输出。

    :param matched_skills: 命中的技能列表，按匹配顺序排列。
    :param extra_system_prompt: 所有命中技能的提示词拼接结果，用于注入 system prompt。
    :param extra_tools: 所有命中技能声明的工具名称（已去重），供 Agent 按需加载。
    :param target_agent: 本次消息应由哪个 Agent 处理的 ID。
    """

    matched_skills: list[Skill]   # 命中的技能列表
    extra_system_prompt: str      # 聚合后的技能提示词，以分隔线拼接
    extra_tools: list[str]        # 技能声明的工具名称（去重后）
    target_agent: str             # 目标 Agent ID


class Router:
    """消息路由器，负责将传入消息分发给合适的技能和 Agent。

    工作流程：
    1. 通过 SkillRegistry 匹配消息触发的技能；
    2. 聚合命中技能的提示词与工具列表；
    3. 根据关键词绑定规则决定目标 Agent。
    """

    def __init__(self, skill_registry: SkillRegistry):
        """
        初始化路由器。

        :param skill_registry: 技能注册表，用于根据消息文本匹配技能。
        """
        # 持有技能注册表，路由时通过它完成技能匹配
        self.skills = skill_registry
        # 关键词 → Agent ID 列表的映射，支持一个关键词绑定多个 Agent
        self._agent_bindings: dict[str, list[str]] = {}

    def add_agent_binding(self, agent_id: str, patterns: list[str]) -> None:
        """
        将消息关键词模式绑定到指定 Agent。

        同一个 pattern 可绑定多个 Agent，路由时取第一个匹配的 Agent。

        :param agent_id: 目标 Agent 的唯一标识符。
        :param patterns: 触发该 Agent 的关键词列表（大小写不敏感）。
        """
        for pattern in patterns:
            # 若该 pattern 尚未注册，先初始化为空列表，再追加 agent_id
            self._agent_bindings[pattern] = self._agent_bindings.get(pattern, [])
            self._agent_bindings[pattern].append(agent_id)

    def route(self, text: str, source_agent: str = "main") -> RouteResult:
        """
        对传入消息执行完整的路由流程，返回路由结果。

        流程：
        1. 通过 SkillRegistry 匹配命中的技能；
        2. 聚合命中技能的 prompt 和工具列表；
        3. 解析目标 Agent；
        4. 记录路由日志并返回 RouteResult。

        :param text: 用户输入的原始消息文本。
        :param source_agent: 消息来源 Agent ID，未命中绑定规则时作为默认目标 Agent。
        :return: 包含命中技能、聚合提示词、工具列表和目标 Agent 的路由结果。
        """
        # 通过注册表匹配当前消息触发的所有技能
        matched = self.skills.match(text)

        extra_prompts = []           # 收集各技能的提示词片段
        extra_tools: list[str] = []  # 收集各技能声明的工具名称

        for skill in matched:
            # 仅当技能配置了提示词时才追加，避免引入空白片段
            if skill.prompt:
                extra_prompts.append(
                    f"### Skill: {skill.name}\n\n{skill.prompt}"
                )
            # 将技能声明的工具名称追加到汇总列表
            extra_tools.extend(skill.tools)

        # 根据关键词绑定规则解析目标 Agent
        target = self._resolve_agent(text, source_agent)

        if matched:
            # 仅在有技能命中时输出日志，减少无效日志噪声
            logger.info(
                f"Matched {len(matched)} skills: "
                f"{[s.name for s in matched]} → agent:{target}"
            )

        return RouteResult(
            matched_skills=matched,
            # 多个技能提示词之间以水平分隔线拼接，保持可读性
            extra_system_prompt="\n\n---\n\n".join(extra_prompts),
            # 对工具列表去重，防止同一工具被多个技能重复声明
            extra_tools=list(set(extra_tools)),
            target_agent=target,
        )

    def _resolve_agent(self, text: str, source: str) -> str:
        """
        根据关键词绑定规则解析目标 Agent ID。

        遍历所有已注册的关键词绑定，若消息文本包含某个 pattern（大小写不敏感），
        则返回该 pattern 绑定的第一个 Agent ID；若无匹配，则回退到来源 Agent。

        :param text: 用户输入的原始消息文本。
        :param source: 消息来源 Agent ID，作为未命中时的默认返回值。
        :return: 目标 Agent ID。
        """
        for pattern, agents in self._agent_bindings.items():
            # 大小写不敏感匹配，提升关键词覆盖率
            if pattern.lower() in text.lower():
                # 取绑定列表中的第一个 Agent 作为路由目标
                return agents[0]
        # 未命中任何绑定规则，消息留在来源 Agent 处理
        return source
