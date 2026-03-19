"""Unit tests for heartbeat.py — active hours, configuration."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from miniclaw.config import AgentDef, HeartbeatConfig
from miniclaw.heartbeat import Heartbeat, HEARTBEAT_OK


class TestActiveHours:
    def _make_heartbeat_with_hours(self, start: str, end: str):
        agent = MagicMock()
        agent.agent_def = AgentDef(
            heartbeat=HeartbeatConfig(
                active_hours_start=start,
                active_hours_end=end,
            )
        )
        return Heartbeat(agent=agent)

    def test_within_normal_hours(self, monkeypatch):
        hb = self._make_heartbeat_with_hours("08:00", "22:00")
        mock_now = datetime(2026, 3, 5, 12, 0, 0)
        monkeypatch.setattr("miniclaw.heartbeat.datetime", type("MockDT", (), {
            "now": staticmethod(lambda: mock_now),
        }))
        assert hb._is_active_hours() is True

    def test_outside_normal_hours(self, monkeypatch):
        hb = self._make_heartbeat_with_hours("08:00", "22:00")
        mock_now = datetime(2026, 3, 5, 23, 30, 0)
        monkeypatch.setattr("miniclaw.heartbeat.datetime", type("MockDT", (), {
            "now": staticmethod(lambda: mock_now),
        }))
        assert hb._is_active_hours() is False

    def test_midnight_crossing_active(self, monkeypatch):
        hb = self._make_heartbeat_with_hours("22:00", "02:00")
        mock_now = datetime(2026, 3, 5, 23, 0, 0)
        monkeypatch.setattr("miniclaw.heartbeat.datetime", type("MockDT", (), {
            "now": staticmethod(lambda: mock_now),
        }))
        assert hb._is_active_hours() is True

    def test_midnight_crossing_active_after(self, monkeypatch):
        hb = self._make_heartbeat_with_hours("22:00", "02:00")
        mock_now = datetime(2026, 3, 6, 1, 0, 0)
        monkeypatch.setattr("miniclaw.heartbeat.datetime", type("MockDT", (), {
            "now": staticmethod(lambda: mock_now),
        }))
        assert hb._is_active_hours() is True

    def test_midnight_crossing_inactive(self, monkeypatch):
        hb = self._make_heartbeat_with_hours("22:00", "02:00")
        mock_now = datetime(2026, 3, 5, 15, 0, 0)
        monkeypatch.setattr("miniclaw.heartbeat.datetime", type("MockDT", (), {
            "now": staticmethod(lambda: mock_now),
        }))
        assert hb._is_active_hours() is False

    def test_invalid_hours_returns_true(self, monkeypatch):
        hb = self._make_heartbeat_with_hours("invalid", "format")
        assert hb._is_active_hours() is True  # fallback: always active

    def test_heartbeat_ok_constant(self):
        assert HEARTBEAT_OK == "HEARTBEAT_OK"

    def test_default_interval(self):
        agent = MagicMock()
        hb = Heartbeat(agent=agent, interval_minutes=30)
        assert hb.interval == 1800

    def test_custom_interval(self):
        agent = MagicMock()
        hb = Heartbeat(agent=agent, interval_minutes=5)
        assert hb.interval == 300
