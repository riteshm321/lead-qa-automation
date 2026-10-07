import faulthandler
import os
import sys
import threading
import time
import urllib.request
import webbrowser

_PROTOBUF_IMPL_ENV = "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"


def _use_pure_python_protobuf(environ=os.environ) -> None:
    # Root cause of the "app closes by itself while idle" bug: the packaged
    # exe repeatedly died with a native access violation (0xc0000005) inside
    # protobuf's upb C extension (google/_upb/_message.pyd, same fault
    # offset every time -- see the Windows Application event log, "Faulting
    # module name: _message.pyd"). protobuf 5.29's C extension predates
    # Python 3.14 and crashes there, typically while objects are being
    # garbage-collected / sessions torn down in the background, i.e. with
    # nobody clicking anything. A native crash kills the process outright
    # (no Python traceback, nothing in app.log), which is why the console
    # window just vanishes. Streamlit is the only protobuf user here and its
    # messages are small (dataframes travel as opaque Arrow bytes), so the
    # pure-Python backend costs nothing noticeable and removes the crash.
    #
    # This MUST run before anything imports google.protobuf -- the backend
    # is chosen once, at first import -- hence its place above the
    # streamlit import below. setdefault() so the variable can still be
    # overridden from outside for diagnosis.
    environ.setdefault(_PROTOBUF_IMPL_ENV, "python")


_use_pure_python_protobuf()

from streamlit.web import cli as stcli  # noqa: E402  (must follow the protobuf backend choice above)

from core.resources import resource_path as _resource_path  # noqa: E402

# Kept open for the life of the process: faulthandler writes to it from a
# signal/exception handler and needs a live file descriptor.
_crash_log_file = None


def _enable_crash_log(log_dir: str = "logs") -> str | None:
    """Dump a Python traceback of every thread to logs/crash.log if the
    process dies from a native fault (access violation, etc.).

    Native crashes bypass Python's exception handling entirely -- before
    this, they left no trace anywhere except the Windows event log, and the
    console window (the only place a traceback could have been printed)
    closes the instant the process dies. Best-effort: never blocks startup.
    """
    global _crash_log_file
    try:
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, "crash.log")
        f = open(path, "a", encoding="utf-8")
        f.write(f"\n--- process {os.getpid()} started {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        f.flush()
        faulthandler.enable(file=f, all_threads=True)
        _crash_log_file = f
        return path
    except Exception:
        return None


def _log(level: str, msg: str, *args) -> None:
    # Imported lazily: core.app_logging opens logs/app.log relative to the
    # current directory, which is only correct after _chdir_to_app_folder().
    try:
        from core.app_logging import get_logger
        getattr(get_logger(), level)(msg, *args)
    except Exception:
        pass


def _guard_streamlit_thread_state() -> None:
    """Recover from Streamlit losing its per-run thread state mid-run.

    Seen once in the packaged exe: the Home page failed on st.title with
    "RuntimeError: FragmentThreadState not initialized" right after
    configure_page() had rendered fine on the same script thread. It could
    not be reproduced in development, so the root cause is still unknown.
    Rather than show the user a broken page, re-seed the state for the
    current page when (and only when) this happens on a live script-run
    thread, and log the stack so the cause can be traced if it recurs.
    Anything else (no script context, another thread) still raises exactly
    as before, since Streamlit itself relies on that RuntimeError.
    """
    from streamlit.runtime.scriptrunner_utils import script_run_context as src

    thread_state = src.ThreadState
    if getattr(thread_state, "_lead_qa_guarded", False):
        return
    original_get = thread_state.get

    def _guarded_get():
        try:
            return original_get()
        except RuntimeError:
            ctx = src.get_script_run_ctx(suppress_warning=True)
            if ctx is None or getattr(ctx, "_main_thread_ident", None) != threading.get_ident():
                raise
            thread_state.initialize(active_script_hash=ctx.page_script_hash)
            import traceback
            _log("warning", "Recovered lost Streamlit thread state (page hash %s):\n%s",
                 ctx.page_script_hash, "".join(traceback.format_stack(limit=25)))
            return original_get()

    thread_state.get = staticmethod(_guarded_get)
    thread_state._lead_qa_guarded = True


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


def _sync_bundled_theme_config(app_data: str) -> None:
    # Streamlit discovers .streamlit/config.toml relative to the CURRENT
    # WORKING DIRECTORY, which the chdir below points at this per-user data
    # folder instead of the bundled resources - without this, the packaged
    # exe silently falls back to Streamlit's own default theme instead of
    # ours. Unlike aliases (user-editable data, copied once), this is
    # app-owned configuration, so it's always overwritten to pick up
    # branding changes from a newer build rather than "copy only if missing".
    src = _resource_path(os.path.join(".streamlit", "config.toml"))
    if os.path.isfile(src):
        import shutil
        dest_dir = os.path.join(app_data, ".streamlit")
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(src, os.path.join(dest_dir, "config.toml"))


def _chdir_to_app_folder() -> None:
    # So "clients/", "aliases/" (relative paths used elsewhere in the app)
    # resolve to a stable per-user folder, not the PyInstaller-managed exe
    # folder (which gets wiped on every rebuild) and not the temp
    # extraction folder (that's sys._MEIPASS, read-only, code only).
    if getattr(sys, "frozen", False):
        app_data = _app_data_dir()
        os.makedirs(app_data, exist_ok=True)
        _bootstrap_bundled_aliases(app_data)
        _sync_bundled_theme_config(app_data)
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
    # listening here" - done BEFORE starting our own server, so a
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
            # Almost certainly our own previous instance, still running -
            # binding our own server to this port would fail with an
            # unhandled OSError that kills the whole process (daemon
            # threads included) before it ever gets a chance to open a
            # browser tab. Just reuse the existing window instead.
            webbrowser.open(url)
            return 0

        _enable_crash_log()
        from google.protobuf.internal import api_implementation
        _log("info", "App starting (pid %s, protobuf backend: %s)", os.getpid(), api_implementation.Type())

        threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()
        _guard_streamlit_thread_state()

        sys.argv = [
            "streamlit", "run", _resource_path("Summary.py"),
            "--server.port", port,
            "--server.headless", "true",
            "--global.developmentMode=false",
        ]
        try:
            code = stcli.main()
        except SystemExit as exc:
            # stcli.main() is a click command and normally ends via
            # SystemExit. Getting here at all means the server shut down
            # gracefully -- the only triggers for that are a console
            # control event (Ctrl+C / Ctrl+Break in this window, Windows
            # shutdown/logoff) or a startup failure such as the port being
            # taken. (The sidebar's Quit App logs its own line and exits
            # via os._exit, and native crashes go to logs/crash.log.)
            _log("warning", "Streamlit server stopped (exit code %s): console Ctrl+C/Ctrl+Break, system shutdown, or a startup failure", exc.code)
            raise
        _log("warning", "Streamlit server stopped (exit code %s)", code)
        return code
    except Exception:
        # Anything else that stops the app from starting at all (a
        # permission error creating the per-user data folder, a corrupted
        # install, etc.) - print a clear banner ahead of the traceback
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
