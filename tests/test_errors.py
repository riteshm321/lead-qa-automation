import logging

from core.errors import friendly_error, render_error


def test_friendly_error_file_not_found():
    message, fix = friendly_error(FileNotFoundError("[Errno 2] No such file or directory: 'x.xlsx'"))
    assert "not found" in message.lower()
    assert fix


def test_friendly_error_permission_denied():
    message, fix = friendly_error(PermissionError("[Errno 13] Permission denied: 'x.xlsx'"))
    assert "couldn't be opened" in message.lower()
    assert "Excel" in fix


def test_friendly_error_missing_columns_keeps_original_detail():
    exc = ValueError("'x.xlsx' is missing expected column(s): Email. Found columns: A, B")
    message, fix = friendly_error(exc)
    assert "required column is missing" in message.lower()
    assert "Email" in fix


def test_friendly_error_key_error():
    message, fix = friendly_error(KeyError("Domain"))
    assert "missing expected data" in message.lower()
    assert fix


def test_friendly_error_old_xls_format():
    # Real openpyxl exception when a client's Lead Template/Accumulated
    # Report path points at a legacy .xls file — this tool only reads/writes
    # .xlsx, since append_leads relies on openpyxl throughout (style/formula
    # preservation) which can't open .xls at all.
    exc = ValueError(
        "openpyxl does not support the old .xls file format, please use xlrd to read this file, "
        "or convert it to the more recent .xlsx file format."
    )
    message, fix = friendly_error(exc)
    assert ".xls" in message
    assert "Save As" in fix and ".xlsx" in fix


def test_friendly_error_win_error_3_path_too_long():
    exc = FileNotFoundError("[WinError 3] The system cannot find the path specified: 'C:\\\\very\\\\long\\\\path.xlsx'")
    message, fix = friendly_error(exc)
    assert "couldn't find part of that file path" in message.lower()
    assert "260" in fix or "too long" in fix.lower()


def test_friendly_error_unrecognized_falls_back_to_raw_text():
    exc = RuntimeError("something unusual happened")
    message, fix = friendly_error(exc)
    assert "something unusual happened" in message
    assert fix == ""


def test_render_error_logs_the_full_exception(tmp_path, monkeypatch, caplog):
    # Regression test: render_error() used to convert an exception into a
    # short friendly message and discard the original entirely — if a user
    # reported "the tool did something wrong," there was no way to find out
    # what actually happened. It must now leave a diagnosable trail.
    monkeypatch.chdir(tmp_path)
    with caplog.at_level(logging.ERROR, logger="lead_qa_automation"):
        try:
            raise ValueError("something specific broke")
        except ValueError as exc:
            render_error(exc)

    assert any("something specific broke" in r.message for r in caplog.records)
    assert any(r.exc_info is not None for r in caplog.records)
