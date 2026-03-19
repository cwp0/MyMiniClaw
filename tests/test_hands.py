"""Unit tests for hands.py — tool registration, execution, path safety."""

import pytest

from miniclaw.hands import Hands, BUILTIN_TOOL_SCHEMAS
from miniclaw.memory import Memory


class TestHandsPathSafety:
    def test_resolve_relative_path(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        resolved = hands._resolve_path("SOUL.md")
        assert resolved == (tmp_workspace / "SOUL.md").resolve()

    def test_resolve_absolute_path_in_workspace(self, tmp_workspace):
        target = tmp_workspace / "test.txt"
        target.write_text("x")
        hands = Hands(tmp_workspace)
        resolved = hands._resolve_path(str(target))
        assert resolved == target.resolve()

    def test_path_traversal_blocked(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        with pytest.raises(ValueError, match="escapes workspace"):
            hands._resolve_path("../../etc/passwd")

    def test_path_traversal_absolute_blocked(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        with pytest.raises(ValueError, match="escapes workspace"):
            hands._resolve_path("/etc/passwd")

    def test_dotdot_within_workspace_ok(self, tmp_workspace):
        sub = tmp_workspace / "sub"
        sub.mkdir()
        hands = Hands(tmp_workspace)
        resolved = hands._resolve_path("sub/../SOUL.md")
        assert resolved == (tmp_workspace / "SOUL.md").resolve()


class TestHandsToolRegistration:
    def test_builtin_schemas_count(self):
        assert len(BUILTIN_TOOL_SCHEMAS) == 7

    def test_builtin_schema_names(self):
        names = {s["name"] for s in BUILTIN_TOOL_SCHEMAS}
        expected = {"shell_exec", "file_read", "file_write", "file_list",
                    "http_get", "memory_append", "memory_read"}
        assert names == expected

    def test_get_all_tool_schemas(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        schemas = hands.get_tool_schemas()
        assert len(schemas) == 7

    def test_get_filtered_schemas(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        schemas = hands.get_tool_schemas(["file_read", "file_write"])
        assert len(schemas) == 2
        names = {s["name"] for s in schemas}
        assert names == {"file_read", "file_write"}

    def test_get_schemas_wildcard(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        schemas = hands.get_tool_schemas(["*"])
        assert len(schemas) == 7

    def test_register_custom_tool(self, tmp_workspace):
        hands = Hands(tmp_workspace)

        async def custom_handler(args):
            return "custom result"

        hands.register_tool("custom_tool", custom_handler, {
            "name": "custom_tool",
            "description": "test",
            "parameters": {"type": "object", "properties": {}},
        })
        schemas = hands.get_tool_schemas()
        assert len(schemas) == 8
        names = {s["name"] for s in schemas}
        assert "custom_tool" in names


@pytest.mark.asyncio
class TestHandsToolExecution:
    async def test_file_read(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        result = await hands.execute("file_read", {"path": "SOUL.md"})
        assert "test agent" in result

    async def test_file_read_not_found(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        result = await hands.execute("file_read", {"path": "nonexistent.md"})
        assert "Error" in result or "not found" in result.lower()

    async def test_file_write_and_read(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        await hands.execute("file_write", {"path": "test.txt", "content": "hello"})
        result = await hands.execute("file_read", {"path": "test.txt"})
        assert "hello" in result

    async def test_file_list(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        result = await hands.execute("file_list", {"path": "."})
        assert "SOUL.md" in result

    async def test_shell_exec(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        result = await hands.execute("shell_exec", {"command": "echo hello"})
        assert "hello" in result
        assert "exit code: 0" in result

    async def test_shell_exec_timeout(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        result = await hands.execute("shell_exec", {"command": "sleep 10", "timeout": 1})
        assert "timed out" in result.lower()

    async def test_unknown_tool(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        result = await hands.execute("nonexistent_tool", {})
        assert "Unknown tool" in result

    async def test_memory_append_and_read(self, tmp_workspace):
        mem = Memory(tmp_workspace)
        hands = Hands(tmp_workspace, memory=mem)
        await hands.execute("memory_append", {"entry": "test entry"})
        result = await hands.execute("memory_read", {"filename": "MEMORY.md"})
        assert "test entry" in result

    async def test_memory_tools_without_memory(self, tmp_workspace):
        hands = Hands(tmp_workspace, memory=None)
        result = await hands.execute("memory_append", {"entry": "x"})
        assert "Error" in result

    async def test_custom_tool_execution(self, tmp_workspace):
        hands = Hands(tmp_workspace)

        async def echo(args):
            return f"echo: {args['text']}"

        hands.register_tool("echo", echo, {
            "name": "echo", "description": "test",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
        })
        result = await hands.execute("echo", {"text": "world"})
        assert result == "echo: world"

    async def test_file_write_creates_directories(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        await hands.execute("file_write", {"path": "sub/dir/file.txt", "content": "nested"})
        assert (tmp_workspace / "sub" / "dir" / "file.txt").read_text() == "nested"

    async def test_path_traversal_in_file_read(self, tmp_workspace):
        hands = Hands(tmp_workspace)
        result = await hands.execute("file_read", {"path": "../../etc/passwd"})
        assert "Error" in result
