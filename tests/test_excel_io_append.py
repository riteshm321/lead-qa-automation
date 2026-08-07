import openpyxl
import pandas as pd

from core.excel_io import append_leads
from core.models import FieldMapping


def _make_accumulated_workbook(path: str) -> None:
    wb = openpyxl.Workbook()
    lookup = wb.active
    lookup.title = "Lookup"
    lookup.append(["CID", "Name"])
    lookup.append([100, "Campaign A"])
    lookup.append([200, "Campaign B"])

    accumulated = wb.create_sheet("Accumulated")
    accumulated.append(["Date", "CID", "Campaign Name", "Comment", "emailaddress", "firstname", "lastname", "company"])
    accumulated.append(["2026-01-01", 100, "=VLOOKUP(B2,Lookup!A:B,2,0)", "Delivered", "a@x.com", "A", "B", "X"])

    refund = wb.create_sheet("Refund")
    refund.append(["Date", "CID", "Campaign Name", "Comment", "emailaddress", "firstname", "lastname", "company", "Reason"])

    wb.save(path)


def _field_mapping() -> FieldMapping:
    return FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                         company="company", cid="CID")


def test_append_leads_to_accumulated_fills_by_header_and_shifts_formula(tmp_path):
    path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_workbook(path)

    leads_df = pd.DataFrame([
        {"CID": 200, "emailaddress": "c@y.com", "firstname": "C", "lastname": "D", "company": "Y"},
    ])

    append_leads(path, "Accumulated", leads_df, _field_mapping(), run_date="2026-08-08")

    wb = openpyxl.load_workbook(path)
    ws = wb["Accumulated"]

    assert ws.max_row == 3
    new_row = {cell.value for cell in ws[1]}
    assert new_row == {"Date", "CID", "Campaign Name", "Comment", "emailaddress", "firstname", "lastname", "company"}

    values = {ws.cell(row=1, column=c).value: ws.cell(row=3, column=c).value for c in range(1, 9)}
    assert values["Date"] == "2026-08-08"
    assert values["CID"] == 200
    assert values["Campaign Name"] == "=VLOOKUP(B3,Lookup!A:B,2,0)"
    assert values["Comment"] is None
    assert values["emailaddress"] == "c@y.com"
    assert values["firstname"] == "C"
    assert values["lastname"] == "D"
    assert values["company"] == "Y"


def test_append_leads_to_refund_fills_reason_column(tmp_path):
    path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_workbook(path)

    leads_df = pd.DataFrame([
        {"CID": 200, "emailaddress": "c@y.com", "firstname": "C", "lastname": "D", "company": "Y"},
    ], index=[42])

    append_leads(path, "Refund", leads_df, _field_mapping(), run_date="2026-08-08",
                 reasons={42: "Exclusion - domain; TAL - not found"})

    wb = openpyxl.load_workbook(path)
    ws = wb["Refund"]
    values = {ws.cell(row=1, column=c).value: ws.cell(row=2, column=c).value for c in range(1, 10)}
    assert values["Reason"] == "Exclusion - domain; TAL - not found"
    assert values["CID"] == 200
