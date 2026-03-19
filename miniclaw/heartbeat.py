#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: heartbeat.py
# @Description: 心跳机制
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/19 14:42
# @Version: 1.0


"""
心跳机制——周期性自主检查。
OpenClaw 的心跳机制允许智能体在无需用户输入的情况下执行操作：

- 按可配置的间隔运行（默认 30 分钟）
- 读取 HEARTBEAT.md 文件以获取指令
- 如果没有需要注意的事情，则回复 HEARTBEAT_OK（已隐藏）
- 如果有需要注意的事情，则将信息传递给配置的目标。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from miniclaw.agents import Agent

logger = logging.getLogger(__name__)

HEARTBEAT_OK = "HEARTBEAT_OK"


class Heartbeat:
    """
    周期性自主心跳检查器。

    按配置的时间间隔唤醒 Agent，让其读取 HEARTBEAT.md 中的指令并判断
    是否有需要关注的事项。若 Agent 回复 HEARTBEAT_OK 则静默忽略；
    否则触发告警回调，将响应推送到外部渠道（如 Discord）。
    """

    def __init__(self, agent: Agent, interval_minutes: int = 30):
        """
        初始化心跳检查器。

        :param agent: 执行心跳检查的 Agent 实例。
        :param interval_minutes: 心跳间隔，单位为分钟，默认 30 分钟。
        """
        # 绑定的 Agent，心跳 prompt 通过它处理
        self.agent = agent
        # 将分钟转换为秒，供 asyncio.sleep 使用
        self.interval = interval_minutes * 60
        # 后台心跳循环的 asyncio Task 句柄
        self._task: asyncio.Task | None = None
        # 控制心跳循环是否继续运行的标志位
        self._running = False
        # 告警回调：当心跳产生非 HEARTBEAT_OK 响应时调用
        self._on_alert: Any = None

    def set_alert_handler(self, handler) -> None:
        """
        设置告警回调函数，在心跳产生需要关注的响应时触发。

        :param handler: 异步回调，签名为 (response: str) -> None。
        :return: None
        """
        self._on_alert = handler

    async def start(self) -> None:
        """
        启动心跳检查器，在后台创建周期循环任务。

        若已在运行则直接返回，避免重复启动。

        :return: None
        """
        # 幂等保护：已运行时不重复启动
        if self._running:
            return
        self._running = True
        # 创建后台心跳循环，不阻塞当前协程
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Heartbeat started (every {self.interval // 60}min)")

    async def stop(self) -> None:
        """
        停止心跳检查器，取消后台循环并等待其退出。

        :return: None
        """
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                # 等待任务真正结束，捕获取消异常以避免警告
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Heartbeat stopped")

    async def _loop(self) -> None:
        """
        心跳检查器的主循环，按配置间隔周期性调用 tick()。

        发生非取消异常时额外等待 60 秒再重试，避免因瞬时错误导致频繁重试。

        :return: None
        """
        while self._running:
            try:
                # 等待一个完整的心跳间隔
                await asyncio.sleep(self.interval)
                if not self._running:
                    break
                await self.tick()
            except asyncio.CancelledError:
                # 收到取消信号时正常退出循环
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                # 出错后等待 60 秒再重试，防止错误风暴
                await asyncio.sleep(60)

    async def tick(self) -> str | None:
        """
        执行一次心跳检查周期。

        流程：
        1. 检查当前时间是否在活跃时段内，不在则跳过；
        2. 读取 HEARTBEAT.md，为空则跳过；
        3. 将固定 prompt 发送给 Agent；
        4. 若响应包含 HEARTBEAT_OK 则静默返回 None；
        5. 否则触发告警回调并返回响应文本。

        :return: Agent 的响应文本；若无需关注则返回 None。
        """
        # 非活跃时段（如深夜）跳过心跳，避免打扰
        if not self._is_active_hours():
            logger.debug("Heartbeat skipped: outside active hours")
            return None

        # 读取心跳指令文件，文件为空时跳过本次检查
        heartbeat_md = self.agent.memory.read_file("HEARTBEAT.md")
        if not heartbeat_md or not heartbeat_md.strip():
            logger.debug("Heartbeat skipped: HEARTBEAT.md empty")
            return None

        # 固定心跳 prompt：要求 Agent 严格按 HEARTBEAT.md 行事
        prompt = (
            "Read HEARTBEAT.md (shown in your context). Follow it strictly.\n"
            "Do not infer or repeat old tasks from prior chats.\n"
            "If nothing needs attention, reply HEARTBEAT_OK."
        )

        response = await self.agent.process_message(prompt)

        # Agent 回复 HEARTBEAT_OK 表示无需关注，静默丢弃
        if HEARTBEAT_OK in response:
            logger.debug("Heartbeat: OK (nothing to report)")
            return None

        # 有实质性内容，记录日志并触发告警回调
        logger.info(f"Heartbeat alert: {response[:200]}")

        if self._on_alert:
            await self._on_alert(response)

        return response

    def _is_active_hours(self) -> bool:
        """
        判断当前时间是否处于配置的活跃时段内。

        支持跨午夜的时段（如 22:00 - 02:00）。
        若配置缺失或格式错误，默认返回 True（始终活跃）。

        :return: True 表示当前处于活跃时段，False 表示应跳过心跳。
        """
        cfg = self.agent.agent_def.heartbeat
        now = datetime.now()
        try:
            start_h, start_m = map(int, cfg.active_hours_start.split(":"))
            end_h, end_m = map(int, cfg.active_hours_end.split(":"))
            start = now.replace(hour=start_h, minute=start_m, second=0)
            end = now.replace(hour=end_h, minute=end_m, second=0)
            if start <= end:
                # 普通时段（如 09:00 - 22:00），直接判断是否在区间内
                return start <= now <= end
            # 跨午夜时段（如 22:00 - 02:00），now 在 start 之后或 end 之前均视为活跃
            return now >= start or now <= end
        except (ValueError, AttributeError):
            # 配置缺失或格式错误时，默认全天活跃
            return True


