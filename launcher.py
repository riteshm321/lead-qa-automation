import os
import sys
import threading
import webbrowser

from streamlit.web import cli as stcli


def _resource_path(rel_path: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, rel_path)


def _app_data_dir() -> str:
    # A per-user folder outside the exe's own install directory. PyInstaller
    # deletes and rebuilds dist/LeadQAAutomation from scratch on every
    # build, so anything written next to the exe (client profiles, saved
    # company aliases) was being destroyed by every rebuild. %LOCALAPPDATA%
    # survives rebuilds and reinstalls.
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "LeadQAAutomation")


def _bootstrap_bundled_aliases(app_data: str) -> None:
    # First run after install: seed the persistent aliases file from the
    # bundled default so users don't start with an empty alias list.
    dest = os.path.join(app_data, "aliases", "company_aliases.json")
    if os.path.isfile(dest):
        return
    src = _resource_path(os.path.join("aliases", "company_aliases.json"))
    if os.path.isfile(src):
        import shutil
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)


def _chdir_to_app_folder() -> None:
    # So "clients/", "aliases/" (relative paths used elsewhere in the app)
    # resolve to a stable per-user folder, not the PyInstaller-managed exe
    # folder (which gets wiped on every rebuild) and not the temp
    # extraction folder (that's sys._MEIPASS, read-only, code only).
    if getattr(sys, "frozen", False):
        app_data = _app_data_dir()
        os.makedirs(app_data, exist_ok=True)
        _bootstrap_bundled_aliases(app_data)
        os.chdir(app_data)


def _open_browser_when_ready(url: str) -> None:
    import time
    import urllib.request

    for _ in range(60):
        try:
            urllib.request.urlopen(url, timeout=1)
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(0.5)
    webbrowser.open(url)


if __name__ == "__main__":
    _chdir_to_app_folder()

    port = "8501"
    url = f"http://localhost:{port}"

    threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()

    sys.argv = [
        "streamlit", "run", _resource_path("Summary.py"),
        "--server.port", port,
        "--server.headless", "true",
        "--global.developmentMode=false",
    ]
    sys.exit(stcli.main())
