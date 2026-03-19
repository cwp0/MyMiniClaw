"""Unit tests for config.py — configuration loading and provider resolution."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from miniclaw.config import (
    BrainConfig,
    Config,
    AgentDef,
    HeartbeatConfig,
    CronJobConfig,
    PROVIDER_DEFAULTS,
)


class TestBrainConfig:
    def test_default_values(self):
        cfg = BrainConfig()
        assert cfg.provider == "dashscope"
        assert cfg.model == "qwen-plus"
        assert cfg.api_key is None
        assert cfg.base_url is None
        assert cfg.max_tokens == 4096
        assert cfg.temperature == 0.7

    def test_resolve_api_key_from_field(self):
        cfg = BrainConfig(api_key="test-key")
        assert cfg.resolve_api_key() == "test-key"

    def test_resolve_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "env-key")
        cfg = BrainConfig(provider="dashscope")
        assert cfg.resolve_api_key() == "env-key"

    def test_resolve_api_key_missing_raises(self, monkeypatch):
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        cfg = BrainConfig(provider="dashscope")
        with pytest.raises(ValueError, match="No API key"):
            cfg.resolve_api_key()

    def test_resolve_api_key_anthropic_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")
        cfg = BrainConfig(provider="anthropic")
        assert cfg.resolve_api_key() == "ant-key"

    def test_resolve_api_key_openai_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "oai-key")
        cfg = BrainConfig(provider="openai")
        assert cfg.resolve_api_key() == "oai-key"

    def test_resolve_base_url_from_field(self):
        cfg = BrainConfig(base_url="http://custom.url/v1")
        assert cfg.resolve_base_url() == "http://custom.url/v1"

    def test_resolve_base_url_from_defaults(self):
        cfg = BrainConfig(provider="dashscope")
        assert cfg.resolve_base_url() == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_resolve_base_url_anthropic_none(self):
        cfg = BrainConfig(provider="anthropic")
        assert cfg.resolve_base_url() is None

    def test_resolve_base_url_dashscope_coding(self):
        cfg = BrainConfig(provider="dashscope-coding")
        assert cfg.resolve_base_url() == "https://coding.dashscope.aliyuncs.com/v1"

    def test_unknown_provider_env_fallback_missing(self, monkeypatch):
        monkeypatch.delenv("CUSTOM_API_KEY", raising=False)
        cfg = BrainConfig(provider="custom")
        with pytest.raises(ValueError, match="CUSTOM_API_KEY"):
            cfg.resolve_api_key()

    def test_unknown_provider_env_fallback_present(self, monkeypatch):
        monkeypatch.setenv("CUSTOM_API_KEY", "custom-key")
        cfg = BrainConfig(provider="custom")
        assert cfg.resolve_api_key() == "custom-key"

    def test_field_api_key_takes_priority_over_env(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "env-key")
        cfg = BrainConfig(api_key="field-key")
        assert cfg.resolve_api_key() == "field-key"


class TestProviderDefaults:
    def test_all_providers_have_env_var(self):
        for provider, defaults in PROVIDER_DEFAULTS.items():
            assert "env_var" in defaults, f"{provider} missing env_var"
            assert "model" in defaults, f"{provider} missing model"

    def test_dashscope_coding_has_base_url(self):
        assert PROVIDER_DEFAULTS["dashscope-coding"]["base_url"] is not None

    def test_anthropic_no_base_url(self):
        assert PROVIDER_DEFAULTS["anthropic"]["base_url"] is None


class TestConfig:
    def test_load_defaults(self, tmp_path):
        cfg = Config.load(tmp_path / "nonexistent.yaml")
        assert "main" in cfg.agents
        assert cfg.agents["main"].brain.provider == "dashscope"
        assert cfg.max_context_chars == 100_000

    def test_load_from_yaml(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "workspace": str(tmp_path / "ws"),
            "max_context_chars": 50_000,
            "agents": {
                "main": {
                    "brain": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 8192,
                    },
                    "heartbeat": {
                        "enabled": False,
                        "interval_minutes": 15,
                    },
                    "max_spawn_depth": 3,
                },
                "helper": {
                    "workspace": str(tmp_path / "helper-ws"),
                    "brain": {"provider": "openai", "model": "gpt-4o"},
                    "max_spawn_depth": 0,
                },
            },
        }))

        cfg = Config.load(config_path)

        assert cfg.max_context_chars == 50_000
        assert cfg.workspace == tmp_path / "ws"
        assert cfg.agents["main"].brain.provider == "anthropic"
        assert cfg.agents["main"].brain.model == "claude-sonnet-4-20250514"
        assert cfg.agents["main"].brain.max_tokens == 8192
        assert cfg.agents["main"].heartbeat.enabled is False
        assert cfg.agents["main"].heartbeat.interval_minutes == 15
        assert cfg.agents["main"].max_spawn_depth == 3

        assert "helper" in cfg.agents
        assert cfg.agents["helper"].brain.provider == "openai"
        assert cfg.agents["helper"].max_spawn_depth == 0

    def test_load_cron_jobs(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "agents": {
                "main": {
                    "brain": {"provider": "dashscope"},
                    "cron": [
                        {"name": "daily", "schedule": "09:00", "prompt": "Report"},
                        {"name": "check", "schedule": "*/30", "prompt": "Check news"},
                    ],
                },
            },
        }))

        cfg = Config.load(config_path)
        assert len(cfg.agents["main"].cron_jobs) == 2
        assert cfg.agents["main"].cron_jobs[0].name == "daily"
        assert cfg.agents["main"].cron_jobs[0].schedule == "09:00"
        assert cfg.agents["main"].cron_jobs[1].schedule == "*/30"

    def test_get_agent_existing(self):
        cfg = Config()
        agent = cfg.get_agent("main")
        assert agent.id == "main"

    def test_get_agent_missing_raises(self):
        cfg = Config()
        with pytest.raises(ValueError, match="not defined"):
            cfg.get_agent("nonexistent")

    def test_agent_workspace_main(self, tmp_path):
        cfg = Config(workspace=tmp_path / "ws")
        assert cfg.agent_workspace("main") == tmp_path / "ws"

    def test_agent_workspace_other(self, tmp_path):
        cfg = Config(workspace=tmp_path / "ws")
        cfg.agents["helper"] = AgentDef(id="helper")
        assert cfg.agent_workspace("helper") == tmp_path / "workspace-helper"

    def test_agent_workspace_custom(self, tmp_path):
        cfg = Config()
        cfg.agents["custom"] = AgentDef(id="custom", workspace="~/my-ws")
        ws = cfg.agent_workspace("custom")
        assert str(ws).endswith("my-ws")

    def test_save_default(self, tmp_path):
        cfg = Config(config_dir=tmp_path)
        saved = cfg.save_default()
        assert saved.exists()
        with open(saved) as f:
            data = yaml.safe_load(f)
        assert "agents" in data
        assert "main" in data["agents"]
