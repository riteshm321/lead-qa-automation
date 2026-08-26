import os

from core.app_settings import save_app_settings
from core.activity_tracker import (
    record_process_completed, load_all_activity, get_time_baseline, save_time_baseline,
    compute_time_saved_summary, format_minutes,
)

_ROOT = "shared_root"


def _configure_shared_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = str(tmp_path / _ROOT)
    os.makedirs(root, exist_ok=True)
    save_app_settings({"shared_root_dir": root})
    return root


def test_record_process_completed_is_a_noop_without_a_shared_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    record_process_completed("ritesh")
    assert load_all_activity() == {}


def test_record_process_completed_creates_and_increments_a_per_user_file(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)

    record_process_completed("ritesh")
    record_process_completed("ritesh")
    record_process_completed("colleague")

    activity = load_all_activity()
    assert activity["ritesh"]["process_count"] == 2
    assert activity["colleague"]["process_count"] == 1
    assert "last_updated" in activity["ritesh"]


def test_record_process_completed_users_never_collide(tmp_path, monkeypatch):
    # Two different users' counters live in separate files -- one user's
    # increments never touch another's, unlike a single shared counter file
    # that both would have to read-modify-write (a real race under OneDrive
    # sync, per this app's own documented Settings-page caveat).
    _configure_shared_root(tmp_path, monkeypatch)
    for _ in range(5):
        record_process_completed("alice")
    for _ in range(3):
        record_process_completed("bob")

    activity = load_all_activity()
    assert activity["alice"]["process_count"] == 5
    assert activity["bob"]["process_count"] == 3


def test_get_time_baseline_defaults_when_unset(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    assert get_time_baseline() == {"automation_minutes": 10, "manual_minutes": 40}


def test_save_and_get_time_baseline_round_trips(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    save_time_baseline(automation_minutes=15, manual_minutes=45)
    assert get_time_baseline() == {"automation_minutes": 15, "manual_minutes": 45}


def test_compute_time_saved_summary_combines_all_users_with_current_baseline(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    record_process_completed("alice")
    record_process_completed("alice")
    record_process_completed("bob")
    save_time_baseline(automation_minutes=10, manual_minutes=30)

    summary = compute_time_saved_summary()

    assert summary["total_processes"] == 3
    assert summary["total_automation_minutes"] == 30
    assert summary["total_manual_minutes"] == 90
    assert summary["total_saved_minutes"] == 60
    assert summary["per_user"]["alice"]["process_count"] == 2
    assert summary["baseline"] == {"automation_minutes": 10, "manual_minutes": 30}


def test_compute_time_saved_summary_reflects_baseline_changes_live(tmp_path, monkeypatch):
    # Editing the baseline in Settings must immediately change the
    # displayed time-saved figure for ALL past processes, not just future
    # ones -- nothing about the per-process saved time is frozen at
    # record_process_completed() time.
    _configure_shared_root(tmp_path, monkeypatch)
    record_process_completed("alice")
    save_time_baseline(automation_minutes=10, manual_minutes=30)
    before = compute_time_saved_summary()["total_saved_minutes"]

    save_time_baseline(automation_minutes=5, manual_minutes=60)
    after = compute_time_saved_summary()["total_saved_minutes"]

    assert before == 20
    assert after == 55


def test_format_minutes_shows_hours_and_minutes():
    assert format_minutes(20) == "20m"
    assert format_minutes(60) == "1h"
    assert format_minutes(90) == "1h 30m"
    assert format_minutes(605) == "10h 5m"
