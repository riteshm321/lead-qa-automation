from unittest.mock import patch, MagicMock

import pytest

from core.google_sheets_client import GoogleSheetsError, read_sheet_headers, append_rows


def test_read_sheet_headers_returns_row_1_values():
    mock_worksheet = MagicMock()
    mock_worksheet.row_values.return_value = ["First Name", "Last Name", "Work Email"]
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_spreadsheet

    with patch("core.google_sheets_client.gspread.service_account", return_value=mock_client):
        headers = read_sheet_headers("fake_key.json", "sheet123", "Sheet1")

    assert headers == ["First Name", "Last Name", "Work Email"]
    mock_client.open_by_key.assert_called_once_with("sheet123")
    mock_spreadsheet.worksheet.assert_called_once_with("Sheet1")


def test_read_sheet_headers_raises_google_sheets_error_when_key_file_missing():
    with patch("core.google_sheets_client.gspread.service_account", side_effect=FileNotFoundError("no such file")):
        with pytest.raises(GoogleSheetsError, match="key"):
            read_sheet_headers("missing.json", "sheet123", "Sheet1")


def test_append_rows_calls_append_rows_with_user_entered_and_matching_header_order():
    mock_worksheet = MagicMock()
    mock_worksheet.row_values.return_value = ["First Name", "Work Email"]
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_spreadsheet

    with patch("core.google_sheets_client.gspread.service_account", return_value=mock_client):
        count = append_rows("fake_key.json", "sheet123", "Sheet1", [
            {"First Name": "A", "Work Email": "a@x.com"},
            {"First Name": "B", "Work Email": "b@x.com"},
        ])

    assert count == 2
    args, kwargs = mock_worksheet.append_rows.call_args
    assert args[0] == [["A", "a@x.com"], ["B", "b@x.com"]]
    assert kwargs["value_input_option"] == "USER_ENTERED"


def test_append_rows_defaults_to_preserving_existing_rows():
    # clear_existing defaults to False -- a second run against the same
    # Sheet must add new leads after the existing ones, never wipe them.
    mock_worksheet = MagicMock()
    mock_worksheet.row_values.return_value = ["First Name", "Work Email"]
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_spreadsheet

    with patch("core.google_sheets_client.gspread.service_account", return_value=mock_client):
        append_rows("fake_key.json", "sheet123", "Sheet1", [{"First Name": "A", "Work Email": "a@x.com"}])

    mock_worksheet.batch_clear.assert_not_called()
    mock_worksheet.append_rows.assert_called_once()


def test_append_rows_clear_existing_wipes_data_rows_before_appending():
    mock_worksheet = MagicMock()
    mock_worksheet.row_values.return_value = ["First Name", "Work Email"]
    mock_worksheet.row_count = 500
    mock_worksheet.col_count = 2
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_spreadsheet

    with patch("core.google_sheets_client.gspread.service_account", return_value=mock_client):
        count = append_rows(
            "fake_key.json", "sheet123", "Sheet1",
            [{"First Name": "A", "Work Email": "a@x.com"}], clear_existing=True,
        )

    assert count == 1
    mock_worksheet.batch_clear.assert_called_once_with(["A2:B500"])
    # The clear must happen before the append, not after -- otherwise a
    # clear_existing run would wipe out the very rows it just wrote.
    method_names = [c[0] for c in mock_worksheet.method_calls]
    assert method_names.index("batch_clear") < method_names.index("append_rows")


def test_append_rows_clear_existing_with_no_new_rows_still_clears():
    # A client might use clear_existing to reset a Sheet even on a run
    # with zero valid leads -- the clear must not be skipped just because
    # there's nothing new to append.
    mock_worksheet = MagicMock()
    mock_worksheet.row_values.return_value = ["First Name"]
    mock_worksheet.row_count = 100
    mock_worksheet.col_count = 1
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_spreadsheet

    with patch("core.google_sheets_client.gspread.service_account", return_value=mock_client):
        count = append_rows("fake_key.json", "sheet123", "Sheet1", [], clear_existing=True)

    assert count == 0
    mock_worksheet.batch_clear.assert_called_once_with(["A2:A100"])
    mock_worksheet.append_rows.assert_not_called()


def test_append_rows_raises_google_sheets_error_on_api_failure():
    mock_worksheet = MagicMock()
    mock_worksheet.row_values.return_value = ["First Name"]
    mock_worksheet.append_rows.side_effect = Exception("API quota exceeded")
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_spreadsheet

    with patch("core.google_sheets_client.gspread.service_account", return_value=mock_client):
        with pytest.raises(GoogleSheetsError, match="API quota exceeded"):
            append_rows("fake_key.json", "sheet123", "Sheet1", [{"First Name": "A"}])
