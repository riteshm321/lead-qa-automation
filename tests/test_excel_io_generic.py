import os
import openpyxl
import pytest

from core.excel_io import list_sheet_names, read_sheet_as_dataframe, backup_file, require_columns


def _make_workbook(path: str) -> None:
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Exclusion"
    ws1.append(["Account Name", "Domain"])
    ws1.append(["Adecco UK Ltd", "adecco.co.uk"])
    ws2 = wb.create_sheet("Persona titles ")
    ws2.append(["AUDIENCE : CSUITE"])
    wb.save(path)


def test_list_sheet_names(tmp_path):
    path = str(tmp_path / "exclusion.xlsx")
    _make_workbook(path)
    assert list_sheet_names(path) == ["Exclusion", "Persona titles "]


def test_read_sheet_as_dataframe(tmp_path):
    path = str(tmp_path / "exclusion.xlsx")
    _make_workbook(path)
    df = read_sheet_as_dataframe(path, "Exclusion")
    assert list(df.columns) == ["Account Name", "Domain"]
    assert df.iloc[0]["Domain"] == "adecco.co.uk"


def test_backup_file_creates_timestamped_copy(tmp_path):
    path = str(tmp_path / "accumulated.xlsx")
    _make_workbook(path)

    backup_path = backup_file(path)

    assert os.path.isfile(backup_path)
    assert backup_path != path
    assert "accumulated_backup_" in os.path.basename(backup_path)
    assert list_sheet_names(backup_path) == list_sheet_names(path)


def test_require_columns_passes_when_all_present(tmp_path):
    path = str(tmp_path / "exclusion.xlsx")
    _make_workbook(path)
    df = read_sheet_as_dataframe(path, "Exclusion")

    require_columns(df, ["Account Name", "Domain"], file_label=path)  # should not raise


def test_require_columns_raises_clear_error_naming_file_and_column(tmp_path):
    path = str(tmp_path / "exclusion.xlsx")
    _make_workbook(path)
    df = read_sheet_as_dataframe(path, "Exclusion")

    with pytest.raises(ValueError) as exc_info:
        require_columns(df, ["Account Name", "Email"], file_label=path)

    message = str(exc_info.value)
    assert path in message
    assert "Email" in message
