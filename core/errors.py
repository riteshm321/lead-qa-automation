import streamlit as st

from core.app_logging import get_logger


def friendly_error(exc: Exception) -> tuple[str, str]:
    """Return (short message, suggested fix) for a caught exception.

    Falls back to the raw exception text with no fix when the error doesn't
    match a known pattern — better a plain message than a wrong guess.
    """
    text = str(exc)

    if "does not support the old .xls file format" in text:
        return ("This file is in the old .xls format, which this tool can't read or write.",
                "Open it in Excel, then File → Save As → pick \"Excel Workbook (*.xlsx)\", and update the "
                "path in Client Setup to point at the new .xlsx file.")

    if "WinError 3" in text:
        return ("Windows couldn't find part of that file path.",
                "This usually means the full path is too long (Windows has a ~260-character limit) — "
                "common with deeply nested OneDrive folders. Try moving the file to a shorter path, "
                "or renaming a parent folder to something shorter.")

    if isinstance(exc, FileNotFoundError) or "No such file or directory" in text:
        return ("File not found.",
                "Check the path is correct, or if it's on OneDrive, open the file once in Explorer/Excel "
                "to make sure it's actually downloaded (not just a cloud placeholder), then try again.")

    if isinstance(exc, PermissionError) or "Permission denied" in text:
        return ("The file couldn't be opened.", "Close it in Excel (or any other program) and try again.")

    if "is missing expected column(s)" in text:
        return ("A required column is missing from a file.", text)

    if "Worksheet" in text and ("does not exist" in text or "not found" in text.lower()):
        return ("The sheet name couldn't be found in the file.",
                "Check the sheet name in Client Setup matches exactly (case-sensitive).")

    if isinstance(exc, KeyError):
        return (f"Missing expected data: {text}.",
                "Check the file's columns match what's configured in Client Setup.")

    if isinstance(exc, ValueError):
        return (text, "")

    return (f"{type(exc).__name__}: {text}", "")


def render_error(exc: Exception) -> None:
    """Show a short, friendly error with a suggested fix when one is known.

    The friendly message deliberately hides the raw exception/traceback
    from the user — but that detail must not simply vanish, or a client
    who reports "the tool did something wrong" leaves no way to find out
    what actually happened. Logging it here, at the one place every
    caught, user-facing error already passes through, means every such
    error leaves a diagnosable trail in logs/app.log without changing
    what the user sees.
    """
    get_logger().exception("Handled error shown to user: %s", exc, exc_info=exc)
    message, fix = friendly_error(exc)
    if fix:
        st.error(f"⚠️ {message}\n\n**Suggested fix:** {fix}")
    else:
        st.error(f"⚠️ {message}")
