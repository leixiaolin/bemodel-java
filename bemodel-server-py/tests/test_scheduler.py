from datetime import datetime
from threading import Event
from zoneinfo import ZoneInfo
import pytest
from bemodel.core import scheduler as module
from bemodel.notice.services import InspectService


@pytest.mark.parametrize("expression,expected", [
    ("0 0/30 * * * *", "2026-09-18T10:30:00+08:00"),
    ("0 0 12 * * SUN", "2026-09-20T12:00:00+08:00"),
    ("0 0 12 ? * 7", "2026-09-20T12:00:00+08:00"),
    ("0 0 12 * * MON-FRI", "2026-09-18T12:00:00+08:00"),
])
def test_spring_cron_next_fire(expression, expected):
    now = datetime(2026, 9, 18, 10, 14, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert module.cron_trigger(expression).get_next_fire_time(None, now).isoformat() == expected


def test_disabled_scheduler(monkeypatch):
    monkeypatch.setattr(module.settings, "disable_scheduler", True)
    assert module.start_scheduler() is None


def test_ontology_analysis_job_uses_local_lock_and_relaxed_instances(monkeypatch):
    monkeypatch.setattr(module.settings, "disable_scheduler", False)
    scheduler = module.start_scheduler()
    try:
        jobs = [job for job in scheduler.get_jobs() if job.func.__name__ == "ontology_analysis"]
        assert len(jobs) == 1
        assert jobs[0].max_instances == 10
    finally:
        scheduler.shutdown(wait=False)


def test_actual_cron_retries_after_inspection_failure(monkeypatch, caplog):
    monkeypatch.setattr(module.settings, "disable_scheduler", False)
    monkeypatch.setattr(module.settings, "inspect_cron", "* * * * * *")
    completed = Event()
    calls = []
    closed = []
    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            closed.append(True)
    def inspect(self):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("test inspection failure")
        completed.set()
    monkeypatch.setattr(module, "Session", FakeSession)
    monkeypatch.setattr(InspectService, "run_all", inspect)
    scheduler = module.start_scheduler()
    try:
        assert completed.wait(6), "Cron did not retry inspection after the first failure"
    finally:
        scheduler.shutdown(wait=True)
    assert len(calls) >= 2 and len(closed) == len(calls)
    assert "test inspection failure" in caplog.text
