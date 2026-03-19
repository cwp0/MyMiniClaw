#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: gateway.py
# @Description: OpenClaw的网关组件
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/19 14:53
# @Version: 1.0

"""Gateway — the central control plane.

OpenClaw's Gateway is the single source of truth that coordinates:
- Agent lifecycle management
- Message queue (serial per-session)
- Session persistence & recovery
- Heartbeat scheduling
- Cron scheduling
- Channel multiplexing
- Health monitoring
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Awaitable

from miniclaw.agents import Agent, AgentOrchestrator
from miniclaw.brain import Message
from miniclaw.config import Config
from miniclaw.cron import CronScheduler, CronJob
from miniclaw.heartbeat import Heartbeat
from miniclaw.hooks import (
    EventBus, Hook, HookEvent,
    EVENT_MESSAGE_RECEIVED, EVENT_MESSAGE_SENT,
    EVENT_HEARTBEAT_ALERT, EVENT_CRON_EXECUTED,
)

logger = logging.getLogger(__name__)

# 消息处理器类型别名：接收 (agent_id, response) 两个字符串参数，返回协程
MessageHandler = Callable[[str, str], Awaitable[None]]  # (agent_id, response) → deliver


class Gateway:
    """
    中央控制平面，负责协调 Agent、心跳检测和多渠道通信。

    Gateway 是整个 OpenClaw 系统的核心枢纽，统一管理以下职责：
    - Agent 生命周期：创建、路由、会话恢复
    - 心跳调度：定期触发 Agent 执行健康检查或主动推送
    - Cron 调度：支持按时间表周期性触发 Agent 任务
    - 事件总线：通过 Hook 机制对外暴露系统事件
    - 多渠道分发：将 Agent 响应投递到所有已注册的输出渠道
    - 健康监控：对外暴露运行状态快照
    """

    def __init__(self, config: Config):
        """
        初始化 Gateway，依据配置构建各核心子系统。

        :param config: 全局配置对象，包含 Agent 定义、目录路径等信息。
        """
        self.config = config
        # Agent 编排器，负责 Agent 实例的创建与查找
        self.orchestrator = AgentOrchestrator(config)
        # 事件总线，用于发布/订阅系统内部事件
        self.events = EventBus()
        # 各 Agent 的心跳实例，key 为 agent_id
        self._heartbeats: dict[str, Heartbeat] = {}
        # 各 Agent 的 Cron 调度器，key 为 agent_id
        self._cron_schedulers: dict[str, CronScheduler] = {}
        # 已注册的消息投递处理器列表（对应各输出渠道）
        self._message_handlers: list[MessageHandler] = []
        # 会话持久化目录，每个 Agent 对应一个 .jsonl 文件
        self._session_dir = config.config_dir / "sessions"
        # Gateway 运行状态标志
        self._running = False
        # Gateway 启动时间戳，用于计算运行时长
        self._start_time: float = 0
        # 累计处理的请求总数
        self._request_count: int = 0
        # 累计发生的错误总数
        self._error_count: int = 0

    async def start(self) -> None:
        """
        启动 Gateway，完成所有 Agent 的初始化、会话恢复、心跳和 Cron 调度。

        按顺序执行以下步骤：
        1. 标记运行状态并记录启动时间
        2. 确保会话持久化目录存在
        3. 遍历配置中的所有 Agent，逐一完成初始化
        4. 若存在 Cron 调度器，统一启动
        """
        self._running = True
        self._start_time = time.time()
        # 确保会话目录存在，首次运行时自动创建
        self._session_dir.mkdir(parents=True, exist_ok=True)

        for agent_id, agent_def in self.config.agents.items():
            # 获取或创建 Agent 实例
            agent = self.orchestrator.get_or_create_agent(agent_id)
            # 初始化 Agent 的默认记忆（如系统提示词等）
            agent.memory.create_defaults()
            # 从磁盘恢复上次会话的对话历史
            self._restore_session(agent_id, agent)
            # 向 Agent 注册 cron_add / cron_list 工具，使其可在对话中管理定时任务
            self._register_cron_tools(agent_id)

            # 若该 Agent 配置了心跳，则创建并启动心跳实例
            if agent_def.heartbeat.enabled:
                hb = Heartbeat(
                    agent=agent,
                    interval_minutes=agent_def.heartbeat.interval_minutes,
                )

                # 心跳触发时的回调：将响应投递到渠道，并向事件总线发布告警事件
                async def _hb_alert(response: str, aid: str = agent_id) -> None:
                    # 将心跳响应投递给所有已注册的消息处理器
                    await self._deliver(aid, response)
                    # 发布心跳告警事件，供外部 Hook 订阅处理
                    await self.events.emit(HookEvent(
                        type=EVENT_HEARTBEAT_ALERT,
                        payload={"agent_id": aid, "alert": response[:200]},
                        source="heartbeat",
                    ))

                hb.set_alert_handler(_hb_alert)
                self._heartbeats[agent_id] = hb
                await hb.start()

            # 将配置中预定义的 Cron 任务注册到调度器
            for cj in agent_def.cron_jobs:
                # 仅当三个必填字段均不为空时才注册，避免无效任务入队
                if cj.name and cj.schedule and cj.prompt:
                    self.add_cron_job(agent_id, CronJob(
                        name=cj.name,
                        schedule=cj.schedule,
                        prompt=cj.prompt,
                    ))

        # 若存在任何 Cron 调度器，统一启动（避免在 add_cron_job 中重复启动）
        if self._cron_schedulers:
            await self.start_cron()

        logger.info(
            f"Gateway started: {len(self.config.agents)} agents, "
            f"{len(self._heartbeats)} heartbeats, "
            f"{len(self._cron_schedulers)} cron schedulers"
        )

    def _register_cron_tools(self, agent_id: str) -> None:
        """
        向指定 Agent 注册 cron_add 和 cron_list 两个内置工具。

        注册后，Agent 可在对话中通过工具调用来动态创建定时任务或查询任务列表，
        实现"对话驱动的任务调度"能力。

        :param agent_id: 目标 Agent 的唯一标识符。
        """
        agent = self.orchestrator.get_or_create_agent(agent_id)

        # --- 工具处理器：cron_add ---
        async def cron_add_handler(args: dict[str, Any]) -> str:
            """解析参数并创建新的 Cron 任务，返回确认消息。"""
            name = args["name"]
            schedule = args["schedule"]
            prompt = args["prompt"]
            # 将新任务注册到该 Agent 的调度器中
            self.add_cron_job(agent_id, CronJob(
                name=name, schedule=schedule, prompt=prompt,
            ))
            return (
                f"Cron job '{name}' created (schedule: {schedule}). "
                f"When triggered, I will: {prompt[:100]}"
            )

        # --- 工具处理器：cron_list ---
        async def cron_list_handler(args: dict[str, Any]) -> str:
            """查询该 Agent 当前所有 Cron 任务并格式化返回。"""
            scheduler = self._cron_schedulers.get(agent_id)
            if not scheduler:
                return "No cron jobs scheduled."
            jobs = scheduler.list_jobs()
            if not jobs:
                return "No cron jobs scheduled."
            # 将每个任务格式化为一行，包含名称、调度表达式、启用状态和上次执行时间
            lines = [f"- {j['name']}: schedule={j['schedule']}, enabled={j['enabled']}, last_run={j['last_run']}" for j in jobs]
            return "\n".join(lines)

        # 向 Agent 的工具注册表注册 cron_add，附带 JSON Schema 描述供 LLM 理解
        agent.hands.register_tool("cron_add", cron_add_handler, {
            "name": "cron_add",
            "description": (
                "Schedule a recurring or one-time task. The agent will be prompted "
                "with the given message at the scheduled time. "
                "Schedule formats: 'HH:MM' for daily at specific time, '*/N' for every N minutes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Unique name for the cron job"},
                    "schedule": {
                        "type": "string",
                        "description": "Schedule: 'HH:MM' for daily, '*/N' for every N minutes (e.g. '*/5' = every 5 min, '20:30' = daily at 20:30)",
                    },
                    "prompt": {"type": "string", "description": "What the agent should do when triggered"},
                },
                "required": ["name", "schedule", "prompt"],
            },
        })

        # 向 Agent 的工具注册表注册 cron_list
        agent.hands.register_tool("cron_list", cron_list_handler, {
            "name": "cron_list",
            "description": "List all scheduled cron jobs and their status.",
            "parameters": {"type": "object", "properties": {}},
        })

    def add_cron_job(self, agent_id: str, job: CronJob) -> None:
        """
        为指定 Agent 添加一个 Cron 定时任务。

        若该 Agent 尚未拥有调度器，则自动创建并配置输出处理器。
        若 Gateway 已处于运行状态，则立即异步启动新创建的调度器。

        :param agent_id: 目标 Agent 的唯一标识符。
        :param job: 要添加的 CronJob 对象，包含名称、调度表达式和触发提示词。
        """
        agent = self.orchestrator.get_or_create_agent(agent_id)
        # 标记是否需要在添加任务后立即启动调度器
        need_start = False

        if agent_id not in self._cron_schedulers:
            # 该 Agent 尚无调度器，创建新实例
            scheduler = CronScheduler(agent)

            # Cron 任务执行完毕后的输出回调：投递响应并发布事件
            async def _cron_output(name: str, response: str, aid: str = agent_id) -> None:
                # 在响应前缀中标注触发来源，便于渠道侧区分消息类型
                await self._deliver(aid, f"[Cron: {name}] {response}")
                # 发布 Cron 执行事件，供外部 Hook 订阅
                await self.events.emit(HookEvent(
                    type=EVENT_CRON_EXECUTED,
                    payload={"agent_id": aid, "job_name": name},
                    source="cron",
                ))

            scheduler.set_output_handler(_cron_output)
            self._cron_schedulers[agent_id] = scheduler
            # 仅当 Gateway 已启动时才需要立即启动调度器；
            # 若 Gateway 尚未启动，start() 中的 start_cron() 会统一处理
            need_start = self._running

        # 将任务加入调度器
        self._cron_schedulers[agent_id].add_job(job)

        # Gateway 运行中动态添加的调度器需要立即启动
        if need_start:
            asyncio.ensure_future(self._cron_schedulers[agent_id].start())

    async def start_cron(self) -> None:
        """
        统一启动所有已注册的 Cron 调度器。

        通常由 start() 在 Gateway 初始化完成后调用，确保所有调度器同步启动。
        """
        for scheduler in self._cron_schedulers.values():
            await scheduler.start()

    async def stop(self) -> None:
        """
        优雅停止 Gateway，依次停止所有心跳和 Cron 调度器。

        将运行标志置为 False 后，逐一等待各子系统完成清理，避免任务中途中断。
        """
        self._running = False
        # 停止所有心跳实例
        for hb in self._heartbeats.values():
            await hb.stop()
        # 停止所有 Cron 调度器
        for scheduler in self._cron_schedulers.values():
            await scheduler.stop()
        logger.info("Gateway stopped")

    def on_message(self, handler: MessageHandler) -> None:
        """
        注册一个消息投递处理器（输出渠道）。

        每当 Agent 产生响应时，Gateway 会依次调用所有已注册的处理器，
        实现将同一响应同时投递到多个渠道（如 CLI、Discord 等）。

        :param handler: 异步回调函数，签名为 (agent_id: str, response: str) -> None。
        """
        self._message_handlers.append(handler)

    def register_hook(self, hook: Hook) -> None:
        """
        向 Gateway 的事件总线注册一个 Hook。

        Hook 可订阅系统内部事件（如消息收发、心跳告警、Cron 执行等），
        用于实现日志记录、监控告警、二次处理等扩展逻辑。

        :param hook: 要注册的 Hook 对象，需实现事件过滤和处理逻辑。
        """
        self.events.register(hook)

    async def handle_input(
        self, text: str, agent_id: str = "main"
    ) -> str:
        """
        处理来自用户或渠道的输入消息，经路由后交由对应 Agent 生成响应。

        完整流程：
        1. 递增请求计数并发布消息接收事件
        2. 通过 Router 判断是否需要转发到其他 Agent
        3. 调用目标 Agent 处理消息并获取响应
        4. 将响应投递到所有渠道，并持久化会话记录
        5. 发布消息发送事件后返回响应文本

        :param text: 用户输入的原始文本。
        :param agent_id: 指定处理该消息的 Agent ID，默认为 "main"。
        :return: Agent 生成的响应文本。
        :raises Exception: 处理过程中的任何异常均会在记录错误后向上抛出。
        """
        # 累计请求计数，用于健康监控统计
        self._request_count += 1
        # 发布消息接收事件，触发相关 Hook（如日志记录）
        await self.events.emit(HookEvent(
            type=EVENT_MESSAGE_RECEIVED,
            payload={"text": text, "agent_id": agent_id},
            source="gateway",
        ))
        try:
            agent = self.orchestrator.get_or_create_agent(agent_id)
            # 通过路由器判断该消息应由哪个 Agent 处理
            route = agent.router.route(text, agent_id)

            if route.target_agent != agent_id:
                # 路由结果指向其他 Agent，转发消息并以目标 Agent 身份投递响应
                target_agent = self.orchestrator.get_or_create_agent(route.target_agent)
                response = await target_agent.process_message(text)
                await self._deliver(route.target_agent, response)
                self._save_session(route.target_agent, text, response)
            else:
                # 路由结果指向当前 Agent，直接处理
                response = await agent.process_message(text)
                await self._deliver(agent_id, response)
                self._save_session(agent_id, text, response)

            # 发布消息发送事件，供外部 Hook 统计响应长度等指标
            await self.events.emit(HookEvent(
                type=EVENT_MESSAGE_SENT,
                payload={"agent_id": agent_id, "response_length": len(response)},
                source="gateway",
            ))
            return response
        except Exception as e:
            # 累计错误计数并记录日志，异常继续向上传播
            self._error_count += 1
            logger.error(f"handle_input error for agent '{agent_id}': {e}")
            raise

    def health(self) -> dict[str, Any]:
        """
        返回 Gateway 当前的健康状态快照，供监控系统或运维接口调用。

        快照包含：运行状态、运行时长、请求/错误统计、各 Agent 详情、
        心跳/Cron/Hook/渠道数量以及当前时间戳。

        :return: 包含健康状态信息的字典。
        """
        # 计算自启动以来的运行时长（秒）
        uptime = time.time() - self._start_time if self._start_time else 0

        # 收集每个 Agent 的运行时详情
        agents_info = {}
        for aid in self.orchestrator.list_agents():
            agent = self.orchestrator.get_or_create_agent(aid)
            agents_info[aid] = {
                "context_messages": len(agent.context.history),   # 当前上下文消息数
                "turn_count": agent._turn_count,                   # 累计对话轮次
                "skills": len(agent.skill_registry.list_skills()), # 已注册技能数
            }

        return {
            "status": "healthy" if self._running else "stopped",
            "uptime_seconds": round(uptime, 1),
            "requests": self._request_count,
            "errors": self._error_count,
            "agents": agents_info,
            "heartbeats": list(self._heartbeats.keys()),
            "cron_schedulers": list(self._cron_schedulers.keys()),
            "hooks": len(self.events.list_hooks()),
            "channels": len(self._message_handlers),
            "timestamp": datetime.now().isoformat(),
        }

    async def _deliver(self, agent_id: str, response: str) -> None:
        """
        将 Agent 响应投递到所有已注册的消息处理器（输出渠道）。

        采用"尽力投递"策略：单个处理器抛出异常时仅记录日志，不影响其他处理器的执行。

        :param agent_id: 产生响应的 Agent ID，随响应一起传递给处理器。
        :param response: 需要投递的响应文本。
        """
        for handler in self._message_handlers:
            try:
                await handler(agent_id, response)
            except Exception as e:
                # 单个渠道投递失败不应影响其他渠道，记录日志后继续
                logger.error(f"Delivery handler error: {e}")

    def _save_session(self, agent_id: str, user_input: str, response: str) -> None:
        """
        将本轮对话记录以追加方式持久化到对应 Agent 的会话文件中。

        会话文件为 JSONL 格式（每行一个 JSON 对象），路径为：
        <config_dir>/sessions/<agent_id>.jsonl

        为控制存储大小，用户输入截取前 1000 字符，响应截取前 2000 字符。

        :param agent_id: 产生本轮对话的 Agent ID。
        :param user_input: 用户输入的原始文本。
        :param response: Agent 生成的响应文本。
        """
        session_file = self._session_dir / f"{agent_id}.jsonl"
        with open(session_file, "a", encoding="utf-8") as f:
            entry = {
                "ts": datetime.now().isoformat(),
                "user": user_input[:1000],     # 截断过长的用户输入
                "assistant": response[:2000],  # 截断过长的 Agent 响应
            }
            # ensure_ascii=False 保留中文等非 ASCII 字符的原始编码
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _restore_session(self, agent_id: str, agent: Agent) -> None:
        """
        在 Gateway 启动时，从持久化文件中恢复指定 Agent 的历史对话记录。

        恢复策略：
        - 最多恢复最近 20 条记录（max_restore），避免上下文过长
        - 跳过格式损坏的 JSON 行，保证健壮性
        - 按 user / assistant 角色依次注入到 Agent 的上下文中

        :param agent_id: 目标 Agent 的唯一标识符。
        :param agent: 目标 Agent 实例，恢复的消息将注入其上下文。
        """
        session_file = self._session_dir / f"{agent_id}.jsonl"
        # 若会话文件不存在（首次启动），直接返回
        if not session_file.exists():
            return

        try:
            lines = session_file.read_text(encoding="utf-8").strip().split("\n")
            restored = 0
            # 最多恢复的历史条目数，防止上下文窗口溢出
            max_restore = 20

            # 解析所有有效的 JSON 行，跳过空行和格式错误的行
            entries = []
            for line in lines:
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        # 忽略损坏的行，继续处理其余记录
                        continue

            # 仅取最近的 max_restore 条记录注入上下文
            for entry in entries[-max_restore:]:
                user_text = entry.get("user", "")
                assistant_text = entry.get("assistant", "")
                if user_text:
                    # 将用户消息注入 Agent 上下文
                    agent.context.add_message(Message(role="user", content=user_text))
                    restored += 1
                if assistant_text:
                    # 将 Assistant 消息注入 Agent 上下文，保持对话连贯性
                    agent.context.add_message(Message(role="assistant", content=assistant_text))
                    restored += 1

            if restored > 0:
                logger.info(f"Restored {restored} messages for agent '{agent_id}'")
        except Exception as e:
            # 会话恢复失败不应阻断启动流程，降级为警告日志
            logger.warning(f"Session restore failed for '{agent_id}': {e}")
