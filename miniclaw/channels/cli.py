#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: cli.py
# @Description: CLI channel
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/19 14:43
# @Version: 1.0



"""CLI channel — interactive terminal chat."""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from miniclaw.channels.base import Channel
from miniclaw.gateway import Gateway


class CLIChannel(Channel):
    """
    基于终端的交互式对话渠道，使用 Rich 库进行富文本格式化输出。

    支持斜杠命令（/quit、/skills、/agents 等），并将用户输入
    通过 Gateway 路由给指定 Agent，再将响应以 Markdown 形式渲染到终端。
    """

    def __init__(self, gateway: Gateway, agent_id: str = "main"):
        """
        初始化 CLI 渠道。

        :param gateway: 负责消息路由和 Agent 编排的网关对象。
        :param agent_id: 本渠道默认对话的 Agent 标识，默认为 "main"。
        """
        super().__init__(gateway, agent_id)
        # Rich Console 实例，用于带样式的终端输出
        self.console = Console()
        # 控制主循环是否继续运行的标志位
        self._running = False

    async def start(self) -> None:
        """
        启动 CLI 渠道，进入交互式输入循环。

        流程：
        1. 打印欢迎面板；
        2. 向 Gateway 注册响应回调，以便接收其他 Agent 的广播消息；
        3. 循环读取用户输入，区分斜杠命令和普通对话，分别处理；
        4. 遇到 EOFError / KeyboardInterrupt 或 /quit 命令时退出循环。

        :return: None
        """
        self._running = True

        # 打印欢迎面板，展示 Agent 名称和可用命令提示
        self.console.print(
            Panel(
                "[bold green]MiniClaw[/] - A minimal OpenClaw implementation\n"
                f"Agent: [cyan]{self.agent_id}[/] | "
                f"Type [bold]/quit[/] to exit, [bold]/skills[/] to list skills",
                title="Welcome",
            )
        )

        # 注册消息回调，用于接收来自其他 Agent 的广播响应
        self.gateway.on_message(self._on_response)

        while self._running:
            try:
                # 在线程池中执行阻塞式 input()，避免阻塞事件循环
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, self._read_input
                )
            except (EOFError, KeyboardInterrupt):
                # 管道关闭或 Ctrl+C 时优雅退出
                break

            # 跳过空输入
            if not user_input:
                continue

            # 以 "/" 开头的输入视为内部命令，交由命令处理器处理
            if user_input.startswith("/"):
                should_continue = await self._handle_command(user_input)
                if not should_continue:
                    break
                continue

            # 普通对话：显示思考提示，然后将输入发送给 Agent
            self.console.print("[dim]Thinking...[/]")

            try:
                response = await self.gateway.handle_input(
                    user_input, agent_id=self.agent_id
                )
                # 将 Agent 响应渲染为 Markdown 输出到终端
                await self.send(response)
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/]")

    def _read_input(self) -> str:
        """
        从标准输入读取一行用户输入（阻塞式）。

        在 EOFError（如管道关闭）时返回 "/quit" 以触发退出流程。

        :return: 用户输入的字符串，已去除首尾空白；异常时返回 "/quit"。
        """
        try:
            return input("\n🐾 > ").strip()
        except EOFError:
            # 标准输入关闭时，模拟用户输入 /quit 以触发正常退出
            return "/quit"

    async def stop(self) -> None:
        """
        停止 CLI 渠道，退出主循环并打印告别信息。

        :return: None
        """
        self._running = False
        self.console.print("[dim]Goodbye![/]")

    async def send(self, message: str) -> None:
        """
        将消息以 Markdown 格式渲染并输出到终端。

        :param message: 要输出的 Markdown 格式文本。
        :return: None
        """
        # 先打印空行，保持输出间距美观
        self.console.print()
        self.console.print(Markdown(message))

    async def _on_response(self, agent_id: str, response: str) -> None:
        """
        Gateway 广播回调：接收来自其他 Agent 的响应并输出到终端。

        仅处理非本渠道 Agent 的消息，避免重复显示当前 Agent 的响应。

        :param agent_id: 发出响应的 Agent 标识。
        :param response: Agent 响应的文本内容。
        :return: None
        """
        # 只处理其他 Agent 的广播消息，当前 Agent 的响应已在主循环中处理
        if agent_id != self.agent_id:
            self.console.print(f"\n[dim]📢 [{agent_id}][/]")
            self.console.print(Markdown(response))

    async def _handle_command(self, command: str) -> bool:
        """
        处理以 "/" 开头的内部斜杠命令。

        支持的命令：
        - /quit      退出程序
        - /skills    列出当前 Agent 已注册的所有技能
        - /agents    列出 Orchestrator 管理的所有 Agent
        - /compact   压缩当前上下文，生成摘要以节省 Token
        - /clear     清空当前 Agent 的对话上下文
        - /heartbeat 手动触发一次心跳检查

        :param command: 用户输入的完整命令字符串（含参数）。
        :return: True 表示继续运行主循环，False 表示应退出。
        """
        parts = command.split()
        # 取第一个词作为命令名，统一转为小写
        cmd = parts[0].lower()

        if cmd == "/quit":
            # 调用 stop() 打印告别信息并将 _running 置为 False
            await self.stop()
            return False

        if cmd == "/skills":
            # 获取当前 Agent 实例，查询其技能注册表
            agent = self.gateway.orchestrator.get_or_create_agent(self.agent_id)
            skills = agent.skill_registry.list_skills()
            if skills:
                self.console.print("[bold]Available Skills:[/]")
                for s in skills:
                    self.console.print(f"  • [cyan]{s['name']}[/] — {s['description']}")
            else:
                self.console.print("[dim]No skills loaded.[/]")
            return True

        if cmd == "/agents":
            # 列出 Orchestrator 当前管理的所有 Agent 标识
            agents = self.gateway.orchestrator.list_agents()
            self.console.print(f"[bold]Agents:[/] {', '.join(agents)}")
            return True

        if cmd == "/compact":
            # 调用 Context.compact() 将历史消息压缩为摘要，释放上下文空间
            agent = self.gateway.orchestrator.get_or_create_agent(self.agent_id)
            summary = await agent.context.compact(
                agent.brain,
                agent.memory.assemble_bootstrap(),
            )
            # 仅展示摘要的前 200 个字符，避免输出过长
            self.console.print(f"[dim]Compacted. Summary: {summary[:200]}...[/]")
            return True

        if cmd == "/clear":
            # 清空对话上下文，相当于开启新会话
            agent = self.gateway.orchestrator.get_or_create_agent(self.agent_id)
            agent.context.clear()
            self.console.print("[dim]Context cleared.[/]")
            return True

        if cmd == "/heartbeat":
            # 手动触发心跳，通常用于调试定时任务的输出
            hb = self.gateway._heartbeats.get(self.agent_id)
            if hb:
                result = await hb.tick()
                if result:
                    # 有实质性输出则渲染到终端
                    await self.send(result)
                else:
                    self.console.print("[dim]Heartbeat: nothing to report.[/]")
            else:
                self.console.print("[dim]No heartbeat configured.[/]")
            return True

        # 未识别的命令，提示用户可用命令列表
        self.console.print(
            f"[yellow]Unknown command: {cmd}[/]\n"
            "Available: /quit /skills /agents /compact /clear /heartbeat"
        )
        return True

