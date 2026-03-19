#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: cron.py
# @Description: 定时任务
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/19 14:42
# @Version: 1.0

"""
Cron——定时任务执行。
与 Heartbeat（固定间隔、通用检查）不同，Cron 会在特定时间运行特定任务。
每个 Cron 任务都有自己的提示符和计划。

OpenClaw 对 Cron 和 Heartbeat 的区别在于：
- Heartbeat：“唤醒并检查是否有需要注意的事项”（通用）
- Cron：“在特定时间执行特定操作”（目标明确）
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Awaitable

from miniclaw.agents import Agent

logger = logging.getLogger(__name__)


@dataclass
class CronJob:
    """
    单个定时任务的配置数据类。

    schedule 支持两种格式：
    - "HH:MM"：每天在指定时刻执行一次（如 "09:00"）；
    - "*/N"：每隔 N 分钟执行一次（如 "*/30"）。
    """

    name: str                        # 任务唯一标识名称，用于日志和手动触发
    schedule: str                    # 调度表达式："HH:MM" 或 "*/N"
    prompt: str                      # 发送给 Agent 的指令文本
    enabled: bool = True             # 是否启用，False 时跳过调度检查
    last_run: datetime | None = None # 上次成功执行的时间，用于间隔计算


class CronScheduler:
    """
    定时任务调度器，按配置的时间表周期性执行指定任务。

    每分钟检查一次所有已注册的 CronJob，判断是否到达执行时间，
    到达则将对应 prompt 发送给 Agent 并将响应通过输出回调推送出去。
    """

    def __init__(self, agent: Agent):
        """
        初始化定时任务调度器。

        :param agent: 执行定时任务 prompt 的 Agent 实例。
        """
        # 绑定的 Agent，所有 cron 任务的 prompt 都通过它处理
        self.agent = agent
        # 已注册的定时任务列表
        self._jobs: list[CronJob] = []
        # 后台调度循环的 asyncio Task 句柄
        self._task: asyncio.Task | None = None
        # 控制调度循环是否继续运行的标志位
        self._running = False
        # 任务执行结果的输出回调，签名为 (job_name: str, response: str) -> None
        self._on_output: Callable[[str, str], Awaitable[None]] | None = None

    def add_job(self, job: CronJob) -> None:
        """
        向调度器注册一个新的定时任务。

        :param job: 要注册的 CronJob 实例。
        :return: None
        """
        self._jobs.append(job)
        logger.info(f"Cron job added: '{job.name}' schedule={job.schedule}")

    def set_output_handler(self, handler: Callable[[str, str], Awaitable[None]]) -> None:
        """
        设置任务执行结果的输出回调函数。

        回调在每次任务执行完成后被调用，可用于将结果推送到外部渠道（如 Discord）。

        :param handler: 异步回调，签名为 (job_name: str, response: str) -> None。
        :return: None
        """
        self._on_output = handler

    async def start(self) -> None:
        """
        启动调度器，在后台创建周期检查循环任务。

        若已在运行则直接返回，避免重复启动。

        :return: None
        """
        # 幂等保护：已运行时不重复启动
        if self._running:
            return
        self._running = True
        # 创建后台调度循环，不阻塞当前协程
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Cron scheduler started ({len(self._jobs)} jobs)")

    async def stop(self) -> None:
        """
        停止调度器，取消后台循环并等待其退出。

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

    async def _loop(self) -> None:
        """
        调度器主循环，每 60 秒检查一次所有任务是否到达执行时间。

        :return: None
        """
        while self._running:
            try:
                # 每分钟检查一次，与 cron 最小粒度对齐
                await asyncio.sleep(60)
                if not self._running:
                    break
                await self._check_jobs()
            except asyncio.CancelledError:
                # 收到取消信号时正常退出循环
                break
            except Exception as e:
                logger.error(f"Cron error: {e}")

    async def _check_jobs(self) -> None:
        """
        遍历所有已注册任务，对满足执行条件的任务触发执行。

        :return: None
        """
        now = datetime.now()
        for job in self._jobs:
            # 跳过已禁用的任务
            if not job.enabled:
                continue
            if self._should_run(job, now):
                await self._execute_job(job, now)

    def _should_run(self, job: CronJob, now: datetime) -> bool:
        """
        判断指定任务在当前时刻是否应该执行。

        支持两种调度格式：
        - "*/N"：每隔 N 分钟执行，基于 last_run 计算已过去的时间；
        - "HH:MM"：每天在指定时刻执行，同一天内只执行一次。

        :param job: 要判断的 CronJob 实例。
        :param now: 当前时间。
        :return: True 表示应执行，False 表示跳过。
        """
        if job.schedule.startswith("*/"):
            # 间隔模式：每 N 分钟执行一次
            try:
                interval = int(job.schedule[2:])
            except ValueError:
                return False
            # 从未执行过则立即执行
            if job.last_run is None:
                return True
            elapsed = (now - job.last_run).total_seconds() / 60
            return elapsed >= interval

        if ":" in job.schedule:
            # 每日定时模式：在 HH:MM 执行，同一天内只触发一次
            try:
                hour, minute = map(int, job.schedule.split(":"))
            except ValueError:
                return False
            if now.hour == hour and now.minute == minute:
                # 从未执行过，或今天尚未执行过
                if job.last_run is None or job.last_run.date() != now.date():
                    return True
            return False

        # 未知格式，跳过
        return False

    async def _execute_job(self, job: CronJob, now: datetime) -> None:
        """
        执行指定的定时任务：将 prompt 发送给 Agent，并将响应通过输出回调推送。

        :param job: 要执行的 CronJob 实例。
        :param now: 本次执行的时间戳，用于更新 last_run。
        :return: None
        """
        logger.info(f"Cron executing: '{job.name}'")
        # 先更新 last_run，防止执行期间被重复触发
        job.last_run = now

        try:
            # 在 prompt 前加上 [CRON: name] 前缀，让 Agent 知晓任务来源
            response = await self.agent.process_message(
                f"[CRON: {job.name}] {job.prompt}"
            )
            # 将执行结果通过输出回调推送到外部渠道
            if self._on_output:
                await self._on_output(job.name, response)
            logger.info(f"Cron '{job.name}' completed: {response[:100]}")
        except Exception as e:
            logger.error(f"Cron '{job.name}' failed: {e}")

    async def run_job_now(self, name: str) -> str | None:
        """
        按名称手动立即触发一个定时任务，常用于调试或测试。

        :param name: 要触发的任务名称。
        :return: 执行成功的提示字符串；若任务不存在则返回错误提示。
        """
        for job in self._jobs:
            if job.name == name:
                await self._execute_job(job, datetime.now())
                return f"Job '{name}' executed"
        return f"Job '{name}' not found"

    def list_jobs(self) -> list[dict[str, Any]]:
        """
        返回所有已注册定时任务的摘要信息列表，常用于状态查询和调试。

        :return: 包含每个任务 name、schedule、enabled、last_run 字段的字典列表。
        """
        return [
            {
                "name": j.name,
                "schedule": j.schedule,
                "enabled": j.enabled,
                # last_run 为 None 时返回 None，否则转为字符串便于序列化
                "last_run": str(j.last_run) if j.last_run else None,
            }
            for j in self._jobs
        ]

