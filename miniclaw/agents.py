#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: agents.py
# @Description: 多智能体管理，负责处理用户请求，调用各种插件
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/13 14:57
# @Version: 1.0

"""Multi-agent management.

Implements agent isolation and spawn/delegation:
- Each agent has its own workspace, memory, context, and skill registry
- Agents can spawn child agents for delegation (like OpenClaw's sessions_spawn)
- Spawn depth is limited to prevent runaway recursion

AgentOrchestrator
  └── Agent (main)
        ├── Memory        → workspace/MEMORY.md, IDENTITY.md, SOUL.md
        ├── Brain         → LLM 调用
        ├── Hands         → 工具注册与执行（含 spawn_agent）
        ├── SkillRegistry → workspace/skills/*.md
        ├── Router        → 技能匹配
        ├── ContextManager→ 对话历史 & 上下文窗口
        └── Agent (child) → 子智能体（递归结构）

"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from miniclaw.brain import Brain, Message
from miniclaw.config import AgentDef, Config, BrainConfig

from miniclaw.context import ContextManager
from miniclaw.hands import Hands
from miniclaw.memory import Memory
from miniclaw.router import Router
from miniclaw.skills import SkillRegistry

# 模块级 logger，日志名与模块路径一致，便于按模块过滤和追踪日志
logger = logging.getLogger(__name__)


@dataclass
class SpawnResult:
    """子 Agent 派生任务的执行结果封装。"""

    run_id: str        # 本次派生任务的唯一追踪 ID（UUID 前 8 位）
    status: str        # 任务状态："accepted" | "completed" | "failed"
    result: str = ""   # 子 Agent 返回的结果文本，失败时为空字符串
    agent_id: str = "" # 执行本次任务的子 Agent ID


class Agent:
    """A single agent instance with its own isolated context."""

    def __init__(
            self,
            agent_def: AgentDef,
            workspace: Path,
            config: Config,
            spawn_depth: int = 0,
    ):
        """
        初始化 Agent 实例，构建完整的智能体运行环境。

        初始化流程：
        - 绑定基础配置（agent_def, config, spawn_depth）
        - 初始化核心组件：Memory（记忆）、Brain（大脑）、Hands（工具执行）
        - 加载技能目录并构建技能索引
        - 注册 spawn_agent 工具（如果未达到最大派生深度）

        :param agent_def: Agent 定义配置，包含 ID、大脑配置、权限等
        :param workspace: Agent 的工作目录，用于存储记忆和技能
        :param config: 全局配置对象
        :param spawn_depth: 当前派生深度，用于限制递归派生
        """
        # 从 agent_def 中提取 Agent 的唯一标识符
        self.id = agent_def.id
        # 保存全局配置，供后续获取子 Agent 定义和工作目录使用
        self.config = config
        # 保存 Agent 定义，包含权限、工具白名单、派生深度限制等
        self.agent_def = agent_def
        # 记录当前派生深度，防止无限递归派生子 Agent
        self.spawn_depth = spawn_depth

        # Memory：负责读写 MEMORY.md，提供跨会话的长期记忆能力
        self.memory = Memory(workspace)
        # Brain：封装 LLM 调用，负责推理和生成响应
        self.brain = Brain(agent_def.brain)
        # Hands：工具执行层，管理所有可调用工具的注册与执行
        self.hands = Hands(workspace, memory=self.memory)
        # SkillRegistry：技能注册表，存储从磁盘加载的技能定义
        self.skill_registry = SkillRegistry()
        # Router：根据用户输入匹配最合适的技能，决定路由目标
        self.router = Router(self.skill_registry)
        # ContextManager：管理对话历史窗口，控制上下文长度不超过 LLM 限制
        self.context = ContextManager(max_context_chars=config.max_context_chars)

        # 从 workspace/skills 目录加载所有技能文件（YAML/JSON 格式）
        self.skill_registry.load_from_directory(workspace / "skills")
        # 构建技能索引，用于在 system prompt 中向 LLM 展示可用技能列表
        self._skill_index = self.skill_registry.build_index()
        # 按需注册 spawn_agent 工具（仅在未达到最大派生深度时注册）
        self._register_spawn_tool()
        # 记录当前 Agent 已处理的对话轮次，用于触发周期性反思
        self._turn_count = 0
        # 每隔 N 轮触发一次自我反思，将重要信息沉淀到长期记忆
        self.reflection_interval = 5  # reflect every N turns

    def _register_spawn_tool(self) -> None:
        """
        注册 spawn_agent 工具，允许当前 Agent 派生子 Agent。

        注册条件：
        - 当前派生深度小于 max_spawn_depth 时才注册
        - 工具 handler 调用 self.spawn() 执行实际派生逻辑

        工具参数：
        - task: 子 Agent 的任务描述（必填）
        - agent_id: 目标 Agent ID（可选，默认使用当前 Agent ID）
        """
        # 已达到最大派生深度，禁止继续注册 spawn 工具，防止无限递归
        if self.spawn_depth >= self.agent_def.max_spawn_depth:
            return

        # 定义异步 handler，将 LLM 的工具调用参数转发给 self.spawn()
        async def spawn_handler(args: dict[str, Any]) -> str:
            # agent_id 为可选参数，未指定时默认派生与当前 Agent 相同类型的子 Agent
            return await self.spawn(
                task=args["task"],
                agent_id=args.get("agent_id", self.id),
            )

        # 向 Hands 注册 spawn_agent 工具，包含 handler 和 JSON Schema 描述
        self.hands.register_tool(
            "spawn_agent",
            spawn_handler,
            {
                "name": "spawn_agent",
                "description": (
                    "Spawn a child agent to handle a subtask. "
                    "The child runs independently and returns a result."
                ),
                # 工具参数的 JSON Schema，LLM 依据此 Schema 构造工具调用参数
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The task description for the child agent",
                        },
                        "agent_id": {
                            "type": "string",
                            "description": "Target agent ID (default: same as current)",
                        },
                    },
                    # task 为必填参数，agent_id 可选
                    "required": ["task"],
                },
            },
        )

    async def process_message(self, user_input: str) -> str:
        """
        处理用户消息，执行完整的 Agent 循环。

        Agent 循环流程（参考 OpenClaw）：
        1. Route: 匹配技能，确定目标 Agent
        2. Context assembly: 组装上下文（bootstrap + skills + history）
        3. Brain inference: 调用 LLM 进行推理
        4. Tool execution loop: 如果 LLM 请求工具，执行并反馈结果
           - 最多执行 max_tool_rounds 轮（默认 10 轮）
        5. 返回最终响应

        额外机制：
        - 每 reflection_interval 轮触发一次自我反思（_reflect）
        - 上下文接近限制时自动压缩（context.compact）

        :param user_input: 用户输入的消息内容
        :return: Agent 的最终响应文本
        """
        # Step 1: 路由匹配 —— 根据用户输入找到最匹配的技能，获取额外的 system prompt
        route_result = self.router.route(user_input, self.id)

        # 将用户消息追加到对话历史，供后续构建上下文窗口使用
        self.context.add_message(Message(role="user", content=user_input))

        # 判断是否为首轮对话，首轮时 bootstrap 会包含完整的初始化指令
        is_first = len(self.context.history) <= 1
        # 组装 bootstrap prompt（MEMORY.md 内容 + 系统初始化指令）
        bootstrap = self.memory.assemble_bootstrap(first_run=is_first)
        # Step 2: 构建上下文窗口 —— 将 bootstrap、技能 prompt、对话历史合并为 LLM 输入
        window = self.context.build(
            bootstrap_prompt=bootstrap,
            skill_prompt=route_result.extra_system_prompt,
            skill_index=self._skill_index,
        )

        # 获取当前 Agent 允许使用的工具白名单
        allowed_tools = self.agent_def.allowed_tools
        # 根据白名单过滤出对应工具的 JSON Schema，传给 LLM 以启用工具调用能力
        tool_schemas = self.hands.get_tool_schemas(allowed_tools)

        # Step 3: 首次 LLM 推理 —— 传入消息窗口和工具列表，获取初始响应
        response = await self.brain.think(
            messages=window.messages,
            system_prompt=window.system_prompt,
            # 无可用工具时传 None，避免 LLM 尝试调用不存在的工具
            tools=tool_schemas if tool_schemas else None,
        )

        # 工具调用轮次上限，防止 LLM 陷入无限工具调用循环
        max_tool_rounds = 10
        # 当前已执行的工具调用轮次计数
        round_count = 0

        # Step 4: 工具执行循环 —— 只要 LLM 仍在请求工具调用且未超出轮次限制，持续循环
        while response.tool_calls and round_count < max_tool_rounds:
            round_count += 1

            # 将 LLM 的 assistant 消息（含工具调用请求）记录到对话历史
            self.context.add_message(Message(
                role="assistant",
                content=response.text,
                tool_calls=response.tool_calls,
            ))

            # 遍历本轮所有工具调用请求，逐一执行并将结果写回上下文
            for tc in response.tool_calls:
                # 通过 Hands 执行工具，tc.name 为工具名，tc.arguments 为参数字典
                result = await self.hands.execute(tc.name, tc.arguments)
                # 将工具执行结果以 tool_result 角色追加到对话历史
                # tool_call_id 用于关联对应的工具调用请求
                self.context.add_message(Message(
                    role="tool_result",
                    content=result,
                    tool_call_id=tc.id,
                ))

            # 工具执行完毕后重新构建上下文窗口，将最新的工具结果纳入 LLM 输入
            window = self.context.build(
                bootstrap_prompt=bootstrap,
                skill_prompt=route_result.extra_system_prompt,
                skill_index=self._skill_index,
            )

            # 携带工具结果再次调用 LLM，让其基于工具输出继续推理或生成最终答案
            response = await self.brain.think(
                messages=window.messages,
                system_prompt=window.system_prompt,
                tools=tool_schemas,
            )

        # Step 5: 将 LLM 的最终 assistant 响应追加到对话历史，完成本轮对话记录
        self.context.add_message(Message(role="assistant", content=response.text))

        # 累加对话轮次计数，用于判断是否触发周期性反思
        self._turn_count += 1

        # 检查上下文是否接近字符上限，若是则触发压缩以释放空间
        if self.context.needs_compaction():
            logger.info("Context approaching limit, compacting...")
            # compact 会用 LLM 对历史对话进行摘要，替换掉旧的详细记录
            await self.context.compact(self.brain, bootstrap)

        # 每隔 reflection_interval 轮触发一次自我反思，将重要信息沉淀到长期记忆
        if self._turn_count % self.reflection_interval == 0:
            await self._reflect()

        return response.text

    async def _reflect(self) -> None:
        """
        周期性自我反思：将近期对话总结提取到 MEMORY.md。

        反思机制（自迭代记忆）：
        - 每 N 轮（reflection_interval）触发一次
        - 回顾最近 6 条对话记录
        - 提取可复用的知识、用户偏好或重要决策
        - 生成 1-3 条简洁的记忆点写入 Memory

        如果 LLM 返回 NOTHING_TO_REMEMBER，则跳过本次记录。
        """
        # 取最近 6 条对话记录作为反思素材，避免上下文过长
        recent = self.context.history[-6:]
        # 若历史为空则无需反思，直接返回
        if not recent:
            return

        # 将近期对话格式化为纯文本，每条消息截取前 300 字符防止 prompt 过长
        # 只保留 user 和 assistant 角色的消息，过滤掉 tool_result 等中间状态
        recent_text = "\n".join(
            f"[{m.role}] {m.content[:300]}" for m in recent
            if m.role in ("user", "assistant")
        )

        # 构造反思 prompt，引导 LLM 从对话中提炼值得长期记忆的关键信息
        reflection_prompt = (
            "Review this recent conversation and extract any important information "
            "worth remembering long-term. Focus on:\n"
            "- User preferences or habits\n"
            "- Key decisions made\n"
            "- Facts learned\n"
            "- Patterns noticed\n\n"
            "Write 1-3 concise bullet points. If nothing is worth remembering, "
            "reply NOTHING_TO_REMEMBER.\n\n"
            f"{recent_text}"
        )

        try:
            # 使用轻量级 system prompt 调用 LLM，专注于知识提炼而非对话生成
            response = await self.brain.think(
                messages=[Message(role="user", content=reflection_prompt)],
                system_prompt="You extract reusable knowledge from conversations. Be concise.",
            )

            # LLM 未返回 NOTHING_TO_REMEMBER，说明有值得记录的内容
            if "NOTHING_TO_REMEMBER" not in response.text:
                # 将反思结果以 [Reflection] 标签追加到 MEMORY.md，供后续对话复用
                self.memory.append_memory(f"[Reflection] {response.text.strip()}")
                logger.info(f"Reflection recorded: {response.text[:100]}")
            else:
                # LLM 判断本轮对话无值得记忆的内容，跳过写入
                logger.debug("Reflection: nothing to remember")
        except Exception as e:
            # 反思失败不应影响主流程，仅记录警告日志后继续
            logger.warning(f"Reflection failed: {e}")

    async def spawn(self, task: str, agent_id: str = "main") -> str:
        """
        派生子 Agent 处理子任务（类似 OpenClaw 的 sessions_spawn）。

        派生前置检查：
        - 当前派生深度不能超过 max_spawn_depth
        - 目标 agent_id 必须在 subagents_allow 列表中（或允许通配符 "*"）

        派生流程：
        1. 生成唯一的 run_id 用于追踪
        2. 从配置中获取子 Agent 定义和工作目录
        3. 创建新的 Agent 实例（spawn_depth + 1）
        4. 调用子 Agent 的 process_message 执行任务
        5. 返回包含 run_id 和结果的状态信息

        :param task: 子 Agent 的任务描述
        :param agent_id: 目标 Agent ID（默认 "main"）
        :return: 包含派生结果的状态字符串
        """
        # 前置检查：当前派生深度已达上限，拒绝继续派生以防止调用栈溢出
        if self.spawn_depth >= self.agent_def.max_spawn_depth:
            return f"Error: Max spawn depth ({self.agent_def.max_spawn_depth}) reached"

        # 前置检查：目标 agent_id 必须在允许列表中，"*" 表示允许派生任意 Agent
        allowed = self.agent_def.subagents_allow
        if "*" not in allowed and agent_id not in allowed:
            return f"Error: Not allowed to spawn agent '{agent_id}'"

        # 生成短 UUID 作为本次派生任务的唯一追踪 ID，便于日志关联
        run_id = str(uuid.uuid4())[:8]
        logger.info(f"Spawning child agent '{agent_id}' (run: {run_id}, depth: {self.spawn_depth + 1})")

        # 从全局配置中获取子 Agent 的定义（brain、权限、工具白名单等）
        child_def = self.config.get_agent(agent_id)
        # 获取子 Agent 的工作目录（独立于父 Agent，保证隔离性）
        child_workspace = self.config.agent_workspace(agent_id)

        # 创建子 Agent 实例，派生深度 +1 以追踪递归层级
        child = Agent(
            agent_def=child_def,
            workspace=child_workspace,
            config=self.config,
            spawn_depth=self.spawn_depth + 1,  # 递增派生深度，防止无限递归
        )

        # 调用子 Agent 处理任务，等待其完成并获取结果
        result = await child.process_message(task)

        # 返回格式化的结果字符串，包含 agent_id 和 run_id 便于父 Agent 追踪
        return f"[Agent {agent_id} completed (run: {run_id})]\n{result}"


class AgentOrchestrator:
    """
    Agent 编排器，管理多个 Agent 的生命周期。

    职责：
    - 按需创建和缓存 Agent 实例（get_or_create_agent）
    - 维护 Agent ID 到实例的映射关系
    - 提供列出所有可用 Agent 的方法
    """

    def __init__(self, config: Config):
        """
        初始化编排器。

        :param config: 全局配置对象，用于获取 Agent 定义和工作目录
        """
        # 保存全局配置，供创建 Agent 实例时使用
        self.config = config
        # Agent 实例缓存，key 为 agent_id，避免重复创建同一 Agent
        self._agents: dict[str, Agent] = {}

    def get_or_create_agent(self, agent_id: str = "main") -> Agent:
        """
        获取或创建指定 ID 的 Agent 实例。

        如果该 ID 的 Agent 尚未创建，则：
        1. 从配置中获取 Agent 定义
        2. 解析对应的工作目录
        3. 创建新的 Agent 实例并缓存

        :param agent_id: Agent 的唯一标识符（默认 "main"）
        :return: Agent 实例
        """
        # 缓存命中时直接返回已有实例，保证同一 agent_id 的对话状态连续性
        if agent_id not in self._agents:
            # 从配置中读取该 agent_id 对应的 AgentDef（brain、权限等）
            agent_def = self.config.get_agent(agent_id)
            # 解析该 Agent 的工作目录路径（存放 skills、memory 等文件）
            workspace = self.config.agent_workspace(agent_id)
            # 创建新的 Agent 实例，spawn_depth 默认为 0（顶层 Agent）
            agent = Agent(
                agent_def=agent_def,
                workspace=workspace,
                config=self.config,
            )
            # 将新实例写入缓存，后续同 agent_id 的请求直接复用
            self._agents[agent_id] = agent
        return self._agents[agent_id]

    def list_agents(self) -> list[str]:
        """
        列出配置中定义的所有 Agent ID。

        :return: Agent ID 列表
        """
        # 直接从配置的 agents 字典中提取所有已定义的 Agent ID
        return list(self.config.agents.keys())


async def main():
    """
    Agent 交互式测试入口。

    测试流程：
      1. 创建 Agent 实例（注意：当前实现缺少必要的构造参数）
      2. 进入交互循环，读取用户输入
      3. 调用 agent.process_message 处理消息并打印响应
      4. 支持 'quit' / 'exit' 或 Ctrl+C 退出

    注意：当前 main() 中的 Agent() 构造不完整，实际运行需要
    提供 agent_def, workspace, config 等必要参数。
    """
    # 注意：此处 Agent() 构造参数不完整，仅作为交互测试示例框架
    # 实际使用时需传入 agent_def、workspace、config 等必要参数
    agent = Agent()

    print("=== MiniClaw Agent 交互 ===")
    print("输入 'quit' 或 'exit' 退出\n")

    while True:
        try:
            # 读取用户输入并去除首尾空白字符
            user_input = input("用户: ").strip()
            # 检测退出指令，支持 'quit' 和 'exit' 两种写法（大小写不敏感）
            if user_input.lower() in ['quit', 'exit']:
                print("再见！")
                break

            # 跳过空输入，避免将空字符串传入 Agent 处理
            if not user_input:
                continue

            # 调用 Agent 处理用户消息，等待异步响应
            response = await agent.process_message(user_input)
            print(f"助手: {response}\n")

        except KeyboardInterrupt:
            # 用户按下 Ctrl+C 时优雅退出，避免抛出异常堆栈
            print("\n再见！")
            break
        except Exception as e:
            # 捕获其他异常并打印错误信息，保持交互循环不中断
            print(f"错误: {e}\n")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
