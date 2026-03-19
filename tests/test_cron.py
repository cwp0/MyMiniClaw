"""Unit tests for cron.py — schedule matching, job management."""

from datetime import datetime, timedelta

import pytest

from miniclaw.cron import CronJob, CronScheduler


class TestCronJobSchedule:
    """Test _should_run logic without actually running any agent."""

    def _make_scheduler(self):
        """Create a scheduler with a mock agent (we only test scheduling logic)."""
        class MockAgent:
            pass
        return CronScheduler(MockAgent())

    def test_interval_first_run(self):
        scheduler = self._make_scheduler()
        job = CronJob(name="test", schedule="*/15", prompt="test")
        now = datetime(2026, 3, 5, 10, 0, 0)
        assert scheduler._should_run(job, now) is True

    def test_interval_not_yet(self):
        scheduler = self._make_scheduler()
        job = CronJob(name="test", schedule="*/15", prompt="test")
        job.last_run = datetime(2026, 3, 5, 10, 0, 0)
        now = datetime(2026, 3, 5, 10, 10, 0)  # only 10 min passed
        assert scheduler._should_run(job, now) is False

    def test_interval_ready(self):
        scheduler = self._make_scheduler()
        job = CronJob(name="test", schedule="*/15", prompt="test")
        job.last_run = datetime(2026, 3, 5, 10, 0, 0)
        now = datetime(2026, 3, 5, 10, 15, 0)
        assert scheduler._should_run(job, now) is True

    def test_daily_match(self):
        scheduler = self._make_scheduler()
        job = CronJob(name="daily", schedule="09:00", prompt="report")
        now = datetime(2026, 3, 5, 9, 0, 0)
        assert scheduler._should_run(job, now) is True

    def test_daily_no_match_wrong_time(self):
        scheduler = self._make_scheduler()
        job = CronJob(name="daily", schedule="09:00", prompt="report")
        now = datetime(2026, 3, 5, 10, 0, 0)
        assert scheduler._should_run(job, now) is False

    def test_daily_already_ran_today(self):
        scheduler = self._make_scheduler()
        job = CronJob(name="daily", schedule="09:00", prompt="report")
        job.last_run = datetime(2026, 3, 5, 9, 0, 0)
        now = datetime(2026, 3, 5, 9, 0, 30)
        assert scheduler._should_run(job, now) is False

    def test_daily_new_day(self):
        scheduler = self._make_scheduler()
        job = CronJob(name="daily", schedule="09:00", prompt="report")
        job.last_run = datetime(2026, 3, 4, 9, 0, 0)
        now = datetime(2026, 3, 5, 9, 0, 0)
        assert scheduler._should_run(job, now) is True

    def test_invalid_schedule(self):
        scheduler = self._make_scheduler()
        job = CronJob(name="bad", schedule="invalid", prompt="test")
        now = datetime(2026, 3, 5, 10, 0, 0)
        assert scheduler._should_run(job, now) is False

    def test_invalid_interval(self):
        scheduler = self._make_scheduler()
        job = CronJob(name="bad", schedule="*/abc", prompt="test")
        now = datetime(2026, 3, 5, 10, 0, 0)
        assert scheduler._should_run(job, now) is False

    def test_disabled_job(self):
        scheduler = self._make_scheduler()
        job = CronJob(name="off", schedule="*/1", prompt="test", enabled=False)
        # _should_run itself doesn't check enabled; _check_jobs does
        assert scheduler._should_run(job, datetime.now()) is True


class TestCronSchedulerManagement:
    def _make_scheduler(self):
        class MockAgent:
            pass
        return CronScheduler(MockAgent())

    def test_add_job(self):
        scheduler = self._make_scheduler()
        scheduler.add_job(CronJob(name="j1", schedule="09:00", prompt="test"))
        assert len(scheduler._jobs) == 1

    def test_list_jobs(self):
        scheduler = self._make_scheduler()
        scheduler.add_job(CronJob(name="j1", schedule="09:00", prompt="p1"))
        scheduler.add_job(CronJob(name="j2", schedule="*/30", prompt="p2"))
        jobs = scheduler.list_jobs()
        assert len(jobs) == 2
        assert jobs[0]["name"] == "j1"
        assert jobs[1]["schedule"] == "*/30"

    def test_list_jobs_empty(self):
        scheduler = self._make_scheduler()
        assert scheduler.list_jobs() == []

    def test_job_default_values(self):
        job = CronJob(name="test", schedule="09:00", prompt="do it")
        assert job.enabled is True
        assert job.last_run is None
