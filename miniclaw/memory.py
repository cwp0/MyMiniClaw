#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: memory.py
# @Description: 记忆模块
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/13 15:52
# @Version: 1.0


"""Markdown-based persistent memory, mirroring OpenClaw's workspace bootstrap files.

OpenClaw assembles context from these workspace files on every API call:
  SOUL.md → personality and rules
  IDENTITY.md → who the agent is
  MEMORY.md → persistent learnings (append-only)
  HEARTBEAT.md → periodic check instructions
  TOOLS.md → tool usage hints
  USER.md → user preferences
  BOOTSTRAP.md → first-run instructions

  workspace/
├── SOUL.md          # Agent 人格
├── IDENTITY.md      # Agent 身份
├── MEMORY.md        # 学习记录（append-only）
├── HEARTBEAT.md     # 心跳指令
├── TOOLS.md         # 工具提示
├── USER.md          # 用户偏好
├── BOOTSTRAP.md     # 首次运行引导
└── skills/          # 技能目录
    ├── greeting.md
    └── researcher.md

"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path



logger = logging.getLogger(__name__)

BOOTSTRAP_FILES = [
    "BOOTSTRAP.md",
    "HEARTBEAT.md",
    "USER.md",
    "IDENTITY.md",
    "TOOLS.md",
    "SOUL.md",
]

class Memory:
    """Manages the workspace directory and its Markdown bootstrap files."""
    # 管理工作区目录及其 Markdown 引导文件
    def __init__(self, workspace: Path, max_chars_per_file: int = 20_000):
        """初始化 Memory 实例
        
        Args:
            workspace: 工作区目录路径
            max_chars_per_file: 单个文件最大字符数限制，默认20,000字符
        """
        # 初始化工作区目录和字符限制
        self.workspace_dir = workspace
        self.max_chars_per_file = max_chars_per_file
        self._ensure_workspace()

    def _ensure_workspace(self) -> None:
        """确保工作区目录结构存在
        
        创建工作区主目录和 skills 子目录，使用幂等性设计确保多次调用不报错
        """
        # 创建工作区主目录，parents=True 创建中间目录，exist_ok=True 避免重复创建报错
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        skills_dir = self.workspace_dir / "skills"
        # 创建技能目录
        skills_dir.mkdir(exist_ok=True)

    def read_file(self, filename: str) -> str | None:
        """读取工作区文件内容
        
        Args:
            filename: 要读取的文件名
            
        Returns:
            文件内容字符串，如果文件不存在则返回 None
            超长文件会被自动截断并在末尾添加截断提示
        """
        # 构建完整文件路径
        path = self.workspace_dir / filename
        # 文件不存在时返回 None（防御性设计）
        if not path.exists():
            return None
        # 读取文件内容
        content = path.read_text(encoding="utf-8")
        # 防御性设计：超长内容自动截断并记录警告日志
        if len(content) > self.max_chars_per_file:
            logger.warning(f"{filename} exceeds {self.max_chars_per_file} chars, truncating")
            content = content[:self.max_chars_per_file] + "\n\n...truncated..."
        return content

    def write_file(self, filename: str, content: str) -> None:
        """写入内容到工作区文件
        
        Args:
            filename: 目标文件名
            content: 要写入的内容
            
        自动创建文件所在目录的中间路径
        """
        # 构建完整文件路径
        path = self.workspace_dir / filename
        # 写入时自动创建中间目录（幂等性设计）
        path.parent.mkdir(parents=True, exist_ok=True)
        # 写入文件内容
        path.write_text(content, encoding="utf-8")
        logger.debug(f"Wrote {len(content)} chars to {filename}")

    def append_memory(self, entry: str) -> None:
        """Append a learning to MEMORY.md (the persistent append-only log). 追加学习记录到 MEMORY.md（持久化的追加式日志）
        
        Args:
            entry: 要追加的学习记录内容
            
        实现 append-only 模式，只追加不修改，保证历史记录完整性
        文件不存在时自动创建带标题的初始文件
        """
        # 格式化当前时间戳
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        # 构造带时间戳的记录行
        line = f"\n- {timestamp}: {entry}\n"
        path = self.workspace_dir / "MEMORY.md"
        # 文件不存在时初始化创建
        if not path.exists():
            path.write_text(f"# Memory\n{line}", encoding="utf-8")
        else:
            # 追加模式写入文件
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)

    def create_default(self) -> None:
        """Create default workspace files if they don't exist. 创建默认工作区文件（如果不存在）
        
        实现幂等性设计：已有文件不覆盖，保护用户自定义内容
        每个文件对应 Agent 的特定维度（人格、身份、心跳指令等）
        """
        # 定义默认文件内容映射
        defaults = {
            "SOUL.md": (
                "# Soul\n\n"
                "You are a helpful AI assistant powered by MiniClaw.\n"
                "Be concise, accurate, and helpful.\n"
                "When uncertain, say so explicitly.\n\n"
                "## Capabilities\n"
                "- Execute shell commands (shell_exec)\n"
                "- Read and write files (file_read, file_write)\n"
                "- Make HTTP requests (http_get)\n"
                "- Persist learnings (memory_append, memory_read)\n"
                "- Spawn sub-agents for delegation (spawn_agent)\n"
                "- Schedule timed tasks (cron_add, cron_list)\n\n"
                "## Scheduling\n"
                "When a user asks for a reminder or scheduled task, use cron_add.\n"
            ),
            "IDENTITY.md": (
                "# Identity\n\n"
                "- Name: MiniClaw\n"
                "- Role: General-purpose assistant\n"
                "- Created: Learning project based on OpenClaw principles\n"
            ),
            "HEARTBEAT.md": (
                "# Heartbeat\n\n"
                "Check if there are any pending tasks or reminders.\n"
                "If nothing needs attention, reply HEARTBEAT_OK.\n"
            ),
            "MEMORY.md": "# Memory\n",
        }
        # 幂等性创建：仅当文件不存在时创建
        for filename, content in defaults.items():
            path = self.workspace_dir / filename
            if not path.exists():
                path.write_text(content, encoding="utf-8")
                logger.debug(f"Created default {filename}")

    def assemble_bootstrap(self, first_run: bool = False) -> str:
        """Assemble bootstrap context from workspace files. 从工作区文件组装引导上下文
    
        Follows OpenClaw's injection order:
        BOOTSTRAP.md (first run only) → HEARTBEAT.md → USER.md → IDENTITY.md 
        → TOOLS.md → SOUL.md
        遵循 OpenClaw 的注入顺序：
        BOOTSTRAP.md（仅首次运行）→ HEARTBEAT.md → USER.md → IDENTITY.md 
        → TOOLS.md → SOUL.md
            
        Args:
            first_run: 是否为首次运行，决定是否包含 BOOTSTRAP.md
                
        Returns:
            组装好的引导上下文字符串，各部分用分隔符连接
        """
        parts = []
        # 按照 OpenClaw 设计约定的顺序处理引导文件
        for filename in BOOTSTRAP_FILES:
            # 条件注入：BOOTSTRAP.md 仅在首次运行时包含
            if filename == "BOOTSTRAP.md" and not first_run:
                continue
            content = self.read_file(filename)
            # 空文件跳过，避免产生无意义的 section
            if content:
                parts.append(f"## [{filename}]\n\n{content}")
        # 始终包含内存记录
        memory_content = self.read_file("MEMORY.md")
        if memory_content:
            parts.append(f"## [MEMORY.md]\n\n{memory_content}")
            
        # 使用分隔符连接各部分内容，让 LLM 清晰区分不同 section
        return "\n\n---\n\n".join(parts)

    def list_skills(self) -> list[Path]:
        """列出技能目录中的所有技能文件
        
        Returns:
            排序后的 .md 和 .yaml 技能文件路径列表
            支持两种格式：.md（Markdown）和 .yaml（YAML配置）
        """
        skills_dir = self.workspace_dir / "skills"
        # 目录不存在时返回空列表
        if not skills_dir.exists():
            return []
        # 使用 glob 查找并排序两种格式的技能文件
        return sorted(skills_dir.glob("*.md")) + sorted(skills_dir.glob("*.yaml"))

    def create_defaults(self) -> None:
        """
        Create default workspace files if they don't exist.
        """
        defaults = {
            "SOUL.md": (
                "# Soul\n\n"
                "You are a helpful AI assistant powered by MiniClaw.\n"
                "Be concise, accurate, and helpful.\n"
                "When uncertain, say so explicitly.\n\n"
                "## Capabilities\n"
                "- Execute shell commands (shell_exec)\n"
                "- Read and write files (file_read, file_write)\n"
                "- Make HTTP requests (http_get)\n"
                "- Persist learnings (memory_append, memory_read)\n"
                "- Spawn sub-agents for delegation (spawn_agent)\n"
                "- Schedule timed tasks (cron_add, cron_list)\n\n"
                "## Scheduling\n"
                "When a user asks for a reminder or scheduled task, use cron_add.\n"
            ),
            "IDENTITY.md": (
                "# Identity\n\n"
                "- Name: MiniClaw\n"
                "- Role: General-purpose assistant\n"
                "- Created: Learning project based on OpenClaw principles\n"
            ),
            "HEARTBEAT.md": (
                "# Heartbeat\n\n"
                "Check if there are any pending tasks or reminders.\n"
                "If nothing needs attention, reply HEARTBEAT_OK.\n"
            ),
            "MEMORY.md": "# Memory\n",
        }
        for filename, content in defaults.items():
            path = self.workspace_dir / filename
            if not path.exists():
                path.write_text(content, encoding="utf-8")
                logger.info(f"Created default {filename}")


def main() -> None:
    """测试 Memory 类的各项核心功能。"""
    import tempfile
    import shutil

    workspace = Path(tempfile.mkdtemp(prefix="miniclaw_test_"))
    print(f"[测试工作区] {workspace}\n")

    try:
        memory = Memory(workspace)

        # ── 1. 验证工作区目录结构 ──────────────────────────────────────────
        print("=== 1. 验证工作区目录结构 ===")
        assert workspace.exists(), "工作区主目录应存在"
        assert (workspace / "skills").exists(), "skills 子目录应存在"
        print("✓ 工作区目录结构正常\n")

        # ── 2. 创建默认文件 ────────────────────────────────────────────────
        print("=== 2. 创建默认文件 ===")
        memory.create_default()
        for filename in ["SOUL.md", "IDENTITY.md", "HEARTBEAT.md", "MEMORY.md"]:
            content = memory.read_file(filename)
            assert content is not None, f"{filename} 应已创建"
            print(f"✓ {filename} ({len(content)} chars)")
        print()

        # ── 3. 写入与读取文件 ──────────────────────────────────────────────
        print("=== 3. 写入与读取文件 ===")
        memory.write_file("USER.md", "# User\n\n- Language: Chinese\n- Style: concise\n")
        user_content = memory.read_file("USER.md")
        assert user_content is not None and "Language" in user_content
        print(f"✓ write_file / read_file 正常，内容：\n{user_content}")

        # ── 4. 读取不存在的文件返回 None ──────────────────────────────────
        print("=== 4. 读取不存在文件 ===")
        result = memory.read_file("NOT_EXIST.md")
        assert result is None, "不存在的文件应返回 None"
        print("✓ 返回 None 正常\n")

        # ── 5. 超长内容截断 ────────────────────────────────────────────────
        print("=== 5. 超长内容截断 ===")
        small_memory = Memory(workspace, max_chars_per_file=50)
        memory.write_file("LONG.md", "A" * 200)
        truncated = small_memory.read_file("LONG.md")
        assert truncated is not None and truncated.endswith("...truncated...")
        print(f"✓ 截断正常，截断后长度：{len(truncated)}\n")

        # ── 6. 追加记忆条目 ────────────────────────────────────────────────
        print("=== 6. 追加记忆条目 ===")
        memory.append_memory("用户偏好使用中文回复")
        memory.append_memory("项目使用 Python 3.11")
        memory_content = memory.read_file("MEMORY.md")
        assert memory_content is not None
        assert "用户偏好使用中文回复" in memory_content
        assert "项目使用 Python 3.11" in memory_content
        print(f"✓ MEMORY.md 内容：\n{memory_content}")

        # ── 7. 幂等性：create_default 不覆盖已有文件 ──────────────────────
        print("=== 7. 幂等性验证 ===")
        memory.write_file("SOUL.md", "# Custom Soul\n\nCustom content.\n")
        memory.create_default()
        soul_content = memory.read_file("SOUL.md")
        assert soul_content is not None and "Custom content" in soul_content
        print("✓ create_default 不覆盖已有文件\n")

        # ── 8. 组装引导上下文（非首次运行）────────────────────────────────
        print("=== 8. 组装引导上下文（first_run=False）===")
        bootstrap = memory.assemble_bootstrap(first_run=False)
        assert "BOOTSTRAP.md" not in bootstrap, "非首次运行不应包含 BOOTSTRAP.md"
        assert "[SOUL.md]" in bootstrap
        assert "[MEMORY.md]" in bootstrap
        print(f"✓ 引导上下文长度：{len(bootstrap)} chars，包含正确 sections\n")

        # ── 9. 组装引导上下文（首次运行）──────────────────────────────────
        print("=== 9. 组装引导上下文（first_run=True）===")
        memory.write_file("BOOTSTRAP.md", "# Bootstrap\n\nFirst run instructions.\n")
        bootstrap_first = memory.assemble_bootstrap(first_run=True)
        assert "[BOOTSTRAP.md]" in bootstrap_first
        print(f"✓ 首次运行引导上下文包含 BOOTSTRAP.md，长度：{len(bootstrap_first)} chars\n")

        # ── 10. 列出技能文件 ───────────────────────────────────────────────
        print("=== 10. 列出技能文件 ===")
        memory.write_file("skills/greeting.md", "# Greeting Skill\n\nSay hello.\n")
        memory.write_file("skills/researcher.yaml", "name: researcher\n")
        skills = memory.list_skills()
        skill_names = [skill.name for skill in skills]
        assert "greeting.md" in skill_names
        assert "researcher.yaml" in skill_names
        print(f"✓ 技能文件列表：{skill_names}\n")

        print("=" * 40)
        print("✅ 所有测试通过！")

    finally:
        shutil.rmtree(workspace)
        print(f"[清理] 已删除测试工作区 {workspace}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    main()