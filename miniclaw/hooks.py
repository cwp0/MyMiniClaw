#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: hooks.py
# @Description: Hooks
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/19 14:42
# @Version: 1.0

"""Hooks — event-driven lifecycle automation.

OpenClaw's three autonomy pillars:
- Heartbeat: periodic awareness ("check if anything needs attention")
- Cron: precise scheduling ("do X at Y time")
- Hooks: event-driven responses ("when X happens, do Y")

Hooks are built on an EventBus — components emit events,
and registered hook handlers respond. This is the "nervous system"
that connects everything without tight coupling.

Components don't call each other directly, but communicate
through event broadcasting — like a company bulletin board.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

HookHandler = Callable[["HookEvent"], Awaitable[None]]

@dataclass
class HookEvent:
    """
    触发钩子的事件数据类。

    EventBus 中流转的基本单元，携带事件类型、附加数据和来源标识。
    """

    type: str                                          # 事件类型，对应 EVENT_* 常量
    payload: dict[str, Any] = field(default_factory=dict)  # 事件附加数据，内容由发送方定义
    source: str = ""                                   # 事件来源标识，便于调试和过滤


@dataclass
class Hook:
    """
    已注册的钩子配置数据类，描述"监听哪种事件"及"如何处理"。

    priority 越小优先级越高，同一事件的多个钩子按 priority 升序执行。
    """

    name: str                # 钩子唯一标识名称，用于注册/注销
    event_type: str          # 监听的事件类型；"*" 表示监听所有事件
    handler: HookHandler     # 事件触发时调用的异步处理函数
    description: str = ""   # 钩子功能描述，用于 list_hooks() 展示
    priority: int = 100      # 执行优先级，数值越小越先执行

class EventBus:
    """
    中央事件总线，实现基于钩子的松耦合通信机制。

    OpenClaw 模式：组件通过 emit() 发出事件，钩子通过 register() 订阅事件。
    新功能无需修改现有代码即可通过注册钩子响应任意事件，实现开闭原则。

    钩子分为两类：
    - 全局钩子（event_type="*"）：响应所有事件；
    - 具体钩子（event_type=某事件类型）：只响应指定类型的事件。
    """

    def __init__(self) -> None:
        """
        初始化事件总线，创建空的钩子注册表。

        :return: None
        """
        # 按事件类型分组存储的具体钩子，key 为事件类型字符串
        self._hooks: dict[str, list[Hook]] = {}
        # 监听所有事件的全局钩子列表（event_type="*"）
        self._global_hooks: list[Hook] = []

    def register(self, hook: Hook) -> None:
        """
        向事件总线注册一个钩子。

        若 hook.event_type 为 "*"，则注册为全局钩子，响应所有事件；
        否则注册为具体类型钩子，仅响应对应类型的事件。
        注册后按 priority 升序排列，确保执行顺序正确。

        :param hook: 要注册的 Hook 实例。
        :return: None
        """
        if hook.event_type == "*":
            # 全局钩子：监听所有事件类型
            self._global_hooks.append(hook)
            self._global_hooks.sort(key=lambda h: h.priority)
        else:
            # 具体类型钩子：仅监听指定事件
            if hook.event_type not in self._hooks:
                self._hooks[hook.event_type] = []
            self._hooks[hook.event_type].append(hook)
            # 保持同类型钩子按优先级有序
            self._hooks[hook.event_type].sort(key=lambda h: h.priority)
        logger.info(f"Hook registered: '{hook.name}' → {hook.event_type}")

    def unregister(self, name: str) -> None:
        """
        按名称注销一个已注册的钩子。

        会同时从具体类型钩子表和全局钩子列表中移除匹配项。

        :param name: 要注销的钩子名称。
        :return: None
        """
        # 从所有具体类型钩子中移除同名钩子
        for event_type, hooks in self._hooks.items():
            self._hooks[event_type] = [h for h in hooks if h.name != name]
        # 从全局钩子列表中移除同名钩子
        self._global_hooks = [h for h in self._global_hooks if h.name != name]

    async def emit(self, event: HookEvent) -> None:
        """
        发出一个事件，触发所有匹配的钩子处理器。

        执行顺序：先合并全局钩子和具体类型钩子，再按 priority 升序统一排序执行。
        单个钩子处理失败不会中断其他钩子的执行。

        :param event: 要发出的 HookEvent 实例。
        :return: None
        """
        # 先收集全局钩子（监听所有事件）
        handlers = list(self._global_hooks)
        # 再追加匹配当前事件类型的具体钩子
        if event.type in self._hooks:
            handlers.extend(self._hooks[event.type])
        # 合并后按优先级重新排序，确保跨类型的优先级语义正确
        handlers.sort(key=lambda h: h.priority)

        for hook in handlers:
            try:
                await hook.handler(event)
            except Exception as e:
                # 单个钩子失败只记录日志，不影响其他钩子继续执行
                logger.error(f"Hook '{hook.name}' failed on '{event.type}': {e}")

    def list_hooks(self) -> list[dict[str, Any]]:
        """
        返回所有已注册钩子的摘要信息列表，常用于状态查询和调试。

        :return: 包含每个钩子 name、event_type、description、priority 字段的字典列表。
        """
        # 合并全局钩子和所有具体类型钩子
        all_hooks = list(self._global_hooks)
        for hooks in self._hooks.values():
            all_hooks.extend(hooks)
        return [
            {
                "name": h.name,
                "event_type": h.event_type,
                "description": h.description,
                "priority": h.priority,
            }
            for h in all_hooks
        ]



# MiniClaw 中使用的标准事件类型
EVENT_SESSION_CREATED = "session.created"
EVENT_SESSION_RESET = "session.reset"
EVENT_MESSAGE_RECEIVED = "message.received"
EVENT_MESSAGE_SENT = "message.sent"
EVENT_TOOL_EXECUTED = "tool.executed"
EVENT_TOOL_ERROR = "tool.error"
EVENT_HEARTBEAT_ALERT = "heartbeat.alert"
EVENT_HEARTBEAT_OK = "heartbeat.ok"
EVENT_CRON_EXECUTED = "cron.executed"
EVENT_AGENT_SPAWNED = "agent.spawned"
EVENT_CONTEXT_COMPACTED = "context.compacted"
EVENT_REFLECTION_DONE = "reflection.done"

