import os

from core.app_settings import save_app_settings
from core.activity_tracker import (
    record_process_completed, load_all_activity, compute_time_saved_summary, format_minutes,
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
    record_process_completed("ritesh", 3.0)
    assert load_all_activity() == {}


def test_record_process_completed_creates_and_increments_a_per_user_file(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)

    record_process_completed("ritesh", 3.0)
    record_process_completed("ritesh", 2.0)
    record_process_completed("colleague", 1.0)

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
        record_process_completed("alice", 2.0)
    for _ in range(3):
        record_process_completed("bob", 2.0)

    activity = load_all_activity()
    assert activity["alice"]["process_count"] == 5
    assert activity["bob"]["process_count"] == 3


def test_record_process_completed_adds_15_minutes_manual_for_a_plain_client(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    record_process_completed("ritesh", 3.0, is_complex_account=False)

    activity = load_all_activity()["ritesh"]
    assert activity["total_automated_minutes"] == 3.0
    assert activity["total_manual_minutes"] == 18.0


def test_record_process_completed_adds_30_minutes_manual_for_a_complex_account_client(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    record_process_completed("ritesh", 3.0, is_complex_account=True)

    activity = load_all_activity()["ritesh"]
    assert activity["total_automated_minutes"] == 3.0
    assert activity["total_manual_minutes"] == 33.0


def test_record_process_completed_accumulates_minutes_across_calls(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    record_process_completed("ritesh", 3.0, is_complex_account=False)
    record_process_completed("ritesh", 2.0, is_complex_account=True)

    activity = load_all_activity()["ritesh"]
    assert activity["process_count"] == 2
    assert activity["total_automated_minutes"] == 5.0
    assert activity["total_manual_minutes"] == 18.0 + 32.0


def test_compute_time_saved_summary_combines_all_users(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    record_process_completed("alice", 3.0, is_complex_account=False)
    record_process_completed("alice", 5.0, is_complex_account=True)
    record_process_completed("bob", 1.0, is_complex_account=False)

    summary = compute_time_saved_summary()

    assert summary["total_processes"] == 3
    assert summary["total_automated_minutes"] == 9.0
    assert summary["total_manual_minutes"] == 18.0 + 35.0 + 16.0
    assert summary["total_saved_minutes"] == summary["total_manual_minutes"] - 9.0
    assert summary["per_user"]["alice"]["process_count"] == 2


def test_load_all_activity_migrates_a_legacy_count_only_record(tmp_path, monkeypatch):
    # Records from before measured-time tracking existed only stored
    # process_count -- these must be backfilled with the old fixed baseline
    # (10 min automated / 40 min manual per process) rather than showing as
    # 0 minutes despite a non-zero process count.
    root = _configure_shared_root(tmp_path, monkeypatch)
    users_dir = os.path.join(root, "activity", "users")
    os.makedirs(users_dir, exist_ok=True)
    import json
    with open(os.path.join(users_dir, "legacy-user.json"), "w", encoding="utf-8") as f:
        json.dump({"process_count": 2, "last_updated": "2026-01-01T00:00:00"}, f)

    activity = load_all_activity()

    assert activity["legacy-user"]["total_automated_minutes"] == 20.0
    assert activity["legacy-user"]["total_manual_minutes"] == 80.0

    # The migration must persist -- re-reading must not re-derive from a
    # bare count a second time (it wouldn't matter here since the numbers
    # are the same either way, but the file on disk must actually be updated).
    with open(os.path.join(users_dir, "legacy-user.json"), "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["total_automated_minutes"] == 20.0
    assert on_disk["total_manual_minutes"] == 80.0


def test_load_all_activity_migrates_using_a_custom_legacy_baseline(tmp_path, monkeypatch):
    root = _configure_shared_root(tmp_path, monkeypatch)
    activity_dir = os.path.join(root, "activity")
    users_dir = os.path.join(activity_dir, "users")
    os.makedirs(users_dir, exist_ok=True)
    import json
    with open(os.path.join(activity_dir, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"automation_minutes": 5, "manual_minutes": 25}, f)
    with open(os.path.join(users_dir, "legacy-user.json"), "w", encoding="utf-8") as f:
        json.dump({"process_count": 3, "last_updated": "2026-01-01T00:00:00"}, f)

    activity = load_all_activity()

    assert activity["legacy-user"]["total_automated_minutes"] == 15.0
    assert activity["legacy-user"]["total_manual_minutes"] == 75.0


def test_compute_time_saved_summary_with_no_activity(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    summary = compute_time_saved_summary()

    assert summary["total_processes"] == 0
    assert summary["total_saved_minutes"] == 0
    assert summary["percent_saved"] == 0.0


def test_format_minutes_shows_hours_and_minutes():
    assert format_minutes(20) == "20m"
    assert format_minutes(60) == "1h"
    assert format_minutes(90) == "1h 30m"
    assert format_minutes(605) == "10h 5m"


def test_format_minutes_shows_seconds_under_an_hour():
    assert format_minutes(0.5) == "0m 30s"
    assert format_minutes(29.5) == "29m 30s"
    assert format_minutes(3) == "3m"
