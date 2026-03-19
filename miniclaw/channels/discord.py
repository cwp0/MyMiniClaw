#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: discord.py
# @Description: Discord channel
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/19 14:43
# @Version: 1.0

"""Discord channel — connects MiniClaw to a Discord bot.

Requires: pip install discord.py
Set DISCORD_BOT_TOKEN in config or environment.

The bot listens for DMs and mentions, routes them through Gateway,
and sends responses back to the same channel.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from miniclaw.channels.base import Channel
from miniclaw.gateway import Gateway

logger = logging.getLogger(__name__)


class DiscordChannel(Channel):
    """
    基于 discord.py 的 Discord Bot 渠道。

    支持以下三种触发场景：
    - 私信（DM）：Bot 收到任意私信时响应；
    - @提及：在任意频道中被 @mention 时响应；
    - 白名单频道：在 allowed_channels 指定的频道中，所有消息均响应。

    心跳/定时任务产生的主动推送消息会发送到 alert_channel_id 指定的频道，
    若未配置则回退到最近一次有交互的频道。
    """

    def __init__(
        self,
        gateway: Gateway,
        token: str,
        agent_id: str = "main",
        allowed_channels: list[int] | None = None,
        alert_channel_id: int | None = None,
    ):
        """
        初始化 Discord 渠道。

        :param gateway: 负责消息路由和 Agent 编排的网关对象。
        :param token: Discord Bot Token，从 Discord Developer Portal 获取。
        :param agent_id: 本渠道默认对话的 Agent 标识，默认为 "main"。
        :param allowed_channels: 允许 Bot 响应的频道 ID 列表；为 None 时仅响应 DM 和 @提及。
        :param alert_channel_id: 主动推送告警消息的目标频道 ID；为 None 时回退到最近交互频道。
        """
        super().__init__(gateway, agent_id)
        # Bot 登录凭证
        self.token = token
        # 白名单频道列表，None 表示不限制（仅 DM 和 @提及触发）
        self.allowed_channels = allowed_channels
        # 告警推送目标频道 ID，用于心跳/定时任务的主动通知
        self.alert_channel_id = alert_channel_id
        # discord.Client 实例，在 start() 中创建
        self._client = None
        # 记录最近一次有交互的频道，作为告警推送的回退目标
        self._last_interaction_channel = None

    async def start(self) -> None:
        """
        启动 Discord Bot，注册事件监听器并连接到 Discord 网关。

        流程：
        1. 动态导入 discord.py（未安装时抛出友好错误）；
        2. 配置 Intents 并创建 Client 实例；
        3. 注册 on_ready 和 on_message 事件处理器；
        4. 向 Gateway 注册主动推送回调；
        5. 调用 client.start() 建立 WebSocket 连接（阻塞直到断开）。

        :return: None
        """
        try:
            import discord
        except ImportError:
            raise ImportError(
                "discord.py is required for Discord channel. "
                "Install with: pip install discord.py"
            )

        # 启用默认 Intents 并额外开启 message_content，以便读取消息正文
        intents = discord.Intents.default()
        intents.message_content = True

        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            """Bot 成功连接到 Discord 后触发，记录登录账号信息。"""
            logger.info(f"Discord bot connected as {self._client.user}")

        @self._client.event
        async def on_message(message: discord.Message):
            """
            监听所有可见消息，根据触发条件决定是否响应。

            触发条件（满足其一即响应）：
            - 消息来自私信频道（DMChannel）；
            - 消息中 @提及了 Bot；
            - 消息所在频道在 allowed_channels 白名单中。

            :param message: discord.py 的 Message 对象。
            """
            # 忽略 Bot 自身发出的消息，防止自我响应死循环
            if message.author == self._client.user:
                return

            should_respond = False

            # 场景一：私信频道，无条件响应
            if isinstance(message.channel, discord.DMChannel):
                should_respond = True

            # 场景二：消息中 @提及了 Bot
            elif self._client.user in message.mentions:
                should_respond = True

            # 场景三：消息所在频道在白名单中
            elif self.allowed_channels and message.channel.id in self.allowed_channels:
                should_respond = True

            if not should_respond:
                return

            # 去除消息中的 @Bot 提及标记，提取纯文本内容
            text = message.content
            if self._client.user:
                text = text.replace(f"<@{self._client.user.id}>", "").strip()

            # 去除提及后若消息为空则忽略
            if not text:
                return

            # 记录日志，仅打印前 100 个字符避免日志过长
            logger.info(
                f"Discord message from {message.author}: {text[:100]}"
            )

            # 记录本次交互的频道，作为后续告警推送的回退目标
            self._last_interaction_channel = message.channel

            # 显示"正在输入"状态，提升用户体验
            async with message.channel.typing():
                try:
                    response = await self.gateway.handle_input(
                        text, agent_id=self.agent_id
                    )
                    # Discord 单条消息上限为 2000 字符，超长时分片发送
                    for chunk in self._split_message(response):
                        await message.channel.send(chunk)
                except Exception as e:
                    logger.error(f"Discord handler error: {e}")
                    await message.channel.send(f"Error: {e}")

        # 向 Gateway 注册主动推送回调，用于接收心跳/定时任务的告警消息
        self.gateway.on_message(self._on_gateway_message)

        # 建立 WebSocket 连接，此调用会阻塞直到 Bot 断开连接
        await self._client.start(self.token)

    async def stop(self) -> None:
        """
        关闭 Discord Bot，断开与 Discord 网关的连接。

        :return: None
        """
        if self._client:
            await self._client.close()

    async def send(self, message: str) -> None:
        """
        通过渠道发送消息（Discord 渠道中此方法为空实现）。

        Discord 的消息发送在 on_message 事件处理器中按频道上下文完成，
        无法在此处统一发送，故此方法保留为空以满足基类接口约束。

        :param message: 要发送的文本内容（此处未使用）。
        :return: None
        """
        # Discord 发送逻辑在 on_message 中按频道上下文处理，此处无需实现
        pass

    async def _on_gateway_message(self, agent_id: str, response: str) -> None:
        """
        接收 Gateway 广播的主动推送消息（如心跳检查、定时任务结果），
        并将其发送到指定的告警频道。

        优先使用 alert_channel_id 指定的频道；若未配置，则回退到
        最近一次有用户交互的频道。

        :param agent_id: 发出消息的 Agent 标识。
        :param response: 需要推送的消息内容。
        :return: None
        """
        # Bot 尚未就绪时忽略推送，避免在连接建立前发送消息
        if not self._client or not self._client.is_ready():
            return

        channel = None
        if self.alert_channel_id:
            # 优先使用配置的专属告警频道
            channel = self._client.get_channel(self.alert_channel_id)
        elif self._last_interaction_channel:
            # 回退到最近有交互的频道
            channel = self._last_interaction_channel

        if channel:
            # 添加告警前缀，标明消息来源 Agent
            prefix = f"🔔 **[{agent_id}]**\n"
            for chunk in self._split_message(prefix + response):
                try:
                    await channel.send(chunk)
                except Exception as e:
                    logger.error(f"Failed to send alert to Discord: {e}")

    def _split_message(self, text: str, max_len: int = 1900) -> list[str]:
        """
        将超长文本按 Discord 消息长度限制拆分为多个片段。

        Discord 单条消息上限为 2000 字符，此处保守使用 1900 作为默认阈值，
        预留空间给 Markdown 渲染可能带来的额外字符。
        拆分时优先在换行符处断开，以保持消息的可读性。

        :param text: 需要拆分的原始文本。
        :param max_len: 每个片段的最大字符数，默认为 1900。
        :return: 拆分后的文本片段列表。
        """
        # 未超长则直接返回，避免不必要的处理
        if len(text) <= max_len:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_len:
                # 剩余文本已在限制内，直接作为最后一片
                chunks.append(text)
                break

            # 优先在 max_len 范围内的最后一个换行符处断开，保持语义完整
            split_at = text.rfind("\n", 0, max_len)
            if split_at == -1:
                # 找不到换行符时，强制在 max_len 处截断
                split_at = max_len

            chunks.append(text[:split_at])
            # 去除片段开头的多余换行符，避免空白行堆积
            text = text[split_at:].lstrip("\n")

        return chunks

