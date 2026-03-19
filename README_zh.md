# MiniClaw 🦞

> **~2,700 行 Python** 实现 [OpenClaw](https://github.com/openclaw/openclaw)（43 万行 TypeScript）的核心架构。为理解原理而建，非生产级别。

[English README](./README.md) | [架构原理深度讲解](./docs/architecture-guide.md)

## 这是什么？

MiniClaw 把 OpenClaw 的关键架构模式提炼为一个可运行的 Python 最小实现。不需要读 43 万行 TypeScript，用 ~2,700 行 Python 理解同样的概念。

**覆盖 11 个核心原理：**

1. **Hub-and-Spoke** — Gateway 作为唯一的协调中心
2. **Workspace 契约文件** — SOUL.md / IDENTITY.md / MEMORY.md 注入 system prompt
3. **Agent Loop** — Brain → Hands → Brain 工具循环（最多 10 轮）
4. **Skills 触发** — 关键词/正则匹配 → 上下文注入
5. **Brain 抽象层** — Anthropic / OpenAI / 阿里百炼统一接口
6. **上下文管理** — Compaction + tool_call/tool_result 配对安全分割
7. **Multi-Agent & Spawn** — Agent 隔离 + 子 Agent 委派 + 深度限制
8. **Heartbeat** — 周期性自主检查 + `HEARTBEAT_OK` 静默协议
9. **Cron** — 精确定时调度（`HH:MM` 每日 / `*/N` 分钟间隔）
10. **Hooks (EventBus)** — 事件驱动的生命周期自动化（12 种标准事件）
11. **自动反思** — 定期从对话中提取知识写入 MEMORY.md

## OpenClaw 的灵魂：自主性三角

OpenClaw 的核心创新是让 Agent **不依赖人类输入就能做事**，这种自主性由三个互补的机制构成：

```
                  自主性 (Autonomy)
                        ▲
                       / \
                      /   \
                Heartbeat  Cron
            "巡视判断"    "精确定时"
                      \   /
                       \ /
                        ▼
                      Hooks
                  "事件驱动"
```

MiniClaw 完整实现了三者。

## 快速上手

```bash
# 克隆并安装
git clone <this-repo>
cd miniclaw
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 初始化工作区
python -m miniclaw init

# 配置 API Key（通过环境变量，不要硬编码到 config 文件中）
# 默认 provider: dashscope（百炼 qwen-plus）
export DASHSCOPE_API_KEY=sk-xxx          # 百炼 / Coding Plan
# 也可以在 config.yaml 中切换其他 provider:
#   provider: anthropic    → export ANTHROPIC_API_KEY=sk-ant-xxx
#   provider: openai       → export OPENAI_API_KEY=sk-xxx
#   provider: dashscope-coding → export DASHSCOPE_API_KEY=sk-sp-xxx

# 运行
python -m miniclaw chat                  # 交互式 CLI
python -m miniclaw serve                 # 生产模式（HTTP API + Heartbeat + Cron）
python -m miniclaw serve --discord-token $TOKEN  # 生产模式 + Discord
python -m miniclaw heartbeat             # 手动触发 heartbeat
python -m miniclaw status                # 查看配置
```

**CLI 命令：** `/skills` `/agents` `/heartbeat` `/compact` `/clear` `/quit`

**HTTP 端点（serve 模式）：**
- `GET /health` — 健康检查（uptime、请求数、Agent 状态）
- `POST /input` — 发送消息：`{"text": "你好", "agent_id": "main"}`

## 项目结构

```
miniclaw/
├── gateway.py        # 中央控制平面 (Hub-and-Spoke)
├── agents.py         # Agent 生命周期、spawn、自动反思
├── brain.py          # LLM 抽象层 (Anthropic/OpenAI/百炼)
├── hands.py          # 工具执行 (7 个内置 + spawn + 2 个 Cron 工具 + 路径安全)
├── memory.py         # Workspace 契约文件 (SOUL/IDENTITY/MEMORY)
├── skills.py         # Skill 加载 + 触发匹配
├── router.py         # 消息路由 + 跨 Agent 分发
├── context.py        # 上下文组装 + Compaction + 消息清洗
├── hooks.py          # EventBus + 12 种标准事件
├── heartbeat.py      # 周期性自主检查
├── cron.py           # 定时任务调度
├── config.py         # 配置管理（含 Cron 声明）
├── __main__.py       # CLI + serve 入口
└── channels/
    ├── base.py       # Channel 接口
    ├── cli.py        # CLI 频道 (Rich 格式化)
    └── discord.py    # Discord Bot 频道（含告警投递）
tests/                        # 单元测试（179 个，无需 LLM API）
├── test_config.py        # 配置加载、provider 解析
├── test_memory.py        # 契约文件、bootstrap 组装
├── test_skills.py        # 解析、触发、tools 规范化、渐进式披露索引
├── test_context.py       # 上下文组装、压缩、消息清洗、Skill 索引注入
├── test_brain.py         # 消息格式转换、工具 schema 转换
├── test_agents.py        # Agent 生命周期、spawn 深度限制、mock LLM 处理
├── test_gateway.py       # Gateway 协调、Session 持久化、Hooks、健康检查
├── test_hands.py         # 工具执行、路径遍历安全
├── test_hooks.py         # EventBus、优先级、错误隔离
├── test_router.py        # 路由、跨 Agent 分发
├── test_cron.py          # 调度匹配、job 管理
├── test_heartbeat.py     # 活跃时段、跨午夜
└── integration/          # 集成测试（需要 LLM API Key）
    ├── test_basic_loop.py        # 端到端 Agent 循环
    ├── test_full_capabilities.py # 全功能（工具、记忆、Skills）
    ├── test_advanced_features.py # Heartbeat、多 Agent Spawn、Compaction
    ├── test_gateway_coordination.py  # 多 Channel、Cron、Session、路由
    └── test_hooks_e2e.py         # 真实 Gateway 下的 Hooks
docs/
└── architecture-guide.md  # 架构原理深度讲解
```

## MiniClaw vs OpenClaw

| 维度 | MiniClaw | OpenClaw |
|------|----------|----------|
| 代码量 | ~2,700 行 Python | ~43 万行 TypeScript |
| Gateway | HTTP serve + 内存协调 | WebSocket 服务器 |
| LLM 支持 | Anthropic + OpenAI + 百炼 | 10+ provider |
| Channel | CLI + Discord + HTTP API | 50+ 渠道 |
| Hooks | EventBus（12 种事件） | 完整事件系统 |
| 自主性 | Heartbeat + Cron + Hooks | 同上 |
| 性能 | 同一数量级 | 同上（瓶颈在 LLM API） |

## 推荐阅读顺序

1. `memory.py` → workspace 契约文件
2. `skills.py` → Skill 触发匹配
3. `hooks.py` → EventBus 和事件驱动设计
4. `hands.py` → 工具注册和执行
5. `brain.py` → LLM 调用协议差异
6. `agents.py` → Agent Loop、Spawn、反思
7. `context.py` → Compaction 和消息清洗
8. `gateway.py` → 协调、Session 恢复、健康检查
9. `heartbeat.py` → 自主性周期检查
10. `cron.py` → 定时任务

## 本地体验

```bash
# 1. 设置 API Key（通过环境变量，不要写到配置文件里）
export DASHSCOPE_API_KEY=sk-sp-xxx   # 或 sk-xxx（普通百炼）

# 2. 交互式聊天 — 和 Agent 对话，测试工具调用和 Skills
python -m miniclaw chat

# 3. 生产模式 — 启动 HTTP API + Heartbeat + Cron 调度
python -m miniclaw serve

# 4. 手动触发 Heartbeat
python -m miniclaw heartbeat

# 5. 查看当前配置
python -m miniclaw status
```

在 `chat` 模式下试试这些对话：

```
🐾 > hello                          # 触发 greeting skill
🐾 > 列出工作区里的所有文件          # Agent 调用 file_list 工具
🐾 > 读一下 SOUL.md 文件             # Agent 调用 file_read 工具
🐾 > 记住：我喜欢简洁的回答          # Agent 调用 memory_append
🐾 > /skills                         # 列出已加载的 Skills
🐾 > /heartbeat                      # 手动 Heartbeat 检查
🐾 > /compact                        # 触发上下文压缩
```

## 运行测试

```bash
# 单元测试（无需 LLM API，~1.5 秒，179 个测试）
python -m pytest tests/ -v

# 集成测试（需要设置 DASHSCOPE_API_KEY）
python -m pytest tests/integration/ -v -m integration

# 运行特定集成测试
python -m pytest tests/integration/test_basic_loop.py -v -m integration

# 运行全部（单元 + 集成）
python -m pytest tests/ -v -m ""
```

## 协议

MIT
