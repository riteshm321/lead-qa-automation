import gspread
from gspread.utils import rowcol_to_a1


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


def append_rows(
    key_path: str, sheet_id: str, worksheet_name: str, rows: list[dict[str, str]],
    clear_existing: bool = False,
) -> int:
    """Appends each row (already resolved to {header: value} by the
    caller, via core.excel_io.resolve_lead_template_rules +
    _resolve_passthrough_columns) after the Sheet's last real row, using
    the Sheets API's own native append -- no manual "find the next empty
    row" bookkeeping needed, unlike the Excel writer. value_input_option
    is USER_ENTERED so a date string is recognized as a real Sheets date
    value, not left as plain text, matching how append_leads' xlsx branch
    requires a genuine date value rather than text.

    clear_existing defaults to False: a second run against the same Sheet
    preserves whatever leads are already there and adds the new ones after
    them, same as append_leads' own clear_existing default for Excel. Set
    it to True to wipe every data row (everything below the header) before
    appending -- e.g. for a client who wants each run's Sheet to reflect
    only that run's leads, not an ever-growing accumulation.

    Raises GoogleSheetsError on any failure -- a lead this function
    believes it sent is never silently dropped.
    """
    if not rows and not clear_existing:
        return 0
    worksheet = _open_worksheet(key_path, sheet_id, worksheet_name)
    try:
        headers = worksheet.row_values(1)
        if clear_existing:
            # batch_clear only clears cell VALUES in the given range -- it
            # never deletes/resizes rows or touches formatting, so this
            # can't accidentally remove the header row (start=row 2) or
            # shrink the sheet the way Worksheet.clear() or delete_rows()
            # would.
            end_cell = rowcol_to_a1(max(worksheet.row_count, 2), max(worksheet.col_count, len(headers) or 1))
            worksheet.batch_clear([f"A2:{end_cell}"])
        if rows:
            values = [[row.get(header, "") for header in headers] for row in rows]
            worksheet.append_rows(values, value_input_option="USER_ENTERED")
        return len(rows)
    except Exception as exc:
        raise GoogleSheetsError(f"Failed to append {len(rows)} lead(s) to Sheet \"{sheet_id}\": {exc}") from exc
