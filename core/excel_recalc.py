import os
import shutil
import tempfile
import threading

_DEFAULT_TIMEOUT_SECONDS = 60


def recalculate_workbook(path: str, timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS) -> str:
    """Force every formula in `path` to recalculate, returning the path to a
    temporary, recalculated copy — the original file is never opened for
    writing and is never modified.

    openpyxl (used everywhere else in this app) never evaluates formulas —
    it only ever reads whatever value Excel itself last cached. A workbook
    this app wrote new rows into (via openpyxl, not Excel) keeps showing
    Excel's *previous* cached formula results — stale, or None/blank if the
    formula was newly added and never opened in real Excel at all — even
    though the underlying data just changed. This drives Excel itself,
    headlessly, to produce a fresh, correct cache.

    Best-effort: returns the original `path` unchanged if pywin32/Excel
    isn't available, or if recalculation fails or exceeds the timeout for
    any reason (a hung/crashed Excel automation, a corrupt file, etc.) —
    callers get back a valid path either way and should treat a returned
    original path as "possibly stale," not as an error to surface.
    """
    try:
        import pythoncom
        import win32com.client
        import win32process
    except ImportError:
        return path

    tmp_dir = tempfile.mkdtemp(prefix="leadqa_recalc_")
    tmp_path = os.path.join(tmp_dir, os.path.basename(path))
    shutil.copy2(path, tmp_path)

    outcome = {"ok": False}
    excel_pid: list[int] = []

    def _worker() -> None:
        pythoncom.CoInitialize()
        app = None
        wb = None
        try:
            # DispatchEx (never GetObject/Dispatch's "reuse a running
            # instance" behavior) guarantees a fresh, isolated Excel
            # instance — never one the user might already have open with
            # unsaved work of their own.
            app = win32com.client.DispatchEx("Excel.Application")
            try:
                excel_pid.append(win32process.GetWindowThreadProcessId(app.Hwnd)[1])
            except Exception:
                pass
            app.Visible = False
            app.DisplayAlerts = False
            app.AskToUpdateLinks = False
            app.EnableEvents = False
            app.ScreenUpdating = False
            try:
                app.AutomationSecurity = 4  # msoAutomationSecurityForceDisable
            except Exception:
                pass  # not settable on every Excel version/context — non-fatal

            wb = app.Workbooks.Open(tmp_path, UpdateLinks=0, ReadOnly=False)
            app.CalculateFullRebuild()
            wb.Save()
            outcome["ok"] = True
        except Exception:
            outcome["ok"] = False
        finally:
            try:
                if wb is not None:
                    wb.Close(SaveChanges=False)
            except Exception:
                pass
            try:
                if app is not None:
                    app.Quit()
            except Exception:
                pass
            del wb
            del app
            pythoncom.CoUninitialize()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout_seconds)

    if thread.is_alive() or not outcome["ok"]:
        if excel_pid:
            _force_kill(excel_pid[0])
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return path

    return tmp_path


def _force_kill(pid: int) -> None:
    # Only reached when graceful Quit() didn't finish in time — kill the
    # *specific* Excel process this call spawned, never a broad "all Excel
    # processes" sweep, so a user's own open Excel windows are never touched.
    try:
        import psutil
        psutil.Process(pid).kill()
    except Exception:
        pass
