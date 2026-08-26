import datetime
import json
import os

from core.atomic_io import atomic_write_json
from core.app_settings import get_shared_root_dir

_DEFAULT_AUTOMATION_MINUTES = 10
_DEFAULT_MANUAL_MINUTES = 40


def _activity_dir() -> str:
    root = get_shared_root_dir()
    return os.path.join(root, "activity") if root else ""


def _user_file(username: str) -> str:
    return os.path.join(_activity_dir(), "users", f"{username}.json")


def _baseline_file() -> str:
    return os.path.join(_activity_dir(), "settings.json")


def record_process_completed(username: str) -> None:
    """Increments the logged-in user's completed-client-process counter.

    Call once per successful Finalize/Confirm & Write -- a completed
    write to the Accumulated Report, not just a Run Check click. A no-op
    if no shared team data folder is configured yet (nothing to write
    into, and recording locally would defeat the point of a
    team-visible tracker once the shared folder does get set up).
    """
    root = get_shared_root_dir()
    if not root or not username:
        return
    path = _user_file(username)
    existing = {"process_count": 0}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing["process_count"] = existing.get("process_count", 0) + 1
    existing["last_updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    atomic_write_json(path, existing)


def load_all_activity() -> dict[str, dict]:
    """{username: {"process_count", "last_updated"}} for every user who has
    completed at least one process -- one file per user (see
    record_process_completed) so two people finalizing at nearly the same
    moment on different machines never race on the same file the way a
    single shared counter would under OneDrive's own sync model."""
    users_dir = os.path.join(_activity_dir(), "users") if _activity_dir() else ""
    if not users_dir or not os.path.isdir(users_dir):
        return {}
    activity: dict[str, dict] = {}
    for entry in os.listdir(users_dir):
        if not entry.endswith(".json"):
            continue
        username = entry[: -len(".json")]
        with open(os.path.join(users_dir, entry), "r", encoding="utf-8") as f:
            activity[username] = json.load(f)
    return activity


def get_time_baseline() -> dict:
    path = _baseline_file()
    if not path or not os.path.isfile(path):
        return {"automation_minutes": _DEFAULT_AUTOMATION_MINUTES, "manual_minutes": _DEFAULT_MANUAL_MINUTES}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "automation_minutes": data.get("automation_minutes", _DEFAULT_AUTOMATION_MINUTES),
        "manual_minutes": data.get("manual_minutes", _DEFAULT_MANUAL_MINUTES),
    }


def save_time_baseline(automation_minutes: int, manual_minutes: int) -> None:
    path = _baseline_file()
    if not path:
        return
    atomic_write_json(path, {"automation_minutes": automation_minutes, "manual_minutes": manual_minutes})


def format_minutes(minutes: float) -> str:
    minutes = round(minutes)
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def compute_time_saved_summary() -> dict:
    """Combined totals across every user, computed live from the current
    baseline (see get_time_baseline) -- editing the baseline in Settings
    immediately changes what this reports, past processes included,
    rather than freezing a stale per-process value at record time."""
    activity = load_all_activity()
    baseline = get_time_baseline()
    total_processes = sum(u.get("process_count", 0) for u in activity.values())
    saved_per_process = baseline["manual_minutes"] - baseline["automation_minutes"]
    total_automation_minutes = total_processes * baseline["automation_minutes"]
    total_manual_minutes = total_processes * baseline["manual_minutes"]
    total_saved_minutes = total_processes * saved_per_process
    return {
        "total_processes": total_processes,
        "total_automation_minutes": total_automation_minutes,
        "total_manual_minutes": total_manual_minutes,
        "total_saved_minutes": total_saved_minutes,
        "per_user": activity,
        "baseline": baseline,
    }
