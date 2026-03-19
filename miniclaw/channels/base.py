#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: base.py
# @Description: Channel 基类
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/19 14:43
# @Version: 1.0

"""Channel base class — the I/O abstraction for external platforms."""

from __future__ import annotations

from abc import ABC, abstractmethod

from miniclaw.gateway import Gateway


class Channel(ABC):
    """
    所有输入/输出渠道的抽象基类。

    每种接入渠道（CLI、Discord 等）都需要继承此类并实现
    start / stop / send 三个核心方法，从而与 Gateway 解耦，
    使框架可以无缝切换或同时运行多个渠道。
    """

    def __init__(self, gateway: Gateway, agent_id: str = "main"):
        """
        初始化渠道，绑定 Gateway 实例和目标 Agent。

        :param gateway: 负责消息路由和 Agent 编排的网关对象。
        :param agent_id: 本渠道默认对话的 Agent 标识，默认为 "main"。
        """
        # 持有 Gateway 引用，所有消息的收发都通过它完成
        self.gateway = gateway
        # 标识本渠道当前服务的 Agent，支持多 Agent 场景下的路由
        self.agent_id = agent_id

    @abstractmethod
    async def start(self) -> None:
        """
        启动渠道，开始监听并接收来自外部平台的消息。

        子类应在此方法中完成事件循环的绑定、连接的建立等初始化工作，
        并持续运行直到收到停止信号。

        :return: None
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """
        停止渠道，释放相关资源并退出监听循环。

        子类应在此方法中关闭连接、清理状态，确保优雅退出。

        :return: None
        """
        ...

    @abstractmethod
    async def send(self, message: str) -> None:
        """
        通过当前渠道向外部平台发送一条消息。

        :param message: 要发送的文本内容。
        :return: None
        """
        ...

