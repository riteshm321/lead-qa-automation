from core.errors import friendly_error


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
