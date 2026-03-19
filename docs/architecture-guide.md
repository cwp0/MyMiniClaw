# 用 2700 行 Python 拆解 OpenClaw 的核心秘密

> 为什么社区都说 OpenClaw 的灵魂是 Cron？我把 43 万行 TypeScript 缩写成 2700 行 Python，终于搞明白了。


项目地址: https://code.alibaba-inc.com/obert/MyMiniClaw
参考: https://code.alibaba-inc.com/obert/MiniClaw

## TL;DR

OpenClaw 是 GitHub 上 30 万 Stars 的 AI Agent 框架，43 万行 TypeScript。MiniClaw 用 Python 写了一个最小可运行复刻，把核心架构浓缩到 16 个模块、约 2700 行代码。这篇文章不是教程，是对 OpenClaw 几个「反常识」设计决策的拆解，以及这些决策背后的工程权衡。

## 为什么要自己写一个

最近在玩 OpenClaw，越玩越上头——给它配好 Heartbeat 和 Cron 之后，Agent 真的会在你不说话的时候自己做事，体验和普通 chatbot 完全不同。但要理解它为什么能做到这些，直接读 43 万行 TypeScript 源码根本看不清楚全貌，看几个文件就迷路了。不如自己动手写一个最小实现——哪些设计是核心的、哪些是工程膨胀，写一遍就全清楚了。

限定条件：
- **Python**（降低理解门槛，方便快速验证想法）
- **可以跑**（不是纸面架构，得真能聊天、真能用工具、真能自主巡检）
- **只保留核心架构模式**（去掉 50+ Channel 适配、10+ LLM provider 等工程量）

最终成果：11 个核心原理，16 个模块，~2700 行 Python，179 个单元测试 + 22 个集成测试全部通过。

## 核心论点：自主性才是 Agent 的分水岭

市面上大量 Agent 框架的架构可以概括为：用户输入 → LLM 推理 → 工具调用 → 返回结果。这是一个**请求-响应模型**——本质上和 Web 服务器没有区别，只是把 HTTP handler 换成了 LLM。

OpenClaw 区别于这些框架的关键不在于它支持多少个 Channel 或 LLM provider，而在于一个架构层面的决策：**Agent 应该能在没有用户输入的情况下自主执行任务**。这意味着框架需要内置调度器、事件总线和生命周期管理——这些在请求-响应模型中完全不需要的基础设施。

## OpenClaw 的灵魂：自主性三角

前面提到 OpenClaw 的核心在于自主性。具体来说，这种自主性由三个互补的机制构成：

```
                    自主性 (Autonomy)
                        ▲
                       / \
                      /   \
                     /     \
          ┌─────────┘       └──────────┐
          │                            │
     Heartbeat                       Cron
   "定期巡视，有事才报"          "到点干活，精确调度"
   (每30分钟判断一次)           (每天9点/每周一)
          │                            │
          └─────────┐       ┌──────────┘
                     \     /
                      \   /
                       \ /
                        ▼
                      Hooks
                 "事件驱动，即时响应"
               (session重置→重新加载)
```

- **Heartbeat** = 周期性觉察。Agent 每 N 分钟醒来，检查一切，有事才报，没事静默（`HEARTBEAT_OK`）。一个 Heartbeat 替代多个小型轮询任务。
- **Cron** = 精确定时。"每天 9 点生成报告"、"每周一做代码审查"。支持隔离 session（不污染主对话）和 model 覆盖（重型任务用更强的模型）。
- **Hooks** = 事件驱动。Agent 生命周期事件（session 重置、新用户连接等）触发预定义行为。

这三者组合起来，Agent 就从"聊天工具"变成了"安静地替你盯着一切的同事"。社区说 OpenClaw 的灵魂是 Cron/Heartbeat，就是这个意思——没有这些自主性机制，Agent 只是一个更花哨的命令行。

MiniClaw 完整实现了自主性三角：Heartbeat（`heartbeat.py`）、Cron（`cron.py`）和 Hooks（`hooks.py` — 基于 EventBus 的 12 种标准事件类型）。

## 架构全景

```
用户输入
   │
   ▼
┌──────────────────────────────────────────────────────────┐
│  Gateway（中央控制平面）                                    │
│                                                          │
│  ┌─────────┐    ┌────────┐    ┌───────┐    ┌──────────┐ │
│  │ Channel  │───▶│ Router │───▶│ Agent │───▶│ Delivery │ │
│  │ (CLI)    │    │        │    │       │    │          │ │
│  └─────────┘    └───┬────┘    └──┬────┘    └──────────┘ │
│                     │            │                       │
│               ┌─────▼────┐   ┌──▼───────────────┐      │
│               │ Skills    │   │ Agent Loop:      │      │
│               │ Registry  │   │  Brain → Hands   │      │
│               └──────────┘   │  → Brain → ...   │      │
│                              └──┬───────────────┘      │
│                                 │                       │
│                    ┌────────────┼────────────┐          │
│                    │            │            │          │
│               ┌────▼───┐  ┌───▼────┐  ┌───▼──────┐   │
│               │ Memory │  │ Context│  │ Heartbeat│   │
│               │(SOUL.md│  │Manager │  │(定时检查) │   │
│               │ etc.)  │  │        │  │          │   │
│               └────────┘  └────────┘  └──────────┘   │
└──────────────────────────────────────────────────────────┘
```

## 核心原理 1: Hub-and-Spoke 架构

OpenClaw 最重要的架构决策是 **Gateway 作为唯一的控制中心**。所有消息、所有 Agent、所有外部 Channel 都通过 Gateway 协调。

MiniClaw 的 `gateway.py` 实现了这个模式：

```python
class Gateway:
    def __init__(self, config):
        self.orchestrator = AgentOrchestrator(config)  # 管理所有 Agent
        self._heartbeats = {}                           # 管理所有 Heartbeat
        self._message_handlers = []                     # 管理所有 Channel 回调

    async def handle_input(self, text, agent_id="main"):
        agent = self.orchestrator.get_or_create_agent(agent_id)
        route = agent.router.route(text, agent_id)      # 路由决策

        if route.target_agent != agent_id:
            # 消息应该由另一个 Agent 处理
            target = self.orchestrator.get_or_create_agent(route.target_agent)
            response = await target.process_message(text)
        else:
            response = await agent.process_message(text)

        await self._deliver(agent_id, response)          # 分发到 Channel
        return response
```

**为什么这样设计？**

把协调逻辑集中在 Gateway 有几个好处：Agent 之间不需要互相感知对方的存在，Channel 不需要知道消息会被哪个 Agent 处理，新增 Agent 或 Channel 不需要改已有代码。这就是 hub-and-spoke 的价值——降低耦合。

OpenClaw 的 Gateway 是一个 WebSocket 服务器，可以同时服务 CLI、Discord、Web 多个 Channel。MiniClaw 简化为直接函数调用，但保留了同样的协调模式。

**Gateway 的 5 个核心职责**（全部验证通过）：

```
1. 多 Channel 广播: 注册多个 handler → 每条响应同时发送给所有 Channel
   实测: Channel A 和 Channel B 同时收到同一条消息 ✓

2. 跨 Agent 路由: 根据消息内容将请求路由到不同 Agent
   实测: "hello" → main agent, "√144" → math agent (返回 12) ✓

3. Session 隔离: 每个 Agent 有独立的 session 文件 (JSONL)
   实测: main 有 8 条消息, math 只有 2 条 ✓

4. Heartbeat 调度: 启动时为每个配置了 heartbeat 的 Agent 创建定时器
   实测: main 有 heartbeat, math 没有 ✓

5. Cron 调度: 支持注册和执行定时任务
   实测: "status-check" cron job 成功调用 file_list ✓
```

## 核心原理 2: Workspace 契约文件

OpenClaw 有一个独特的设计：Agent 的人格、身份、记忆不是硬编码在配置里，而是放在 workspace 目录下的 Markdown 文件中。

```
workspace/
├── SOUL.md        ← 人格和规则（"你是谁、怎么做事"）
├── IDENTITY.md    ← 身份信息（名字、角色）
├── MEMORY.md      ← 持久记忆（append-only 追加日志）
├── HEARTBEAT.md   ← 定时检查指令
└── skills/        ← Skill 定义
```

这些文件在每次 LLM 调用前被**注入到 system prompt** 中。`memory.py` 负责这件事：

```python
BOOTSTRAP_FILES = [
    "BOOTSTRAP.md",   # 首次运行指令（仅第一次）
    "HEARTBEAT.md",   # 定时检查
    "USER.md",        # 用户偏好
    "IDENTITY.md",    # 身份
    "TOOLS.md",       # 工具使用提示
    "SOUL.md",        # 人格规则
]

class Memory:
    def assemble_bootstrap(self, first_run=False):
        parts = []
        for filename in BOOTSTRAP_FILES:
            if filename == "BOOTSTRAP.md" and not first_run:
                continue
            content = self.read_file(filename)
            if content:
                parts.append(f"## [{filename}]\n\n{content}")
        # MEMORY.md 单独追加
        memory_content = self.read_file("MEMORY.md")
        if memory_content:
            parts.append(f"## [MEMORY.md]\n\n{memory_content}")
        return "\n\n---\n\n".join(parts)
```

**这个设计有几个工程上的好处：**

1. **可编辑性**：不需要改代码就能改变 Agent 的行为，直接编辑 Markdown 文件即可
2. **持久记忆**：MEMORY.md 是 append-only 的，Agent 自己可以通过 `memory_append` 工具往里写入学到的东西
3. **多 Agent 隔离**：每个 Agent 有独立的 workspace 目录，人格和记忆天然隔离
4. **注入顺序固定**：OpenClaw 规定了注入顺序（BOOTSTRAP → HEARTBEAT → USER → IDENTITY → TOOLS → SOUL），保证 SOUL.md 里的规则在最后，优先级最高（LLM 对最后出现的指令权重更高）

## 核心原理 3: Agent Loop（工具循环）

Agent 的核心执行逻辑不是"问一次 LLM 拿回答"，而是一个**循环**：LLM 可以选择调用工具，执行完工具后把结果喂回去，LLM 再决定下一步，直到它决定不再调用工具为止。

这在 `agents.py` 的 `process_message` 中实现：

```python
async def process_message(self, user_input):
    # 1. 路由：匹配 Skills，确定目标 Agent
    route_result = self.router.route(user_input, self.id)

    # 2. 上下文组装
    self.context.add_message(Message(role="user", content=user_input))
    bootstrap = self.memory.assemble_bootstrap(first_run=is_first)
    window = self.context.build(
        bootstrap_prompt=bootstrap,
        skill_prompt=route_result.extra_system_prompt,
    )

    # 3. 首次 Brain 推理
    response = await self.brain.think(
        messages=window.messages,
        system_prompt=window.system_prompt,
        tools=tool_schemas,
    )

    # 4. 工具循环（最多 10 轮）
    while response.tool_calls and round_count < 10:
        # 执行每个工具调用
        for tc in response.tool_calls:
            result = await self.hands.execute(tc.name, tc.arguments)
            self.context.add_message(Message(
                role="tool_result", content=result, tool_call_id=tc.id,
            ))
        # 把结果喂回 LLM，让它决定下一步
        response = await self.brain.think(messages=..., tools=...)

    # 5. 返回最终文本回复
    return response.text
```

**为什么限制 10 轮？** 防止 Agent 陷入无限循环。OpenClaw 也有类似的保护机制（`runTimeoutSeconds`）。

**这个循环是 Agent 和 Chatbot 的本质区别**：Chatbot 只是问答（一次 LLM 调用），Agent 能自主使用工具完成任务（多轮 LLM + 工具调用）。

## 核心原理 4: Skills 触发系统

OpenClaw 的 Skill 不是"调用一个 API"，而是**声明式的**：定义好触发条件（关键词或正则），当用户消息匹配时自动注入对应的上下文。

MiniClaw 用 Markdown + YAML front-matter 实现：

```markdown
---
name: code-review
description: Reviews code files for quality issues
triggers:
  - type: keyword
    pattern: "review"
  - type: regex
    pattern: "review\\s+(this|the|my)\\s+(code|file)"
tools:
  - file_read
  - shell_exec
---

When asked to review code:
1. Use file_read to read the specified file
2. Analyze for bugs, style issues, missing error handling
3. Provide specific, actionable feedback
```

`skills.py` 的触发匹配逻辑很直接：

```python
class Trigger:
    def matches(self, text):
        if self.type == "always":
            return True
        if self.type == "keyword":
            return self.pattern.lower() in text.lower()
        if self.type == "regex":
            return bool(re.search(self.pattern, text, re.IGNORECASE))
```

MiniClaw 对 Skill 采用**渐进式披露**——和 OpenClaw 一样的设计：

- **始终可见**：所有 Skill 的 name + description + triggers 组成一个紧凑索引，每次都在 system prompt 中，让 LLM 知道有哪些能力可用
- **触发时加载**：只有匹配到 trigger 的 Skill，其完整 body 才会注入到 system prompt

```python
class SkillRegistry:
    def build_index(self):
        """生成始终可见的 Skill 索引（~100 tokens/skill）"""
        lines = ["## Available Skills (loaded on demand)"]
        for s in self._skills:
            triggers = ", ".join(t.pattern for t in s.triggers if t.type != "always")
            lines.append(f"- **{s.name}**: {s.description} (triggers: {triggers})")
        return "\n".join(lines)

class ContextManager:
    def build(self, bootstrap_prompt, skill_prompt="", skill_index=""):
        system_parts = [bootstrap_prompt]
        if skill_index:           # 始终可见的索引
            system_parts.append(skill_index)
        if skill_prompt:          # 仅匹配时注入的 body
            system_parts.append(skill_prompt)
        ...
```

**为什么这样设计**：如果 20 个 Skill 的 body 全量注入 system prompt，上下文一开局就消耗数千 token。渐进式披露让简单问答只付出索引的代价（几百 token），复杂任务匹配后才加载完整方法论。

## 核心原理 5: Brain 抽象层

`brain.py` 把 Anthropic 和 OpenAI 两种 API 统一成一个接口。表面上看只是适配器模式，但有一个容易忽略的细节——**工具调用的协议不同**。

Anthropic 的工具调用结果需要用 `tool_result` 类型嵌套在 `user` 角色的消息里：

```python
# Anthropic 格式
{"role": "user", "content": [{
    "type": "tool_result",
    "tool_use_id": "toolu_xxx",
    "content": "文件内容..."
}]}
```

OpenAI 则用独立的 `tool` 角色：

```python
# OpenAI 格式
{"role": "tool", "tool_call_id": "call_xxx", "content": "文件内容..."}
```

`Brain` 类隐藏了这些差异，上层代码只需要操作统一的 `Message` 和 `ToolCall` 数据结构。

## 核心原理 6: 上下文管理与 Compaction

LLM 的上下文窗口是有限的。对话越长，旧消息占的空间越多，留给新内容的空间就越少。OpenClaw 用 **Compaction** 解决这个问题：把旧的对话压缩成一段摘要。

`context.py` 实现了这个机制：

```python
class ContextManager:
    def needs_compaction(self):
        total = sum(len(m.content) for m in self._history)
        return total > self.max_context_chars * 0.7  # 70% 阈值

    async def compact(self, brain, bootstrap_prompt):
        # 保留最近 4 条消息
        old_messages = self._history[:-4]
        recent_messages = self._history[-4:]

        # 用 LLM 自己来做摘要
        old_text = "\n".join(f"[{m.role}] {m.content[:500]}" for m in old_messages)
        response = await brain.think(
            messages=[Message(role="user", content=f"Summarize:\n{old_text}")],
            system_prompt="You are a conversation summarizer.",
        )

        self._compacted_summary = response.text
        self._history = recent_messages
```

之后每次构建上下文时，summary 会作为第一条消息注入：

```python
def build(self, bootstrap_prompt, skill_prompt="", skill_index=""):
    messages = self._sanitize_messages(list(self._history))
    if self._compacted_summary:
        summary_msg = Message(
            role="user",
            content=f"[Previous conversation summary]\n{self._compacted_summary}",
        )
        messages = [summary_msg] + messages
    return ContextWindow(system_prompt=..., messages=messages)
```

**Compaction 悖论**：OpenClaw 文档提到一个有趣的问题——当上下文已经超出窗口大小时，请求 LLM 做 compaction 本身也可能失败（因为请求太大）。OpenClaw 的解决办法是主动设置 `contextWindow` 参数，在超出前就触发压缩。

## 核心原理 7: 多 Agent 与 Spawn

OpenClaw 支持多个 Agent，每个 Agent 有独立的 workspace、记忆和 Skill 集合。Agent 之间可以通过 `sessions_spawn` 委派任务。

MiniClaw 的实现在 `agents.py`：

```python
class Agent:
    def __init__(self, agent_def, workspace, config, spawn_depth=0):
        self.spawn_depth = spawn_depth
        self.memory = Memory(workspace)        # 独立 workspace
        self.brain = Brain(agent_def.brain)     # 可以用不同的 LLM
        self.context = ContextManager(...)      # 独立上下文

    async def spawn(self, task, agent_id="main"):
        if self.spawn_depth >= self.agent_def.max_spawn_depth:
            return "Error: Max spawn depth reached"

        # 创建全新的 Agent 实例，深度 +1
        child = Agent(
            agent_def=self.config.get_agent(agent_id),
            workspace=self.config.agent_workspace(agent_id),
            config=self.config,
            spawn_depth=self.spawn_depth + 1,  # 防止无限递归
        )
        result = await child.process_message(task)
        return f"[Agent {agent_id} completed]\n{result}"
```

`spawn_agent` 被注册为一个工具，LLM 可以自己决定何时需要委派：

```python
def _register_spawn_tool(self):
    if self.spawn_depth >= self.agent_def.max_spawn_depth:
        return  # 到达深度限制，不注册 spawn 工具 → LLM 看不到它 → 不会尝试 spawn
    self.hands.register_tool("spawn_agent", spawn_handler, schema)
```

**这个设计的关键点**：spawn_depth 到达上限时，工具本身就不会被注册，LLM 根本看不到 `spawn_agent` 这个选项。这比在工具内部报错更优雅——避免 LLM 反复尝试一个注定失败的工具。

## 核心原理 8: Heartbeat — 周期性觉察

Heartbeat 是 OpenClaw 自主性三角的核心支柱。它解决了一个关键问题：**怎样让 Agent 保持关注而不产生告警疲劳**。

传统做法是给每个监控项创建一个轮询任务（检查邮件一个、检查日历一个、检查待办一个）。OpenClaw 的做法更优雅——一个 Heartbeat 替代所有轮询：

```python
class Heartbeat:
    async def tick(self):
        if not self._is_active_hours():
            return None  # 凌晨不打扰

        heartbeat_md = self.agent.memory.read_file("HEARTBEAT.md")
        if not heartbeat_md or not heartbeat_md.strip():
            return None

        # 把 HEARTBEAT.md 的全部检查项交给 Agent 一次性处理
        response = await self.agent.process_message(
            "Read HEARTBEAT.md. Follow it strictly.\n"
            "If nothing needs attention, reply HEARTBEAT_OK."
        )

        if "HEARTBEAT_OK" in response:
            return None  # 没事，静默
        return response  # 有事，告警
```

**为什么 Heartbeat 是"判断力"而不是"闹钟"？**

关键区别在于 `HEARTBEAT_OK` 协议。Heartbeat 不是每次都产出结果——Agent 会判断"是否值得打扰用户"。一个典型的 HEARTBEAT.md：

```markdown
# Heartbeat 检查清单
- 检查邮箱是否有紧急邮件
- 查看日历未来 2 小时内是否有会议
- 如果有后台任务完成了，汇报结果
- 如果已经超过 8 小时没有互动，发一条简短的 check-in
```

Agent 在一个 turn 中处理所有检查项，大部分时候回复 `HEARTBEAT_OK`（静默丢弃），只有真正需要关注的才推送到 Channel。这就是为什么它不会变成烦人的通知机器。

**Heartbeat 在 MiniClaw 中的位置**：Gateway 启动时为每个配置了 heartbeat 的 Agent 创建一个 `asyncio.Task`，每隔 N 分钟执行一次 `tick()`。告警通过 `_on_alert` 回调发送到 Gateway，再由 Gateway 广播到所有 Channel。

## 核心原理 9: Cron — 精确定时调度

Heartbeat 是"巡视"（可能没事），Cron 是"执行"（到点必须做）。OpenClaw 明确区分这两个概念：

| | Heartbeat | Cron |
|---|-----------|------|
| 触发方式 | 固定间隔（默认 30 分钟） | 精确时间点或精确间隔 |
| 行为模式 | 检查，有事才报 | 无条件执行 |
| Session | 主 session（共享上下文） | 可隔离 session（不污染对话） |
| 典型用途 | 邮件/日历/通知监控 | 日报/周报/定时分析 |

MiniClaw 的 `cron.py` 支持两种调度模式：

```python
# 精确间隔：每 15 分钟执行一次
CronJob(name="check-news", schedule="*/15", prompt="Check tech news")

# 每日定时：每天 9 点执行
CronJob(name="morning-brief", schedule="09:00", prompt="Generate morning briefing")
```

**为什么 Cron 需要 Session 隔离？**

这是 OpenClaw 的一个重要设计。如果 Cron 任务共享主 session，每次执行都会污染对话历史——Agent 和用户的自然对话中突然插入一段定时任务的输出，打乱上下文。OpenClaw 的解决方案是让 Cron 可以运行在隔离 session 中：

```bash
# OpenClaw 的完整 cron 配置
openclaw cron add \
  --name "Weekly review" \
  --cron "0 9 * * 1" \
  --session isolated \        # 不污染主对话
  --model opus \              # 用更强的模型
  --message "..."
  --announce                  # 结果通过 announce 模式推送
```

MiniClaw 简化了这个机制——所有 Cron 任务目前共享主 session。如果需要完整的隔离，可以为 Cron 创建独立的 Agent。

**动态创建 Cron**：MiniClaw 不仅支持在 `config.yaml` 中预声明 Cron，Agent 自身也可以在对话中通过 `cron_add` 工具动态创建定时任务。用户说"5 分钟后提醒我下班"，Agent 就调用 `cron_add(name="下班提醒", schedule="*/5", prompt="提醒用户该下班了")`。这让 Cron 从"管理员预配置"变成"用户随时可用的能力"。

**Cron 是 OpenClaw 用户日常最常接触的功能**。它是让 Agent "替你干活"的直接体现：每天 7 点的 morning briefing、每周一的项目回顾、每月的使用量统计。没有 Cron，Agent 只能在你说话时才做事。

## 核心原理 10: Hooks — 事件驱动响应

Hooks 是 OpenClaw 自主性三角的第三条边。如果说 Heartbeat 是"巡视"、Cron 是"定时执行"，那 Hooks 就是"有事发生了，立刻响应"。

OpenClaw 的核心设计原则之一是**事件驱动的松耦合**——组件之间不直接调用，而是通过 EventBus 广播事件。打个比方：EventBus 像一块公告栏，谁有事往上贴，关心的人自己来看；而不是挨个打电话通知。

MiniClaw 的 `hooks.py` 实现了完整的 EventBus + Hook 系统：

```python
class EventBus:
    def register(self, hook: Hook) -> None:
        # event_type="*" → 全局 hook（收所有事件）
        # event_type="message.sent" → 只收特定事件

    async def emit(self, event: HookEvent) -> None:
        # 按 priority 排序后执行所有匹配的 hook
        # 单个 hook 异常不影响其他 hook

@dataclass
class Hook:
    name: str           # "content-filter"
    event_type: str     # "message.received" 或 "*"
    handler: HookHandler
    priority: int = 100 # 越小越先执行
```

**12 种标准事件类型**：

```
session.created     — 新 Agent session 创建
session.reset       — session 重置
message.received    — 收到用户消息（Gateway 发出）
message.sent        — 响应已发送（Gateway 发出）
tool.executed       — 工具执行完成
tool.error          — 工具执行出错
heartbeat.alert     — Heartbeat 发出告警
heartbeat.ok        — Heartbeat 静默通过
cron.executed       — Cron 任务执行完成
agent.spawned       — 子 Agent 创建
context.compacted   — 上下文压缩完成
reflection.done     — 自动反思完成
```

**关键设计决策**：

1. **错误隔离**：一个 hook 崩溃不影响其他 hook 和正常处理流程
2. **优先级排序**：`priority` 越小越先执行，可用于内容过滤（高优先级拦截）
3. **全局 hook**：`event_type="*"` 可以监听所有事件（用于日志/监控）
4. **动态注册/注销**：运行时可添加或移除 hook

**实测结果**（7/7 通过）：

```
✓ 1. 基础注册和触发   — message.received + message.sent 都正确触发
✓ 2. 定向 hook        — 只订阅 message.sent 时不收到其他事件
✓ 3. 优先级排序       — priority 10→100→200 按顺序执行
✓ 4. 注销 hook        — unregister 后不再触发
✓ 5. 错误隔离         — bad hook 抛异常，good hook 仍正常执行
✓ 6. 健康检查集成     — /health 端点报告 hook 数量
✓ 7. hook 列表        — list_hooks 返回所有注册的 hook 详情
```

**三个机制的协作场景**：

```
工作日上午 9 点
 ├── [Cron] "morning-brief" 触发 → 生成今日待办汇总
 │    └── [Hook] cron.executed → 记录到日志
 │
 ├── 用户开始对话...
 │    └── [Hook] message.received → 内容过滤/敏感词检测
 │
 ├── 30 分钟后
 │    └── [Heartbeat] 检查邮件/日历/通知
 │         ├── 没事 → HEARTBEAT_OK（静默）
 │         └── 有紧急邮件 → 推送告警到 Discord
 │              └── [Hook] heartbeat.alert → 同时通知 Slack
 │
 └── 下午 5 点
      └── [Cron] "daily-report" → 生成日报
```

## 核心原理 11: 自动反思（记忆自主迭代）

Agent 有两种记忆写入方式：

1. **主动记忆**：Agent 在对话中自己决定调用 `memory_append` 工具
2. **自动反思**：每 N 轮对话后，系统自动触发一次反思

反思的实现在 `agents.py`：

```python
async def _reflect(self):
    """每 N 轮自动触发，从对话中提取可复用的知识。"""
    recent = self.context.history[-6:]  # 最近 6 条消息
    recent_text = "\n".join(
        f"[{m.role}] {m.content[:300]}" for m in recent
        if m.role in ("user", "assistant")
    )

    reflection_prompt = (
        "Review this conversation and extract important information "
        "worth remembering long-term. Focus on:\n"
        "- User preferences or habits\n"
        "- Key decisions made\n"
        "- Facts learned\n"
        "- Patterns noticed\n\n"
        "Write 1-3 concise bullet points. If nothing is worth remembering, "
        "reply NOTHING_TO_REMEMBER."
    )

    response = await self.brain.think(
        messages=[Message(role="user", content=reflection_prompt + recent_text)],
        system_prompt="You extract reusable knowledge from conversations.",
    )

    if "NOTHING_TO_REMEMBER" not in response.text:
        self.memory.append_memory(f"[Reflection] {response.text.strip()}")
```

**实际运行效果**：用户在 3 轮对话中分别说了"我叫 Bob"、"我用 Rust 和 Python"、"我要 Rust 代码示例"。反思机制自动整合成一段用户画像：

```
- [2026-03-05 17:35] [Reflection] User's primary programming language is Rust 
  (secondary: Python), with a strict preference for all code examples to be 
  provided in Rust. User favors detailed technical explanations.
```

反思比简单的 append 更智能——它做了**信息整合**，把 3 条分散的记忆合并成了结构化的用户画像。

## 模块依赖关系

```
__main__.py (CLI + serve 入口)
    └── Gateway (中央控制平面)
         ├── EventBus (事件总线，Hooks 注册)  ← 自主性核心
         ├── AgentOrchestrator (Agent 生命周期)
         │    └── Agent (独立隔离的 Agent 实例)
         │         ├── Memory (workspace 契约文件管理)
         │         ├── Brain (LLM 调用抽象层)
         │         ├── Hands (工具注册 + 执行)
         │         ├── SkillRegistry (Skill 加载 + 触发匹配)
         │         ├── Router (消息路由 + 跨 Agent 分发)
         │         └── ContextManager (上下文管理 + Compaction)
         ├── Heartbeat → EventBus (周期性觉察, 发出 heartbeat.alert)
         ├── CronScheduler → EventBus (精确定时, 发出 cron.executed)
         ├── SessionManager (JSONL 持久化 + 恢复)
         ├── HealthEndpoint (HTTP /health + /input)
         └── Channel (CLI / Discord / HTTP API)
              └── Gateway (回调)
```

## 实际运行结果

### 基础能力 (9/9 通过)

使用阿里百炼 qwen3.5-plus 模型验证：

```
✓ 1. Skill Trigger (greeting)   — "hello" 触发 greeting skill
✓ 2. Tool Use: file_list        — Agent 自主列出 workspace 目录
✓ 3. Tool Use: file_read        — Agent 读取文件并总结内容
✓ 4. Tool Use: file_write       — Agent 创建文件（磁盘验证通过）
✓ 5. Tool Use: shell_exec       — Agent 执行 shell 命令
✓ 6. Memory: append + read      — 持久记忆写入后回读确认
✓ 7. Skill Trigger (code-review)— 正则匹配触发 code-review skill
✓ 8. Context Memory             — Agent 回忆前几轮对话内容
✓ 9. Heartbeat Check            — HEARTBEAT_OK 协议正常
```

### 高级能力 (全部验证)

**Multi-Agent Spawn**：主 Agent 委派 helper Agent 计算 7! = 5040，helper 返回完整计算步骤：
```
Step 1: 7 × 6 = 42
Step 2: 42 × 5 = 210
...
Answer: 7! = 5,040
```

**Spawn 深度限制**：helper（max_spawn_depth=0）尝试 spawn 时被拒绝：
```
Error: Max spawn depth (0) reached
```

**Context Compaction**：4 轮对话后上下文达到 70% 阈值，自动压缩旧消息为摘要。压缩后 Agent 仍能记住 "Alice" 和 "ProjectX"。

**自动反思**：3 轮对话后自动触发，整合用户偏好为结构化画像。

### Gateway 能力 (5/5 通过)

```
✓ 1. 多 Channel 广播      — 2 个 handler 同时收到同一条消息
✓ 2. 跨 Agent 路由         — "hello"→main, "√144"→math(返回12)
✓ 3. Cron 任务执行          — status-check 成功调用 file_list
✓ 4. Session 隔离          — main:8条, math:2条, 互不影响
✓ 5. Agent 生命周期        — main有3 skills+10 tools, math有0 skills+9 tools
```

### Session 恢复验证

```
✓ 重启后 context_messages=40（从 JSONL 恢复 20 轮对话）
✓ /health 端点返回完整状态 JSON
✓ POST /input 通过 HTTP 发送消息并收到响应
```

## 与 OpenClaw 的对照

| 概念 | OpenClaw | MiniClaw | 差异原因 |
|------|----------|----------|----------|
| Gateway | WebSocket 服务器，多连接 | HTTP serve + 内存协调 | 生产场景可扩展为 WS |
| Workspace | `~/.openclaw/workspace-<id>/` | `workspace/` 目录 | 简化路径 |
| Brain | pi agent，支持 10+ provider | Anthropic + OpenAI + 百炼 | 覆盖主流即可 |
| Skills | 完整 YAML 定义，工具权限控制 | Markdown front-matter | 保留核心触发机制 |
| Hooks | 完整事件总线 (session/tool/message 等) | EventBus + 12 种事件 + 优先级 + 错误隔离 | 完全对齐 |
| Spawn | `sessions_spawn`，非阻塞 | `spawn()`，同步等待 | 学习项目用同步更好理解 |
| Context | Pruning + Compaction 双机制 | Compaction + 消息清洗 | Pruning 是内存优化，可省略 |
| Heartbeat | 固定间隔 + HEARTBEAT_OK | 相同实现 | 完全对齐 |
| Cron | 完整 cron 表达式 + session 隔离 + model 覆盖 | HH:MM 和 */N + 共享 session | 简化，覆盖常用场景 |
| Channel | CLI + Discord + Web + WhatsApp + 50+ | CLI + Discord + HTTP API | 学习项目覆盖核心类型 |
| 反思 | 无内置（靠 SOUL.md 指导） | 自动反思 + NOTHING_TO_REMEMBER 协议 | MiniClaw 的增强 |
| Session 恢复 | Gateway 持久化，重启自动恢复 | JSONL 持久化，恢复最近 20 轮 | 简化版，原理相同 |
| 健康检查 | Dashboard + WebSocket 心跳 | HTTP /health 端点 | 简化，可对接 k8s/Docker |
| 代码量 | 43 万行 TypeScript | ~2,700 行 Python | 约 1/160 |

## 快速上手

```bash
# 1. 安装
cd miniclaw
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置 (~/.miniclaw/config.yaml)
python -m miniclaw init

# 3. 设置 API Key — 编辑 ~/.miniclaw/config.yaml
# 默认 provider: dashscope（百炼 qwen-plus）
export DASHSCOPE_API_KEY=sk-xxx       # 百炼
# 也可以在 config.yaml 中切换其他 provider:
#   provider: anthropic    → export ANTHROPIC_API_KEY=sk-ant-xxx
#   provider: openai       → export OPENAI_API_KEY=sk-xxx
#   provider: dashscope-coding → export DASHSCOPE_API_KEY=sk-sp-xxx（Coding Plan）

# 4. 运行
python -m miniclaw chat              # CLI 交互
python -m miniclaw serve             # 生产模式（HTTP API + Heartbeat + Cron）
python -m miniclaw serve --discord-token $TOKEN  # 生产模式 + Discord
python -m miniclaw discord           # 仅 Discord bot
python -m miniclaw heartbeat         # 手动触发 heartbeat
python -m miniclaw status            # 查看配置

# CLI 可用命令
/skills    # 查看已加载的 Skill
/agents    # 查看 Agent 列表
/heartbeat # 手动触发一次 heartbeat
/compact   # 手动压缩上下文
/clear     # 清空对话历史
/quit      # 退出

# 生产模式下 HTTP API
curl http://localhost:8765/health                                    # 健康检查
curl -X POST http://localhost:8765/input -d '{"text": "hello"}'     # 发送消息
```

## 如何扩展

**添加新 Skill**：在 `workspace/skills/` 下创建 Markdown 文件：

```markdown
---
name: my-skill
description: What this skill does
triggers:
  - type: keyword
    pattern: "trigger word"
  - type: regex
    pattern: "regex.*pattern"
tools:
  - shell_exec
  - file_read
---

Instructions for the LLM when this skill is triggered.
```

**添加新工具**：两种方式：
1. 在 `hands.py` 中添加 `_tool_xxx` 方法和对应的 schema
2. 运行时用 `agent.hands.register_tool(name, handler, schema)` 动态注册

**添加新 Agent**：在 `config.yaml` 中定义，每个 Agent 有独立的 workspace：

```yaml
agents:
  main:
    brain: { provider: dashscope-coding, model: qwen3.5-plus }
  helper:
    workspace: ~/workspace-helper
    brain: { provider: dashscope-coding, model: qwen3.5-plus }
    max_spawn_depth: 0  # 不能再 spawn
```

**添加 Cron 定时任务**：在 `config.yaml` 中声明：

```yaml
agents:
  main:
    brain: { provider: dashscope, model: qwen-plus }
    cron:
      - name: daily-summary
        schedule: "09:00"
        prompt: "Summarize the key events from MEMORY.md"
      - name: check-news
        schedule: "*/30"
        prompt: "Check tech news and report anything relevant"
```

也可以通过代码动态注册：

```python
from miniclaw.cron import CronJob
gateway.add_cron_job("main", CronJob(
    name="daily-summary",
    schedule="09:00",
    prompt="Summarize the key events from MEMORY.md"
))
```

## 生产部署

### serve 命令

`python -m miniclaw serve` 是生产入口，启动后 Gateway 持续运行：

```bash
# 基础启动（HTTP 健康检查 + Heartbeat + Cron + Session 恢复）
python -m miniclaw serve --port 8765

# 带 Discord Channel 启动
python -m miniclaw serve --port 8765 --discord-token $DISCORD_BOT_TOKEN

# 后台运行
nohup python -m miniclaw serve > miniclaw.log 2>&1 &
```

提供两个 HTTP 端点：
- `GET /health` — 健康检查，返回运行状态、已处理请求数、Agent 上下文信息
- `POST /input` — 发送消息，body: `{"text": "...", "agent_id": "main"}`

### 进程保活

MiniClaw 本身不包含看门狗，需要外部进程管理器保活：

```bash
# systemd (Linux)
[Unit]
Description=MiniClaw
After=network.target
[Service]
ExecStart=/path/to/.venv/bin/python -m miniclaw serve
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target

# PM2 (跨平台)
pm2 start "python -m miniclaw serve" --name miniclaw

# Docker
FROM python:3.11-slim
COPY . /app
RUN pip install -r /app/requirements.txt
CMD ["python", "-m", "miniclaw", "serve"]
HEALTHCHECK CMD curl -f http://localhost:8765/health || exit 1
```

### Session 恢复

Gateway 启动时自动从 `~/.miniclaw/sessions/{agent_id}.jsonl` 恢复最近 20 轮对话。
即使进程崩溃重启，Agent 也能记住之前的对话。

### 健康检查返回示例

```json
{
  "status": "healthy",
  "uptime_seconds": 6.1,
  "requests": 0,
  "errors": 0,
  "agents": {
    "main": { "context_messages": 40, "turn_count": 0, "skills": 3 }
  },
  "heartbeats": ["main"],
  "cron_schedulers": [],
  "channels": 0,
  "timestamp": "2026-03-05T17:48:19"
}
```

## 生产能力清单

### 已实现 ✓

| 能力 | 实现 | 说明 |
|------|------|------|
| 进程长驻 | `serve` 命令 | Gateway + Heartbeat + Cron 持续运行 |
| 健康检查 | `GET /health` | 返回 JSON 状态，可对接 k8s/Docker/PM2 |
| HTTP API | `POST /input` | 可通过 HTTP 发送消息，适合集成 |
| Session 恢复 | JSONL 持久化 | 重启自动恢复最近 20 轮对话 |
| 信号处理 | SIGINT/SIGTERM | 优雅关闭，确保 session 保存 |
| 错误计数 | `_error_count` | 健康检查中暴露错误数 |
| Discord Channel | discord.py | 24 小时在线的 Discord Bot |
| 多 Agent | 按需创建 | 不同 Agent 独立 workspace/context |
| Heartbeat | asyncio.Task | 可配置间隔和活跃时段 |
| Cron | asyncio.Task | 每日定时和间隔执行 |
| Hooks / EventBus | `hooks.py` | 12 种事件类型，优先级排序，错误隔离 |

### 未实现（生产化差距）

| 能力 | 重要度 | 说明 | 实现成本 |
|------|--------|------|---------|
| **WebSocket 服务模式** | 高 | Gateway 作为 WS 服务器，Channel 通过 WS 连接而非进程内调用 | ~200 行 |
| **Token 计费** | 高 | 记录每次 API 调用的 prompt/completion token 数和成本 | ~50 行 |
| **限流** | 高 | 每分钟/每小时 API 调用上限，防止 Heartbeat/Cron 循环消耗 | ~80 行 |
| **流式响应** | 中 | `stream=True`，SSE/WebSocket 逐步推送而非等全部生成 | ~100 行 |
| **Thread 隔离** | 中 | Discord thread 内独立对话上下文 | ~80 行 |
| **配置热更新** | 中 | 文件监听 → 运行时动态更新 Skills/Cron 而无需重启 | ~80 行 |
| **结构化日志** | 低 | JSON 格式日志 + Prometheus 指标 | ~60 行 |
| **认证鉴权** | 低 | HTTP API 的 Bearer token 认证 | ~30 行 |
| **多 Agent 持久化** | 低 | 运行时动态注册/注销 Agent 并持久化 | ~60 行 |

## 性能对比

### MiniClaw vs OpenClaw

| 指标 | MiniClaw | OpenClaw | 说明 |
|------|----------|----------|------|
| **代码量** | ~2,700 行 Python | ~430,000 行 TypeScript | 约 1/160 |
| **启动时间** | <1 秒 | 数秒（需启动 WS 服务器、加载插件） | Python 启动快 |
| **内存占用** | ~30-50 MB | ~200-500 MB | 无 WS 服务器、无插件系统 |
| **响应延迟** | 取决于 LLM API（通常 2-5 秒） | 同上 | 瓶颈在 LLM，框架本身开销可忽略 |
| **并发能力** | 单线程 asyncio，同时处理有限 | 多进程/多线程，高并发 | MiniClaw 适合单用户/少量 Channel |
| **功能覆盖** | 11/15 核心能力 | 15/15 | MiniClaw 缺 WS 服务、流式、Thread 隔离、配置热更新 |

### 性能瓶颈在哪里？

MiniClaw 的性能瓶颈**不在框架本身**，而在 LLM API 调用：

```
框架处理（路由/上下文组装/工具分发）: <5ms
LLM API 单次调用: 1-5 秒
一次完整对话（含 2-3 轮工具调用）: 5-15 秒
```

所以 MiniClaw 的"性能"和 OpenClaw 在同一数量级——两者的延迟 99% 来自 LLM API。
MiniClaw 因为少了 WebSocket 中间层、少了插件系统，单次请求的框架开销反而更小。

**真正需要关注的**不是速度，而是：
1. **Token 成本** — Heartbeat/Cron 会持续消耗 API 调用，需要限流
2. **Context 膨胀** — 长期运行后对话历史增长，需要定期 compaction
3. **并发** — 多个 Channel 同时发消息时，asyncio 是串行处理的

## 设计决策复盘

回头看 MiniClaw 的实现过程，有几个设计决策值得记录——不是"学到了什么"，而是"做了什么取舍、为什么"。

**1. Gateway 中心化 vs 点对点**

Agent 框架有两种拓扑：点对点（Agent 直接发消息给其他 Agent）和 Hub-and-Spoke（所有消息经过中心节点）。OpenClaw 选了后者。代价是 Gateway 成为单点，但换来了三个好处：Channel 和 Agent 完全解耦（加一个 Discord Channel 不需要改任何 Agent 代码）、Session 管理天然集中（只有一个地方需要做持久化）、全局 Hook 只需要监听一个节点。对于 Agent 框架这种 I/O 密集型应用，Gateway 不会成为性能瓶颈——瓶颈永远在 LLM API 调用。

**2. Markdown 文件作为运行时配置**

这是 OpenClaw 最反常规的设计——Agent 的行为由 Markdown 文件定义，而不是代码或 JSON schema。写 MiniClaw 的过程中发现这个选择背后有明确的工程考量：LLM 天然理解 Markdown（不需要格式转换），人类可以直接编辑（不需要专用工具），Git diff 可读（变更审查成本低），热更新成本为零（修改文件即生效）。唯一的代价是没有 schema 校验，但对于定义"人格"和"记忆"这类非结构化内容，强 schema 反而是过度设计。

**3. 自主性的三层分离**

实现 Heartbeat、Cron 和 Hooks 的过程中，最重要的发现是这三者之间的边界必须清晰。早期尝试过用 Cron 做"定期检查"，但很快发现问题——Cron 是无条件执行的，每次都会产生 LLM 调用费用；而 Heartbeat 的 `HEARTBEAT_OK` 协议允许 Agent 自己判断"这次不值得打扰"，大部分时候可以静默。反过来，如果用 Heartbeat 做"每天 9 点生成日报"，你得把时间判断逻辑写进 HEARTBEAT.md，让 LLM 自己判断"现在是不是 9 点"——这显然不靠谱。三者各有适用场景：Heartbeat 处理模糊判断、Cron 处理精确调度、Hooks 处理事件响应。

**4. Compaction 中的消息配对约束**

Context Compaction 的核心难点不在于摘要质量，而在于消息序列的结构约束。LLM API 要求 `tool_call` 和 `tool_result` 严格配对——如果把 `tool_call` 切到旧消息、`tool_result` 留在新消息，API 会直接报错。所以 `_find_safe_split` 必须回退到最近的 `user` 消息边界。同时 compaction 后还需要 `_sanitize_messages` 清洗孤立的 `tool_result`（没有前驱 `tool_call` 的）。这个约束在 OpenClaw 的代码里也有体现，但文档中几乎没提，只能看源码才知道。

**5. Spawn 的深度控制用"工具不可见"实现**

多 Agent spawn 最优雅的设计是：到达深度限制时，`spawn_agent` 工具本身不注册——LLM 的 tool list 里看不到这个选项，自然不会尝试。这比在工具内部返回错误更好：如果工具存在但返回错误，LLM 可能会反复重试（"也许换个参数就行"），浪费多轮 API 调用。而工具不存在 = LLM 根本不知道可以 spawn，会直接自己处理任务。这是一个通用模式——**控制 LLM 行为的最佳方式是控制它能看到什么工具**，而不是在工具内部做权限检查。

**6. 多 provider 适配的真正成本**

统一 Anthropic 和 OpenAI 的 API 不只是"换个 SDK 调用"。工具调用协议有三个关键差异：Anthropic 把 `tool_result` 嵌套在 `user` 消息里，OpenAI 用独立的 `tool` 角色；Anthropic 用 `input` 字段传参数，OpenAI 用 `arguments`（字符串）；百炼的 Coding Plan 需要特定的 `base_url` 和以 `sk-sp-` 开头的 API Key。`Brain` 类的 250 行代码中，超过一半在处理这些格式转换。这些差异不是 API 文档首页能看到的——只有在实现 tool-use loop 时才会踩到。

## 推荐阅读

按这个顺序阅读 MiniClaw 代码，从简单到核心：

1. `memory.py` (135行) — 最简单，理解 workspace 契约文件
2. `skills.py` (134行) — 理解 Skill 定义、触发匹配和渐进式披露索引
3. `hooks.py` (113行) — 理解 EventBus 和事件驱动设计
4. `hands.py` (235行) — 理解工具注册和执行
5. `brain.py` (250行) — 理解 LLM 调用的协议差异
6. `agents.py` (266行) — 核心，理解 Agent Loop、Spawn 和自动反思
7. `context.py` (186行) — 理解上下文管理、Compaction 和消息清洗
8. `gateway.py` (303行) — 理解 Hub-and-Spoke 协调、Session 恢复、健康检查、动态 Cron 工具注册
9. `heartbeat.py` (114行) — 理解 Heartbeat 自主性
10. `cron.py` (142行) — 理解 Cron 定时任务
11. `channels/discord.py` (155行) — 理解 Channel 抽象
12. `__main__.py` (242行) — CLI 和 serve 命令

## 最后

本来只是想搞明白 OpenClaw 到底在做什么，结果越拆越停不下来。2700 行 Python 就够理解 11 个核心原理，剩下的 42.73 万行是工程化、产品化和生态建设——那些虽然重要，但不影响理解架构本身。

想真正理解这些原理，最快的方法不是读这篇文章，而是 clone MiniClaw 自己改几行代码试试——比如加一个新的 Skill、写一段 HEARTBEAT.md、或者给 Cron 配一个每天早上的任务。跑起来的那一刻，很多架构决策就自然理解了。
