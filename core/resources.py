import os

# core/resources.py's own directory is always one level under the repo
# root in dev, and under PyInstaller's bundled resource folder (sys._MEIPASS)
# in the packaged exe — resolving from __file__ rather than the current
# working directory means this works in both, and also under tests that
# deliberately chdir() elsewhere for filesystem isolation (a plain
# os.path.abspath(".")-based fallback broke under exactly that case).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(rel_path: str) -> str:
    """Resolve a path to a bundled, read-only resource (e.g. a logo image
    or Summary.py itself) that works the same regardless of the process's
    current working directory."""
    return os.path.join(_REPO_ROOT, rel_path)
