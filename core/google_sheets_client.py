import gspread


class GoogleSheetsError(Exception):
    """Raised for any failure reading from or writing to a Google Sheet --
    a missing/invalid service-account key file, or any Sheets API error."""


def _open_worksheet(key_path: str, sheet_id: str, worksheet_name: str):
    try:
        client = gspread.service_account(filename=key_path)
    except Exception as exc:
        raise GoogleSheetsError(
            f"Couldn't authenticate with the Google Sheets service-account key at "
            f"\"{key_path}\": {exc}"
        ) from exc
    try:
        spreadsheet = client.open_by_key(sheet_id)
        return spreadsheet.worksheet(worksheet_name)
    except Exception as exc:
        raise GoogleSheetsError(
            f"Couldn't open Sheet \"{sheet_id}\" (tab \"{worksheet_name}\"): {exc}"
        ) from exc


def read_sheet_headers(key_path: str, sheet_id: str, worksheet_name: str) -> list[str]:
    """Reads row 1 of the given Sheet tab live -- used both for the
    Client Setup mapping-preview UI and for resolving write-time column
    order, so a Sheet's headers changing between setup and a later run
    is picked up automatically.
    """
    worksheet = _open_worksheet(key_path, sheet_id, worksheet_name)
    try:
        return worksheet.row_values(1)
    except Exception as exc:
        raise GoogleSheetsError(f"Couldn't read headers from Sheet \"{sheet_id}\": {exc}") from exc


def append_rows(key_path: str, sheet_id: str, worksheet_name: str, rows: list[dict[str, str]]) -> int:
    """Appends each row (already resolved to {header: value} by the
    caller, via core.excel_io.resolve_lead_template_rules +
    _resolve_passthrough_columns) after the Sheet's last real row, using
    the Sheets API's own native append -- no manual "find the next empty
    row" bookkeeping needed, unlike the Excel writer. value_input_option
    is USER_ENTERED so a date string is recognized as a real Sheets date
    value, not left as plain text, matching how append_leads' xlsx branch
    requires a genuine date value rather than text.

    Raises GoogleSheetsError on any failure -- a lead this function
    believes it sent is never silently dropped.
    """
    if not rows:
        return 0
    worksheet = _open_worksheet(key_path, sheet_id, worksheet_name)
    try:
        headers = worksheet.row_values(1)
        values = [[row.get(header, "") for header in headers] for row in rows]
        worksheet.append_rows(values, value_input_option="USER_ENTERED")
        return len(rows)
    except Exception as exc:
        raise GoogleSheetsError(f"Failed to append {len(rows)} lead(s) to Sheet \"{sheet_id}\": {exc}") from exc
