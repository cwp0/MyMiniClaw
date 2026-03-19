"""Shared fixtures for MiniClaw unit tests."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace with default contract files."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "SOUL.md").write_text("# Soul\nYou are a test agent.\n")
    (ws / "IDENTITY.md").write_text("# Identity\nName: TestBot\n")
    (ws / "MEMORY.md").write_text("# Memory\n")
    (ws / "HEARTBEAT.md").write_text("# Heartbeat\n- Check if tests pass\n")
    skills_dir = ws / "skills"
    skills_dir.mkdir()
    return ws


@pytest.fixture
def sample_skill_file(tmp_workspace):
    """Create a sample skill Markdown file."""
    skill_path = tmp_workspace / "skills" / "greeting.md"
    skill_path.write_text(
        "---\n"
        "name: greeting\n"
        "description: Greets the user\n"
        "triggers:\n"
        "  - type: keyword\n"
        "    pattern: hello\n"
        "  - type: regex\n"
        '    pattern: "hi\\\\s+there"\n'
        "tools:\n"
        "  - file_read\n"
        "---\n"
        "You are a friendly greeting bot.\n"
    )
    return skill_path


@pytest.fixture
def sample_skill_string_tools(tmp_workspace):
    """Create a skill with tools as a string (edge case)."""
    skill_path = tmp_workspace / "skills" / "simple.md"
    skill_path.write_text(
        "---\n"
        "name: simple\n"
        "description: Simple skill\n"
        "triggers:\n"
        "  - hello\n"
        "tools: file_read\n"
        "---\n"
        "Do something.\n"
    )
    return skill_path
