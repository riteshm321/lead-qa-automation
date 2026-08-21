import os
import sys
import threading
import urllib.request
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

    for _ in range(60):
        try:
            urllib.request.urlopen(url, timeout=1)
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(0.5)
    webbrowser.open(url)


def _port_already_serving(url: str) -> bool:
    # A quick, synchronous check for "is this app (or anything) already
    # listening here" — done BEFORE starting our own server, so a
    # double-launch can cleanly reuse the already-running instance's
    # window instead of racing Streamlit's own bind attempt.
    try:
        urllib.request.urlopen(url, timeout=1)
        return True
    except Exception:
        return False


def main() -> int:
    try:
        _chdir_to_app_folder()

        port = "8501"
        url = f"http://localhost:{port}"

        if _port_already_serving(url):
            # Almost certainly our own previous instance, still running —
            # binding our own server to this port would fail with an
            # unhandled OSError that kills the whole process (daemon
            # threads included) before it ever gets a chance to open a
            # browser tab. Just reuse the existing window instead.
            webbrowser.open(url)
            return 0

        threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()

        sys.argv = [
            "streamlit", "run", _resource_path("Summary.py"),
            "--server.port", port,
            "--server.headless", "true",
            "--global.developmentMode=false",
        ]
        return stcli.main()
    except Exception:
        # Anything else that stops the app from starting at all (a
        # permission error creating the per-user data folder, a corrupted
        # install, etc.) — print a clear banner ahead of the traceback
        # (this exe runs with a console window) instead of a bare stack
        # trace with no context, then report failure so a caller/wrapper
        # script can detect it.
        import traceback
        print("\n" + "=" * 70)
        print("Lead QA Automation failed to start.")
        print("If this keeps happening, check Task Manager for a stuck")
        print("LeadQAAutomation.exe process and end it, then try again.")
        print("=" * 70 + "\n")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
