
# MiniClaw 🦞

> **~2,700 lines of Python** that implement the core architecture of [OpenClaw](https://github.com/openclaw/openclaw) (430K lines TypeScript). Built for understanding, not production.


[中文版 README](./README_zh.md) | [Architecture Deep-Dive (中文)](./docs/architecture-guide.md)

## What Is This?

MiniClaw distills OpenClaw's key architectural patterns into a minimal, runnable Python implementation. Instead of reading 430K lines of TypeScript, you can understand the same concepts in ~2,700 lines.

**Covers 11 core principles:**

1. **Hub-and-Spoke** — Gateway as the single coordination point
2. **Workspace Contract Files** — SOUL.md / IDENTITY.md / MEMORY.md injected into system prompt
3. **Agent Loop** — Brain → Hands → Brain tool-use cycle (max 10 rounds)
4. **Skills Triggers** — Keyword/regex matching → context injection
5. **Brain Abstraction** — Unified interface for Anthropic / OpenAI / Ali Bailian
6. **Context Management** — Compaction + safe tool_call/tool_result pair splitting
7. **Multi-Agent & Spawn** — Agent isolation + child delegation with depth limits
8. **Heartbeat** — Periodic autonomous check with `HEARTBEAT_OK` suppression
9. **Cron** — Precise scheduling (`HH:MM` daily / `*/N` minute intervals)
10. **Hooks (EventBus)** — Event-driven lifecycle automation (12 standard event types)
11. **Auto-Reflection** — Periodic self-summarization into MEMORY.md

## The Soul of OpenClaw: The Autonomy Triangle

OpenClaw's core innovation is making agents **act without human input**. This autonomy is built on three complementary mechanisms:

```
                  Autonomy
                     ▲
                    / \
                   /   \
             Heartbeat  Cron
         "patrol & judge"  "precise timing"
                   \   /
                    \ /
                     ▼
                   Hooks
              "event-driven"
```

MiniClaw implements all three.

## Quick Start

```bash
# Clone and install
git clone <this-repo>
cd miniclaw
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Initialize workspace
python -m miniclaw init

# Configure API key (via environment variable, never hardcode in config)
# Default provider: dashscope (Ali Bailian qwen-plus)
export DASHSCOPE_API_KEY=sk-xxx          # Ali Bailian / Coding Plan
# Or switch to other providers in config.yaml:
#   provider: anthropic    → export ANTHROPIC_API_KEY=sk-ant-xxx
#   provider: openai       → export OPENAI_API_KEY=sk-xxx
#   provider: dashscope-coding → export DASHSCOPE_API_KEY=sk-sp-xxx

# Run
python -m miniclaw chat                  # Interactive CLI
python -m miniclaw serve                 # Production mode (HTTP API + Heartbeat + Cron)
python -m miniclaw serve --discord-token $TOKEN  # Production + Discord
python -m miniclaw heartbeat             # Manual heartbeat trigger
python -m miniclaw status                # Show configuration
```

**CLI Commands:** `/skills` `/agents` `/heartbeat` `/compact` `/clear` `/quit`

**HTTP Endpoints (serve mode):**
- `GET /health` — Health check with uptime, request count, agent status
- `POST /input` — Send message: `{"text": "hello", "agent_id": "main"}`

## Project Structure

```
miniclaw/
├── gateway.py        # Central control plane (Hub-and-Spoke)
├── agents.py         # Agent lifecycle, spawn, auto-reflection
├── brain.py          # LLM abstraction (Anthropic/OpenAI/Bailian)
├── hands.py          # Tool execution (7 built-in + spawn + 2 cron tools + path safety)
├── memory.py         # Workspace contract files (SOUL/IDENTITY/MEMORY)
├── skills.py         # Skill loading + trigger matching
├── router.py         # Message routing + cross-agent dispatch
├── context.py        # Context assembly + compaction + message sanitization
├── hooks.py          # EventBus + 12 standard event types
├── heartbeat.py      # Periodic autonomous check
├── cron.py           # Scheduled task execution
├── config.py         # Configuration management (incl. cron jobs)
├── __main__.py       # CLI + serve entry point
└── channels/
    ├── base.py       # Channel interface
    ├── cli.py        # CLI channel (Rich formatted)
    └── discord.py    # Discord bot channel (with alert delivery)
tests/                        # Unit tests (179 tests, no LLM API needed)
├── test_config.py        # Config loading, provider resolution
├── test_memory.py        # Contract files, bootstrap assembly
├── test_skills.py        # Parsing, triggers, tools normalization, progressive disclosure index
├── test_context.py       # Context assembly, compaction, sanitization, skill index injection
├── test_brain.py         # Message format conversion, tool schema conversion
├── test_agents.py        # Agent lifecycle, spawn depth limits, mock LLM process_message
├── test_gateway.py       # Gateway coordination, session persistence, hooks, health endpoint
├── test_hands.py         # Tool execution, path traversal security
├── test_hooks.py         # EventBus, priority, error isolation
├── test_router.py        # Routing, cross-agent dispatch
├── test_cron.py          # Schedule matching, job management
├── test_heartbeat.py     # Active hours, midnight crossing
└── integration/          # Integration tests (require LLM API key)
    ├── test_basic_loop.py        # End-to-end agent loop verification
    ├── test_full_capabilities.py # All capabilities (tool use, memory, skills)
    ├── test_advanced_features.py # Heartbeat, multi-agent spawn, compaction
    ├── test_gateway_coordination.py  # Multi-channel, cron, session, routing
    └── test_hooks_e2e.py         # Hooks with real Gateway
docs/
└── architecture-guide.md  # Deep architecture explanation
```

## MiniClaw vs OpenClaw

| Aspect | MiniClaw | OpenClaw |
|--------|----------|----------|
| Code | ~2,700 lines Python | ~430,000 lines TypeScript |
| Gateway | HTTP serve + in-memory | WebSocket server |
| Providers | Anthropic + OpenAI + Bailian | 10+ providers |
| Channels | CLI + Discord + HTTP API | 50+ channels |
| Hooks | EventBus (12 event types) | Full event system |
| Autonomy | Heartbeat + Cron + Hooks | Same |
| Performance | Same order of magnitude | Same (bottleneck is LLM API) |

## Recommended Reading Order

1. `memory.py` → workspace contract files
2. `skills.py` → skill triggers
3. `hooks.py` → EventBus and event-driven design
4. `hands.py` → tool registration and execution
5. `brain.py` → LLM protocol differences
6. `agents.py` → agent loop, spawn, reflection
7. `context.py` → compaction and message sanitization
8. `gateway.py` → coordination, session recovery, health check
9. `heartbeat.py` → autonomous periodic check
10. `cron.py` → scheduled tasks

## Try It Locally

```bash
# 1. Set API key (never hardcode in config files)
export DASHSCOPE_API_KEY=sk-sp-xxx   # or sk-xxx for regular dashscope

# 2. Interactive chat — talk to the agent, try tool calls, test skills
python -m miniclaw chat

# 3. Production mode — starts HTTP API + Heartbeat + Cron scheduling
python -m miniclaw serve

# 4. Manual heartbeat trigger
python -m miniclaw heartbeat

# 5. Check configuration
python -m miniclaw status
```

Try these conversations in `chat` mode:

```
🐾 > hello                          # triggers greeting skill
🐾 > list all files in the workspace  # agent uses file_list tool
🐾 > read the SOUL.md file            # agent uses file_read tool
🐾 > remember: I prefer concise answers  # agent uses memory_append
🐾 > /skills                         # list loaded skills
🐾 > /heartbeat                      # manual heartbeat check
🐾 > /compact                        # trigger context compaction
```

## Running Tests

```bash
# Unit tests only (no LLM API needed, ~1.5s, 179 tests)
python -m pytest tests/ -v

# Integration tests (require DASHSCOPE_API_KEY set)
python -m pytest tests/integration/ -v -m integration

# Run specific integration suite
python -m pytest tests/integration/test_basic_loop.py -v -m integration

# Run everything (unit + integration)
python -m pytest tests/ -v -m ""
```

## License

MIT




## 核心架构图

```
用户输入 (CLI / Discord / HTTP)
    │
    ▼
┌──────────┐
│ Gateway  │ ← 中央控制平面，所有消息经过这里
└────┬─────┘
     │  路由 (Router)
     ▼
┌──────────┐     ┌──────────┐
│  Agent   │────▶│  Brain   │ ← 调用 LLM (Anthropic/OpenAI/百炼)
│  Loop    │◀────│          │
│          │     └──────────┘
│          │
│          │────▶┌──────────┐
│          │     │  Hands   │ ← 执行工具 (shell/file/http/spawn...)
│          │◀────│          │
└──────────┘     └──────────┘
     │
     │  上下文组装 (Context)
     │  ├── Memory (SOUL.md / IDENTITY.md / MEMORY.md)
     │  ├── Skills (触发匹配的技能 prompt)
     │  └── History (对话历史 + Compaction)
     │
     │  自主性三角
     ├── Heartbeat (周期巡视)
     ├── Cron (精确定时)
     └── Hooks/EventBus (事件驱动)
```


## 🎯 如果你要模仿开发，推荐的开发顺序

按照**从简单到复杂、从底层到顶层**的顺序，每一步都能跑起来验证：

### **Phase 1：让 Agent 能"说话"（最小可运行）**

| 步骤 | 做什么 | 对应模块 |
|------|--------|----------|
| **1** | **配置管理** — 定义 config 数据结构，加载 YAML 配置，解析 API Key | `config.py` |
| **2** | **LLM 抽象层** — 先只接一个 provider（如 OpenAI），实现 `think()` 方法，能发消息收回复 | `brain.py` |
| **3** | **最简 Agent** — 写一个 `process_message()` 方法，接收用户输入 → 调 Brain → 返回回复 | `agents.py`（简化版） |
| **4** | **CLI 入口** — 写一个 while 循环读取用户输入，调用 Agent，打印回复 | `__main__.py` |

> ✅ **里程碑 1**：能在终端和 LLM 对话了

### **Phase 2：让 Agent 有"记忆"和"人格"**

| 步骤 | 做什么 | 对应模块 |
|------|--------|----------|
| **5** | **Workspace 契约文件** — 实现 `SOUL.md`、`IDENTITY.md`、`MEMORY.md` 的读写和 bootstrap 组装 | `memory.py` |
| **6** | **上下文管理** — 将 bootstrap prompt + 对话历史组装成完整的 context window | `context.py`（基础版） |

> ✅ **里程碑 2**：Agent 有了"人格"，每次对话都带着 SOUL.md 的设定

### **Phase 3：让 Agent 能"动手"**

| 步骤 | 做什么 | 对应模块 |
|------|--------|----------|
| **7** | **工具执行引擎** — 实现 `file_read`、`file_write`、`shell_exec` 等内置工具 + 路径安全校验 | `hands.py` |
| **8** | **工具调用循环** — 在 Agent 中实现 `Brain → tool_call → Hands 执行 → 结果反馈 → Brain` 的循环 | `agents.py`（完整版） |

> ✅ **里程碑 3**：Agent 能调用工具了，可以读写文件、执行命令

### **Phase 4：让 Agent 更"聪明"**

| 步骤 | 做什么 | 对应模块 |
|------|--------|----------|
| **9** | **技能系统** — 实现 Skill 的 Markdown 定义、触发匹配、上下文注入 | `skills.py` |
| **10** | **消息路由** — 根据技能匹配决定消息路由 | `router.py` |
| **11** | **上下文 Compaction** — 实现对话历史压缩，处理 tool_call/tool_result 配对安全分割 | `context.py`（完整版） |
| **12** | **自动反思** — 每 N 轮对话自动提取知识写入 MEMORY.md | `agents.py` 中的 `_reflect()` |

> ✅ **里程碑 4**：Agent 能根据关键词触发不同技能，长对话不会爆上下文

### **Phase 5：让 Agent "自主行动"**

| 步骤 | 做什么 | 对应模块 |
|------|--------|----------|
| **13** | **事件总线** — 实现 EventBus，定义 12 种标准事件 | `hooks.py` |
| **14** | **Heartbeat** — 周期性自主检查 + `HEARTBEAT_OK` 静默协议 | `heartbeat.py` |
| **15** | **Cron 定时任务** — `HH:MM` 和 `*/N` 两种调度 | `cron.py` |

> ✅ **里程碑 5**：Agent 不需要人类输入也能自主行动了

### **Phase 6：让 Agent "协调多方"**

| 步骤 | 做什么 | 对应模块 |
|------|--------|----------|
| **16** | **Gateway 中央控制** — Hub-and-Spoke 架构，Session 持久化/恢复，健康检查 | `gateway.py` |
| **17** | **Multi-Agent Spawn** — 子 Agent 委派 + 深度限制 | `agents.py` 中的 `spawn()` |
| **18** | **多 Channel 支持** — Discord Bot、HTTP API | `channels/` |
| **19** | **多 Provider 适配** — 加上 Anthropic、百炼的适配 | `brain.py`（完整版） |

> ✅ **里程碑 6**：完整的 Agent 框架，多 Agent、多 Channel、多 Provider

---

### 💡 关键学习建议

- **每个 Phase 结束后都写单元测试**，这个项目有 179 个测试用例可以参考
- **先跑通再优化**，Phase 1-3 大约 500 行代码就能有一个能用的 Agent
- **重点理解三个设计模式**：Hub-and-Spoke（Gateway 中心化）、Workspace 契约文件（Markdown 定义行为）、自主性三角（Heartbeat + Cron + Hooks）
- 项目的 `docs/architecture-guide.md` 有非常详细的架构讲解，建议配合代码一起读



