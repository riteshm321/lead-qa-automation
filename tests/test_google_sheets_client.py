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
