#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @File: hands.py
# @Description: 工具执行引擎
# @Author: 鹤童 (<a href="mailto:chenwenpeng.cwp@alibaba-inc.com">发送邮件</a>)
# @Time: 2026/3/16 16:24
# @Version: 1.0

"""Tool execution engine — MiniClaw 的"双手"模块。

MiniClaw 是一个 AI Agent 框架，把 Agent 拟人化成一个"人"：
- Brain（大脑）：负责思考、决策（调用 LLM）
- Hands（双手）：负责执行动作（操作文件、跑命令、发请求等）

本文件就是"双手"。Brain 说"帮我读一下 README.md"，Hands 就去真的读文件并把内容返回给 Brain。

Built-in tools:
- shell_exec: Run shell commands
- file_read: Read file contents
- file_write: Write file contents
- file_list: List directory contents
- http_get: HTTP GET request
- memory_append: Append to MEMORY.md
- memory_read: Read a workspace file
"""


from __future__ import annotations

import asyncio          # Python 异步编程库，用于并发执行
import json             # JSON 序列化，用于日志打印参数
import logging          # 日志记录
import os               # 操作系统接口（当前未实际使用）
import subprocess       # 子进程管理（当前未实际使用）
from pathlib import Path        # 面向对象的文件路径操作
from typing import Any, Callable, Awaitable  # 类型注解

import aiohttp          # 异步 HTTP 客户端库，用于 http_get 工具


logger = logging.getLogger(__name__)


# 工具函数类型
# 输入：一个字典（dict[str, Any]），比如 {"command": "ls", "timeout": 10}
# 输出：一个异步字符串（Awaitable[str]），即 async 函数返回 str
# 所有工具（不管内置还是自定义）都必须符合这个签名，这样 execute() 方法才能统一调用它们。
ToolFunc = Callable[[dict[str, Any]], Awaitable[str]]


# 列表，里面有 7 个字典，每个字典描述一个内置工具。这些描述不是给人看的，是给 LLM 看的。
BUILTIN_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "shell_exec",
        "description": "Execute a shell command and return stdout/stderr. Use for system operations, git, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)", "default": 30},
            },
            "required": ["command"],
        },
    },
    {
        "name": "file_read",
        "description": "Read the contents of a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "file_write",
        "description": "Write content to a file. Creates parent directories if needed.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to write to"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "file_list",
        "description": "List files and directories at a given path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list (default: current directory)", "default": "."},
            },
        },
    },
    {
        "name": "http_get",
        "description": "Make an HTTP GET request and return the response body.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "memory_append",
        "description": "Append a learning or note to persistent MEMORY.md.",
        "parameters": {
            "type": "object",
            "properties": {
                "entry": {"type": "string", "description": "The memory entry to append"},
            },
            "required": ["entry"],
        },
    },
    {
        "name": "memory_read",
        "description": "Read a file from the workspace directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Filename relative to workspace (e.g., MEMORY.md, skills/example.md)"},
            },
            "required": ["filename"],
        },
    },
]




class Hands:
    """Executes tools — the agent's ability to act on the world.

    核心引擎类，负责管理和执行所有工具（内置工具 + 自定义工具）。
    """

    def __init__(self, workspace_dir: Path, memory=None):
        """初始化 Hands 实例。

        Args:
            workspace_dir: 工作目录，所有文件操作都被限制在此目录内（沙箱安全）
            memory: Memory 模块的引用，用于 memory_append/read 操作
        """
        self._workspace = workspace_dir  # 工作目录，所有文件操作都限制在这里面
        self._memory = memory  # Memory 模块的引用，用于 memory_append/read
        self._custom_tools: dict[str, ToolFunc] = {}  # 自定义工具的函数映射
        self._custom_schemas: list[dict[str, Any]] = []  # 自定义工具的 Schema

    def register_tool(
        self, name: str, func: ToolFunc, schema: dict[str, Any]
    ) -> None:
        """注册自定义工具 —— 插件扩展点。

        允许外部为 Hands 添加新的工具能力。例如添加"发邮件"工具：
            hands.register_tool("send_email", my_email_func, email_schema)

        Args:
            name: 工具名称
            func: 工具函数，必须符合 ToolFunc 签名
            schema: 工具的 JSON Schema 描述，供 LLM 理解如何使用
        """
        self._custom_tools[name] = func
        self._custom_schemas.append(schema)

    def get_tool_schemas(self, allowed: list[str] | None = None) -> list[dict[str, Any]]:
        """获取工具 Schema 列表，供 Brain 提供给 LLM。

        Args:
            allowed: 白名单过滤。None 或 ["*"] 返回全部工具；
                     否则只返回指定名称的工具 Schema

        Returns:
            工具 Schema 列表，每个 Schema 描述工具的名称、功能和参数
        """
        all_schemas = BUILTIN_TOOL_SCHEMAS + self._custom_schemas
        if allowed is None or "*" in allowed:
            return all_schemas  # 不限制，返回全部
        return [s for s in all_schemas if s["name"] in allowed]  # 按白名单过滤

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """统一执行入口 —— 最核心的方法。

        执行流程：
        1. 打日志记录工具调用
        2. 先查自定义工具，有则执行
        3. 再通过反射查内置工具（找 _tool_xxx 方法）
        4. 执行并统一捕获异常

        Args:
            tool_name: 工具名称，如 "file_read"
            arguments: 参数字典，如 {"path": "README.md"}

        Returns:
            工具执行结果的字符串

        示例：
            LLM 说要调用 file_read
            Brain 把 ("file_read", {"path": "README.md"}) 传给 execute()
            execute() 用 getattr(self, "_tool_file_read") 找到内置方法
            调用 _tool_file_read({"path": "README.md"}) 并返回结果
        """
        logger.info(f"Tool call: {tool_name}({json.dumps(arguments, ensure_ascii=False)[:200]})")

        # 先查自定义工具
        if tool_name in self._custom_tools:
            try:
                return await self._custom_tools[tool_name](arguments)
            except Exception as e:
                logger.error(f"Custom tool {tool_name} failed: {e}")
                return f"Error: {e}"

        # 通过反射查内置工具（getattr 自动映射 _tool_ 前缀方法）
        handler = getattr(self, f"_tool_{tool_name}", None)
        if not handler:
            return f"Error: Unknown tool '{tool_name}'"

        # 执行并统一捕获异常
        try:
            return await handler(arguments)
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return f"Error: {e}"

    async def _tool_shell_exec(self, args: dict[str, Any]) -> str:
        """执行 shell 命令。

        使用 asyncio.create_subprocess_shell 异步执行命令（不阻塞事件循环），
        通过 wait_for 设置超时防止命令卡死，工作目录固定为 workspace。

        Args:
            args: 包含 command（必填）和 timeout（可选，默认 30 秒）

        Returns:
            命令的标准输出、标准错误和退出码
        """
        command = args["command"]
        timeout = args.get("timeout", 30)
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,    # 捕获标准输出
                stderr=asyncio.subprocess.PIPE,    # 捕获标准错误
                cwd=str(self._workspace),          # 在 workspace 目录下执行
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout  # 设置超时
            )
            result = ""
            if stdout:
                result += stdout.decode("utf-8", errors="replace")
            if stderr:
                result += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")
            result += f"\n[exit code: {proc.returncode}]"
            return result.strip()
        except asyncio.TimeoutError:
            return f"Error: Command timed out after {timeout}s"

    async def _tool_file_read(self, args: dict[str, Any]) -> str:
        """读取文件内容。

        先通过 _resolve_path 解析并校验路径安全，防止路径逃逸攻击。
        超过 5 万字符的内容会被截断，避免返回过大响应。

        Args:
            args: 包含 path（文件路径）

        Returns:
            文件内容字符串，或错误信息
        """
        path = self._resolve_path(args["path"])  # 解析并校验路径安全
        if not path.exists():
            return f"Error: File not found: {args['path']}"
        content = path.read_text(encoding="utf-8")
        if len(content) > 50_000:                  # 超过 5 万字符就截断
            content = content[:50_000] + "\n\n[...truncated at 50000 chars...]"
        return content

    async def _tool_file_write(self, args: dict[str, Any]) -> str:
        """写入文件内容。

        自动创建父目录（如果不存在），通过 _resolve_path 确保路径安全。

        Args:
            args: 包含 path（文件路径）和 content（写入内容）

        Returns:
            写入成功的提示信息
        """
        path = self._resolve_path(args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)  # 自动创建父目录
        path.write_text(args["content"], encoding="utf-8")
        return f"Written {len(args['content'])} chars to {args['path']}"

    async def _tool_file_list(self, args: dict[str, Any]) -> str:
        """列出目录内容。

        遍历指定目录，用 📁 和 📄 emoji 区分文件夹和文件。

        Args:
            args: 包含 path（可选，默认为当前目录 "."）

        Returns:
            目录内容列表，或错误信息
        """
        path = self._resolve_path(args.get("path", "."))
        if not path.exists():
            return f"Error: Path not found: {args.get('path', '.')}"
        entries = []
        for item in sorted(path.iterdir()):
            prefix = "📁" if item.is_dir() else "📄"  # emoji 区分文件夹和文件
            entries.append(f"{prefix} {item.name}")
        return "\n".join(entries) if entries else "(empty directory)"

    async def _tool_http_get(self, args: dict[str, Any]) -> str:
        """发送 HTTP GET 请求。

        使用 aiohttp 发异步 GET 请求，15 秒超时，响应超过 2 万字符截断。

        Args:
            args: 包含 url（请求地址）

        Returns:
            HTTP 状态码和响应内容
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(args["url"], timeout=aiohttp.ClientTimeout(total=15)) as resp:
                text = await resp.text()
                if len(text) > 20_000:  # 超过 2 万字符截断
                    text = text[:20_000] + "\n\n[...truncated...]"
                return f"[HTTP {resp.status}]\n{text}"

    async def _tool_memory_append(self, args: dict[str, Any]) -> str:
        """向 MEMORY.md 追加记忆条目。

        委托给外部的 Memory 模块处理。如果 Memory 未初始化则报错。

        Args:
            args: 包含 entry（要追加的记忆内容）

        Returns:
            追加成功的提示，或错误信息
        """
        if self._memory:
            self._memory.append_memory(args["entry"])
            return f"Appended to MEMORY.md: {args['entry'][:100]}"
        return "Error: Memory not initialized"

    async def _tool_memory_read(self, args: dict[str, Any]) -> str:
        """读取 workspace 中的文件（通过 Memory 模块）。

        委托给外部的 Memory 模块处理。如果 Memory 未初始化则报错。

        Args:
            args: 包含 filename（文件名，相对于 workspace）

        Returns:
            文件内容，或错误信息
        """
        if self._memory:
            content = self._memory.read_file(args["filename"])
            return content if content else f"File not found: {args['filename']}"
        return "Error: Memory not initialized"

    def _resolve_path(self, path_str: str) -> Path:
        """路径安全守卫 —— 确保所有文件操作都被沙箱化在 workspace 目录内。

        防止 LLM 生成恶意路径（如 ../../etc/passwd），通过 .. 逃逸出 workspace
        读取系统文件。解析后的路径必须是 workspace 的子路径，否则抛出 ValueError。

        Args:
            path_str: 原始路径字符串

        Returns:
            解析后的安全 Path 对象

        Raises:
            ValueError: 如果路径逃逸出 workspace
        """
        p = Path(path_str)
        if p.is_absolute():
            resolved = p.resolve()           # 绝对路径直接解析
        else:
            resolved = (self._workspace / p).resolve()  # 相对路径拼上 workspace

        # 安全检查：解析后的路径必须在 workspace 内部
        ws = self._workspace.resolve()
        try:
            resolved.relative_to(ws)         # 如果不是 ws 的子路径，会抛 ValueError
        except ValueError:
            raise ValueError(f"Path escapes workspace: {path_str}")
        return resolved




