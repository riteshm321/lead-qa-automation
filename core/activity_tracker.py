import datetime
import json
import os

from core.atomic_io import atomic_write_json
from core.app_settings import get_shared_root_dir

# How much longer the same client process is assumed to take by hand than
# it actually took with the tool (measured live, see record_process_completed).
# Complex Account clients carry extra manual review/cross-checking even with
# the tool's help, so they're assumed to save more time than a plain Lead QA
# client -- not because automated time is inflated, but because the manual
# alternative would take that much longer.
_MANUAL_EXTRA_MINUTES = 15
_MANUAL_EXTRA_MINUTES_COMPLEX_ACCOUNT = 30


def _activity_dir() -> str:
    root = get_shared_root_dir()
    return os.path.join(root, "activity") if root else ""


def _user_file(username: str) -> str:
    return os.path.join(_activity_dir(), "users", f"{username}.json")


def record_process_completed(username: str, automated_minutes: float, is_complex_account: bool = False) -> None:
    """Increments the logged-in user's completed-client-process counter and
    accumulates the real, measured time this process took.

    Call once per successful Finalize/Confirm & Write -- a completed write
    to the Accumulated Report, not just a Run Check click. `automated_minutes`
    is the actual elapsed time from that run's Run Check click to this
    Finalize click; the assumed manual-equivalent time is derived from it
    (see _MANUAL_EXTRA_MINUTES above) and stored alongside it, so the
    Time Saved figures reflect real measured work, not a flat guess.

    A no-op if no shared team data folder is configured yet (nothing to
    write into, and recording locally would defeat the point of a
    team-visible tracker once the shared folder does get set up).
    """
    root = get_shared_root_dir()
    if not root or not username:
        return
    extra = _MANUAL_EXTRA_MINUTES_COMPLEX_ACCOUNT if is_complex_account else _MANUAL_EXTRA_MINUTES
    automated_minutes = max(0.0, automated_minutes)
    manual_minutes = automated_minutes + extra

    path = _user_file(username)
    existing = {"process_count": 0, "total_automated_minutes": 0.0, "total_manual_minutes": 0.0}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing["process_count"] = existing.get("process_count", 0) + 1
    existing["total_automated_minutes"] = existing.get("total_automated_minutes", 0.0) + automated_minutes
    existing["total_manual_minutes"] = existing.get("total_manual_minutes", 0.0) + manual_minutes
    existing["last_updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    atomic_write_json(path, existing)


def load_all_activity() -> dict[str, dict]:
    """{username: {"process_count", "total_automated_minutes",
    "total_manual_minutes", "last_updated"}} for every user who has
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


def format_minutes(minutes: float) -> str:
    """Formats a duration for display. Seconds only show up when the total
    is under an hour -- real per-process durations are often well under a
    minute, and "0m" alone would hide that there was any automated time at
    all, but a multi-hour cumulative total doesn't need second-level noise.
    """
    total_seconds = round(minutes * 60)
    hours, remainder = divmod(total_seconds, 3600)
    mins, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    if secs and not mins:
        return f"0m {secs}s"
    if secs:
        return f"{mins}m {secs}s"
    return f"{mins}m"


def compute_time_saved_summary() -> dict:
    """Combined totals across every user, summed directly from each
    process's own measured automated/manual minutes (see
    record_process_completed) -- unlike the old fixed-baseline design,
    there's no separate multiplier to apply here."""
    activity = load_all_activity()
    total_processes = sum(u.get("process_count", 0) for u in activity.values())
    total_automated_minutes = sum(u.get("total_automated_minutes", 0.0) for u in activity.values())
    total_manual_minutes = sum(u.get("total_manual_minutes", 0.0) for u in activity.values())
    total_saved_minutes = total_manual_minutes - total_automated_minutes
    percent_saved = (total_saved_minutes / total_manual_minutes * 100) if total_manual_minutes else 0.0
    return {
        "total_processes": total_processes,
        "total_automated_minutes": total_automated_minutes,
        "total_manual_minutes": total_manual_minutes,
        "total_saved_minutes": total_saved_minutes,
        "percent_saved": percent_saved,
        "per_user": activity,
    }
