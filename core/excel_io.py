import datetime
import shutil
from pathlib import Path

import openpyxl
import pandas as pd
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter

from core.models import FieldMapping


def list_sheet_names(path: str) -> list[str]:
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        return wb.sheetnames
    finally:
        wb.close()


def read_sheet_as_dataframe(path: str, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet_name)


def backup_file(path: str) -> str:
    source = Path(path)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = source.with_name(f"{source.stem}_backup_{timestamp}{source.suffix}")
    shutil.copy2(source, backup_path)
    return str(backup_path)


def require_columns(df: pd.DataFrame, columns: list[str], file_label: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(
            f"'{file_label}' is missing expected column(s): {', '.join(missing)}. "
            f"Found columns: {', '.join(str(c) for c in df.columns)}"
        )


_FIELD_SYNONYMS = {
    "email": ["email", "emailaddress", "email address"],
    "first_name": ["firstname", "first name"],
    "last_name": ["lastname", "last name"],
    "company": ["company", "companyname", "company name"],
    "cid": ["cid"],
}


def _resolve_field_attr(header_norm: str) -> str | None:
    for attr, synonyms in _FIELD_SYNONYMS.items():
        if header_norm in synonyms:
            return attr
    return None


def append_leads(
    accumulated_path: str,
    tab_name: str,
    leads_df: pd.DataFrame,
    field_mapping: FieldMapping,
    run_date: str,
    reasons: dict[int, str] | None = None,
) -> None:
    wb = openpyxl.load_workbook(accumulated_path)
    ws = wb[tab_name]

    headers = [cell.value for cell in ws[1]]
    lead_headers_norm = {str(h).strip().lower(): h for h in leads_df.columns}

    has_reason_column = any(h is not None and str(h).strip().lower() == "reason" for h in headers)
    if reasons and not has_reason_column:
        reason_col_idx = len(headers) + 1
        ws.cell(row=1, column=reason_col_idx, value="Reason")
        headers.append("Reason")

    formula_template: dict[str, tuple[str, str]] = {}
    if ws.max_row >= 2:
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=2, column=col_idx)
            if isinstance(cell.value, str) and cell.value.startswith("="):
                formula_template[header] = (cell.value, cell.coordinate)

    next_row = ws.max_row + 1
    for row_offset, (idx, lead_row) in enumerate(leads_df.iterrows()):
        excel_row = next_row + row_offset
        for col_idx, header in enumerate(headers, start=1):
            if header is None:
                continue
            header_norm = str(header).strip().lower()
            cell = ws.cell(row=excel_row, column=col_idx)

            if header_norm == "date":
                cell.value = run_date
            elif header in formula_template:
                formula, origin_ref = formula_template[header]
                col_letter = get_column_letter(col_idx)
                cell.value = Translator(formula, origin=origin_ref).translate_formula(f"{col_letter}{excel_row}")
            elif header_norm in ("comment", "status"):
                cell.value = None
            elif header_norm == "reason":
                cell.value = (reasons or {}).get(idx, "")
            else:
                attr = _resolve_field_attr(header_norm)
                if attr:
                    source_col = getattr(field_mapping, attr)
                    cell.value = lead_row.get(source_col, "")
                elif header_norm in lead_headers_norm:
                    cell.value = lead_row.get(lead_headers_norm[header_norm], "")
                else:
                    cell.value = None

    wb.save(accumulated_path)
