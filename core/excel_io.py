import datetime
import shutil
from pathlib import Path

import openpyxl
import pandas as pd


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
