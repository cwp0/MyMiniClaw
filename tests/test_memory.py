"""Unit tests for memory.py — workspace contract files and bootstrap assembly."""

from pathlib import Path

import pytest

from miniclaw.memory import Memory


class TestMemory:
    def test_read_existing_file(self, tmp_workspace):
        mem = Memory(tmp_workspace)
        content = mem.read_file("SOUL.md")
        assert "test agent" in content

    def test_read_nonexistent_file(self, tmp_workspace):
        mem = Memory(tmp_workspace)
        assert mem.read_file("NONEXISTENT.md") is None

    def test_write_file(self, tmp_workspace):
        mem = Memory(tmp_workspace)
        mem.write_file("NEW.md", "new content")
        assert (tmp_workspace / "NEW.md").read_text() == "new content"

    def test_append_memory(self, tmp_workspace):
        mem = Memory(tmp_workspace)
        mem.append_memory("Learned something new")
        content = (tmp_workspace / "MEMORY.md").read_text()
        assert "Learned something new" in content
        assert "# Memory" in content  # original content preserved

    def test_append_memory_multiple(self, tmp_workspace):
        mem = Memory(tmp_workspace)
        mem.append_memory("Entry 1")
        mem.append_memory("Entry 2")
        content = (tmp_workspace / "MEMORY.md").read_text()
        assert "Entry 1" in content
        assert "Entry 2" in content

    def test_create_defaults_no_overwrite(self, tmp_workspace):
        mem = Memory(tmp_workspace)
        original = (tmp_workspace / "SOUL.md").read_text()
        mem.create_defaults()
        assert (tmp_workspace / "SOUL.md").read_text() == original

    def test_create_defaults_creates_missing(self, tmp_path):
        ws = tmp_path / "empty_workspace"
        ws.mkdir()
        mem = Memory(ws)
        mem.create_defaults()
        assert (ws / "SOUL.md").exists()
        assert (ws / "IDENTITY.md").exists()
        assert (ws / "MEMORY.md").exists()
        assert (ws / "HEARTBEAT.md").exists()

    def test_assemble_bootstrap_includes_all(self, tmp_workspace):
        mem = Memory(tmp_workspace)
        bootstrap = mem.assemble_bootstrap()
        assert "SOUL.md" in bootstrap
        assert "IDENTITY.md" in bootstrap
        assert "MEMORY.md" in bootstrap
        assert "test agent" in bootstrap
        assert "TestBot" in bootstrap

    def test_assemble_bootstrap_first_run(self, tmp_workspace):
        (tmp_workspace / "BOOTSTRAP.md").write_text("# Welcome\nFirst run instructions.\n")
        mem = Memory(tmp_workspace)
        first = mem.assemble_bootstrap(first_run=True)
        normal = mem.assemble_bootstrap(first_run=False)
        assert "First run instructions" in first
        assert "First run instructions" not in normal

    def test_assemble_bootstrap_empty_files_skipped(self, tmp_workspace):
        (tmp_workspace / "USER.md").write_text("")
        mem = Memory(tmp_workspace)
        bootstrap = mem.assemble_bootstrap()
        assert "USER.md" not in bootstrap

    def test_list_skills(self, tmp_workspace, sample_skill_file):
        mem = Memory(tmp_workspace)
        skills = mem.list_skills()
        assert len(skills) >= 1
        assert any(str(p).endswith(".md") for p in skills)
