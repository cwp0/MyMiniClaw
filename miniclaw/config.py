#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: config.py
# @Description: 配置管理，定义 config 数据结构，加载 YAML 配置，解析 API Key
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/11 15:33
# @Version: 1.0

"""
config.py Configuration management. Loads from ~/.miniclaw/config.yaml or defaults.
│
├── 常量定义
│   ├── DEFAULT_CONFIG_DIR / DEFAULT_WORKSPACE  — 默认路径
│   └── PROVIDER_DEFAULTS                       — 4 种 LLM provider 的默认配置
│
├── 4 个 dataclass 数据结构
│   ├── BrainConfig      — LLM 调用配置
│   ├── HeartbeatConfig   — 心跳检查配置
│   ├── CronJobConfig     — 定时任务配置
│   └── AgentDef          — 单个 Agent 的完整定义
│
└── Config 主类
    ├── load()            — 从 YAML 文件加载配置
    ├── _apply()          — 将原始 dict 映射到 dataclass
    ├── get_agent()       — 获取指定 Agent 定义
    ├── agent_workspace() — 解析 Agent 的 workspace 路径
    └── save_default()    — 生成默认配置文件
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_DIR = Path.home() / ".miniclaw"     # ~/.miniclaw/
DEFAULT_WORKSPACE = Path.cwd() / "workspace"       # 当前目录/workspace/

# LLM provider 的默认配置
PROVIDER_DEFAULTS = {
    "anthropic": {
        "env_var": "ANTHROPIC_API_KEY",
        "base_url": None,
        "model": "claude-sonnet-4-20250514",
    },
    "openai": {
        "env_var": "OPENAI_API_KEY",
        "base_url": None,
        "model": "gpt-4o",
    },
    "dashscope": {
        "env_var": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.5-plus",
    },
    # 阿里云百炼 Coding Plan
    "dashscope-coding": {
        "env_var": "DASHSCOPE_API_KEY",
        "base_url": "https://coding.dashscope.aliyuncs.com/v1", #  兼容 OpenAI 接口协议工具的专属URL
        "model": "qwen3.5-plus",
    },
}


@dataclass
class BrainConfig:
    provider: str = "dashscope"        # ① 用哪家 LLM
    model: str = "qwen3.5-plus"        # ② 用哪个模型
    api_key: str | None = None         # ③ API 密钥（通常不填，走环境变量）
    base_url: str | None = None        # ④ API 地址（OpenAI/Anthropic 不需要，百炼需要）
    max_tokens: int = 4096             # ⑤ 单次回复最大 token 数
    temperature: float = 0.7            # ⑥ 生成随机性（0=确定性，1=更随机）

    def resolve_api_key(self) -> str:
        # 第一优先级：显式配置的 api_key
        if self.api_key:
            return self.api_key

        # 第二优先级：从 PROVIDER_DEFAULTS 查找对应的环境变量名
        defaults = PROVIDER_DEFAULTS.get(self.provider, {})
        env_var = defaults.get("env_var", f"{self.provider.upper()}_API_KEY")
        #   anthropic → ANTHROPIC_API_KEY
        #   openai    → OPENAI_API_KEY
        #   dashscope → DASHSCOPE_API_KEY
        #   未知provider → {PROVIDER}_API_KEY（兜底）

        # 从环境变量读取
        key = os.environ.get(env_var, "")

        # 都没有 → 抛异常，明确告诉用户该怎么做
        if not key:
            raise ValueError(f"No API key: set {env_var} or config brain.api_key")
        return key

    def resolve_base_url(self) -> str | None:
        # 第一优先级：显式配置
        if self.base_url:
            return self.base_url

        # 第二优先级：从 PROVIDER_DEFAULTS 查默认值
        defaults = PROVIDER_DEFAULTS.get(self.provider, {})
        return defaults.get("base_url")
        #   anthropic → None（用 SDK 默认地址）
        #   openai    → None（用 SDK 默认地址）
        #   dashscope → "https://dashscope.aliyuncs.com/compatible-mode/v1"
        #   dashscope-coding → "https://coding.dashscope.aliyuncs.com/v1"

@dataclass
class HeartbeatConfig:
    enabled: bool = True
    interval_minutes: int = 30
    active_hours_start: str = "08:00"
    active_hours_end: str = "23:00"


@dataclass
class CronJobConfig:
    name: str = ""
    schedule: str = ""
    prompt: str = ""
    agent_id: str = "main"

@dataclass
class AgentDef:
    id: str = "main"
    workspace: str = ""
    brain: BrainConfig = field(default_factory=BrainConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    cron_jobs: list[CronJobConfig] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=lambda: ["*"])
    subagents_allow: list[str] = field(default_factory=lambda: ["*"])
    max_spawn_depth: int = 1

@dataclass
class Config:
    """MiniClaw 全局配置主类。

    负责管理整个应用的配置，包括：
    - 全局工作目录和配置目录路径
    - 多 Agent 的定义（每个 Agent 拥有独立的 brain/heartbeat/cron 配置）
    - 全局上下文长度限制

    典型使用方式：
        cfg = Config.load()                        # 从默认路径加载
        cfg = Config.load(Path("my_config.yaml"))  # 从指定路径加载
        agent = cfg.get_agent("main")              # 获取指定 Agent 配置
        ws = cfg.agent_workspace("main")           # 获取 Agent 工作目录

    YAML 配置文件结构示例：
        workspace: ~/my_workspace
        max_context_chars: 200000
        agents:
          main:
            brain:
              provider: dashscope
              model: qwen-plus
            heartbeat:
              enabled: true
              interval_minutes: 30
            cron:
              - name: daily_report
                schedule: "0 9 * * *"
                prompt: "生成今日报告"
    """

    # 配置文件所在目录，默认为 ~/.miniclaw/
    config_dir: Path = field(default_factory=lambda: DEFAULT_CONFIG_DIR)

    # 全局默认工作目录，Agent 未单独指定 workspace 时使用此路径
    workspace: Path = field(default_factory=lambda: DEFAULT_WORKSPACE)

    # 所有已定义的 Agent，key 为 agent_id（如 "main"）
    agents: dict[str, AgentDef] = field(default_factory=dict)

    # 单次对话最大上下文字符数，超出后会触发截断/压缩（0 表示不限制）
    max_context_chars: int = 0

    # 启动阶段（bootstrap）读取上下文的最大字符数，用于控制初始化时的内存占用
    bootstrap_max_chars: int = 0

    @classmethod
    def load(cls, config_path: Path | None = None) -> Config:
        """从 YAML 文件加载配置并返回 Config 实例。

        这是创建 Config 对象的推荐入口（工厂方法）。
        内部流程：
          1. 确定配置文件路径（优先使用传入的 config_path）
          2. 创建一个带默认值的 Config 实例
          3. 若配置文件存在，读取并通过 _apply() 覆盖默认值
          4. 返回最终的 Config 实例

        Args:
            config_path: 配置文件路径。若为 None，则使用默认路径
                         ``<DEFAULT_CONFIG_DIR>/config.yaml``，
                         即 ``~/.miniclaw/config.yaml``。

        Returns:
            加载并应用了配置文件内容的 Config 实例。
            若配置文件不存在，则返回全部字段为默认值的 Config 实例。
        """
        path = config_path or (DEFAULT_CONFIG_DIR / "config.yaml")
        cfg = cls()
        if path.exists():
            with open(path) as f:
                raw = yaml.safe_load(f) or {}
            cfg._apply(raw)
        return cfg

    def _apply(self, raw: dict[str, Any]) -> None:
        """将从 YAML 解析出的原始 dict 映射到当前 Config 实例的各字段。

        仅覆盖 YAML 中显式声明的字段，未出现的字段保留默认值。
        Agent 配置通过 ``agents`` 键按 agent_id 分组，每个 Agent 支持
        独立配置 brain / heartbeat / cron_jobs / allowed_tools 等。

        Args:
            raw: 由 ``yaml.safe_load`` 解析出的顶层配置字典。
                 支持的顶层键：
                   - workspace           (str)  全局工作目录路径
                   - max_context_chars   (int)  最大上下文字符数
                   - bootstrap_max_chars (int)  启动阶段最大上下文字符数
                   - agents              (dict) Agent 配置字典，key 为 agent_id
        """
        # 全局工作目录，支持 ~ 展开
        if "workspace" in raw:
            self.workspace = Path(raw["workspace"]).expanduser()

        # 上下文长度限制
        if "max_context_chars" in raw:
            self.max_context_chars = raw["max_context_chars"]
        if "bootstrap_max_chars" in raw:
            self.bootstrap_max_chars = raw["bootstrap_max_chars"]

        # 遍历所有 Agent 配置，逐一构建 AgentDef 对象
        for agent_id, agent_raw in raw.get("agents", {}).items():
            agent_def = AgentDef(id=agent_id)

            # Agent 独立工作目录（可选，未配置时由 agent_workspace() 推断）
            if "workspace" in agent_raw:
                agent_def.workspace = agent_raw["workspace"]

            # LLM 调用配置：provider / model / api_key / base_url 等
            if "brain" in agent_raw:
                b = agent_raw["brain"]
                provider = b.get("provider", "dashscope")
                # 从 PROVIDER_DEFAULTS 获取该 provider 的默认 model/base_url
                defaults = PROVIDER_DEFAULTS.get(provider, {})
                agent_def.brain = BrainConfig(
                    provider=provider,
                    model=b.get("model", defaults.get("model", "qwen-plus")),
                    api_key=b.get("api_key"),
                    base_url=b.get("base_url"),
                    max_tokens=b.get("max_tokens", 4096),
                    temperature=b.get("temperature", 0.7),
                )

            # 心跳检查配置：是否启用、检查间隔、活跃时间段
            if "heartbeat" in agent_raw:
                h = agent_raw["heartbeat"]
                agent_def.heartbeat = HeartbeatConfig(
                    enabled=h.get("enabled", True),
                    interval_minutes=h.get("interval_minutes", 30),
                    active_hours_start=h.get("active_hours_start", "08:00"),
                    active_hours_end=h.get("active_hours_end", "23:00"),
                )

            # 定时任务列表，每条 cron 对应一个 CronJobConfig
            for cj in agent_raw.get("cron") or []:
                agent_def.cron_jobs.append(CronJobConfig(
                    name=cj.get("name", ""),
                    schedule=cj.get("schedule", ""),
                    prompt=cj.get("prompt", ""),
                    agent_id=agent_id,
                ))

            # 工具白名单，["*"] 表示允许所有工具
            if "allowed_tools" in agent_raw:
                agent_def.allowed_tools = agent_raw["allowed_tools"]

            # 允许派生的子 Agent 白名单，["*"] 表示允许派生任意子 Agent
            if "subagents_allow" in agent_raw:
                agent_def.subagents_allow = agent_raw["subagents_allow"]

            # 子 Agent 最大递归派生深度，防止无限嵌套
            if "max_spawn_depth" in agent_raw:
                agent_def.max_spawn_depth = agent_raw["max_spawn_depth"]

            self.agents[agent_id] = agent_def

    def get_agent(self, agent_id: str = "main") -> AgentDef:
        """根据 agent_id 获取对应的 AgentDef 配置对象。

        Args:
            agent_id: Agent 的唯一标识符，默认为 ``"main"``。

        Returns:
            对应的 AgentDef 实例。

        Raises:
            ValueError: 若指定的 agent_id 在配置中不存在。
        """
        if agent_id not in self.agents:
            raise ValueError(f"Agent '{agent_id}' not defined in config")
        return self.agents[agent_id]

    def agent_workspace(self, agent_id: str = "main") -> Path:
        """解析并返回指定 Agent 的工作目录路径。

        工作目录的优先级规则：
          1. Agent 自身配置了 ``workspace`` → 直接使用（支持 ~ 展开）
          2. Agent 是 ``"main"`` 且未配置 workspace → 使用全局 ``self.workspace``
          3. 其他 Agent 未配置 workspace → 使用 ``<全局workspace父目录>/workspace-{agent_id}``

        Args:
            agent_id: Agent 的唯一标识符，默认为 ``"main"``。

        Returns:
            解析后的工作目录 Path 对象（已展开 ~）。

        Raises:
            ValueError: 若指定的 agent_id 在配置中不存在（由 get_agent 抛出）。
        """
        agent = self.get_agent(agent_id)

        # 优先级 1：Agent 自身显式配置了 workspace
        if agent.workspace:
            return Path(agent.workspace).expanduser()

        # 优先级 2：main agent 使用全局 workspace
        if agent_id == "main":
            return self.workspace

        # 优先级 3：其他 agent 在全局 workspace 同级目录下创建独立子目录
        return self.workspace.parent / f"workspace-{agent_id}"

    def save_default(self) -> Path:
        """在默认配置目录下生成一份最小化的默认配置文件。

        若配置文件已存在，则直接返回其路径，不会覆盖已有内容。
        若不存在，则创建 ``<config_dir>/config.yaml`` 并写入最小默认配置。

        生成的默认配置包含：
          - workspace：当前全局工作目录
          - agents.main.brain：使用 dashscope provider 和 qwen-plus 模型

        Returns:
            配置文件的 Path 对象（无论是已存在的还是新创建的）。
        """
        # 确保配置目录存在（~/.miniclaw/）
        self.config_dir.mkdir(parents=True, exist_ok=True)
        path = self.config_dir / "config.yaml"

        # 已存在则不覆盖，直接返回
        if path.exists():
            return path

        default = {
            "workspace": str(self.workspace),
            "agents": {
                "main": {
                    "brain": {
                        "provider": "dashscope",
                        "model": "qwen-plus",
                    }
                }
            },
        }
        with open(path, "w") as f:
            yaml.dump(default, f, default_flow_style=False)
        return path


def main() -> None:
    """测试配置读取是否正常工作。

    执行流程：
      1. 若 ~/.miniclaw/config.yaml 不存在，自动生成默认配置文件
      2. 加载配置并打印各字段值
      3. 尝试获取 main agent 的配置详情
    """
    print("=== MiniClaw 配置读取测试 ===\n")

    # 第一步：确保默认配置文件存在
    temp_cfg = Config()
    config_path = temp_cfg.save_default()
    print(f"配置文件路径: {config_path}")
    print(f"配置文件是否存在: {config_path.exists()}\n")

    # 第二步：从文件加载配置
    cfg = Config.load(config_path)
    print(f"config_dir:          {cfg.config_dir}")
    print(f"workspace:           {cfg.workspace}")
    print(f"max_context_chars:   {cfg.max_context_chars}")
    print(f"bootstrap_max_chars: {cfg.bootstrap_max_chars}")
    print(f"agents 列表:         {list(cfg.agents.keys())}\n")

    # 第三步：读取 main agent 详细配置
    if "main" in cfg.agents:
        agent = cfg.get_agent("main")
        print("--- main agent 配置 ---")
        print(f"  id:              {agent.id}")
        print(f"  workspace:       {agent.workspace or '(继承全局)'}")
        print(f"  brain.provider:  {agent.brain.provider}")
        print(f"  brain.model:     {agent.brain.model}")
        print(f"  brain.api_key (yaml):  {agent.brain.api_key or '(未设置)'}")
        try:
            resolved_key = agent.brain.resolve_api_key()
            print(f"  brain.api_key (resolved): {resolved_key[:8]}...{resolved_key[-4:]} ✅")
        except ValueError as error:
            print(f"  brain.api_key (resolved): ❌ {error}")
        print(f"  brain.max_tokens:{agent.brain.max_tokens}")
        print(f"  brain.temperature:{agent.brain.temperature}")
        print(f"  heartbeat.enabled:         {agent.heartbeat.enabled}")
        print(f"  heartbeat.interval_minutes:{agent.heartbeat.interval_minutes}")
        print(f"  allowed_tools:   {agent.allowed_tools}")
        print(f"  max_spawn_depth: {agent.max_spawn_depth}")
        print(f"  agent_workspace: {cfg.agent_workspace('main')}")
    else:
        print("⚠️  未找到 main agent 配置")

    print("\n✅ 配置读取测试完成！")


if __name__ == "__main__":
    main()