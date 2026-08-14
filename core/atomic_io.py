import json
import os
import tempfile


def atomic_write_json(path: str, data) -> None:
    # Write to a temp file in the same directory, then atomically replace
    # the target with it. Readers (including OneDrive's own sync scans)
    # never see a half-written file, and a crash mid-write leaves the
    # original file untouched instead of corrupted.
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
