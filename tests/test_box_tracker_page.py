import os

import openpyxl
import pandas as pd
from streamlit.testing.v1 import AppTest

from core.app_settings import get_clients_dir
from core.models import ClientProfile, FieldMapping, BoxTrackerConfig, ComplexAccountConfig
from core.profile_store import save_profile

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "5_Box_Tracker.py")


def _make_accumulated(path: str, rows: list[dict]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Email", "First", "Last", "Company", "CID", "Status", "LOB"])
    for row in rows:
        ws.append([row["Email"], row["First"], row["Last"], row["Company"], row["CID"],
                    row.get("Status", ""), row.get("LOB", "")])
    wb.create_sheet("Refund").append(["Email", "First", "Last", "Company", "CID", "Status", "Refund Reason"])
    wb.save(path)


def _make_mirror(path: str) -> None:
    wb = openpyxl.Workbook()
    approval = wb.active
    approval.title = "Approval Sheet"
    approval.append(["Company Name", "Market", "Date", "Segment", "Job Title"])
    pacing = wb.create_sheet("Pacing")
    pacing.append(["Funding Source", "Publisher", "Country", "Segment", "Campaign", "Week of 7", ""])
    pacing.append([None, None, None, None, None, "P", "D"])
    pacing.append(["Cash", "Madison Logic", "IN", "Select-T", "Bob", 18, 0])
    pacing.append(["Cash", "Madison Logic", "IN", "Named", "CXO", 0, 0])
    pacing["B13"] = "Bob"
    pacing["A14"], pacing["B14"] = "Pending", 20
    pacing["A15"], pacing["B15"] = "Delivered", 7
    pacing["A16"], pacing["B16"] = "Diff", 13
    wb.create_sheet("Response Details").append(
        ["Publisher Name", "source_site", "Market", "Company", "UUCID", "Project Code",
         "Uploaded Date", "Campaign Name", "Segment", "Job Title", "Contact Type", "State",
         "Campaign Type", "Asset Title"])
    wb.save(path)


def _make_lead_template(path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Template"
    ws.append(["Email", "First", "Last", "Company", "CID", "micro_audience", "Industry"])
    wb.save(path)


def _save_profile(acc_path, mirror_path, cid_campaign_map=None, cid_lead_template_path=None,
                   pacing_skipped_campaigns=None):
    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="IBM APAC", accumulated_report_path=acc_path, field_mapping=fm,
        complex_account=ComplexAccountConfig(enabled=True),
        box_tracker=BoxTrackerConfig(
            enabled=True, mirror_workbook_path=mirror_path,
            cid_campaign_map=cid_campaign_map or {"118741": "Bob"},
            cid_lead_template_path=cid_lead_template_path or {},
            pacing_skipped_campaigns=pacing_skipped_campaigns or [],
        ),
    )
    save_profile(profile, get_clients_dir())
    return profile


def test_pick_and_send_writes_approval_sheet_mirror_and_sets_pacing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": f"lead{i}@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741"}
        for i in range(20)
    ])
    _make_mirror(mirror_path)
    _save_profile(acc_path, mirror_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.selectbox[0].set_value("IBM APAC").run()

    pick_button = next(b for b in at.button if b.label == "Pick leads and send for approval")
    pick_button.click().run()

    assert not at.exception

    wb = openpyxl.load_workbook(mirror_path)
    approval_ws = wb["Approval Sheet"]
    assert approval_ws.max_row == 1 + 18  # header + (13 diff + 5 buffer)

    pacing_ws = wb["Pacing"]
    assert pacing_ws.cell(row=3, column=7).value == 18  # "D" column under "Week of 7"

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    sent_count = (accumulated_df["Status"].astype(str).str.startswith("Sent for Approval")).sum()
    assert sent_count == 18


def test_pick_and_send_reports_shortfall(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741"},
    ])
    _make_mirror(mirror_path)
    _save_profile(acc_path, mirror_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.selectbox[0].set_value("IBM APAC").run()
    at.button(key="pick_and_send_button").click().run()

    assert not at.exception
    assert any("118741" in w.value and "short" in w.value.lower() for w in at.warning)


def test_pick_and_send_takes_all_leads_and_skips_pacing_for_skipped_campaign(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": f"lead{i}@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118742"}
        for i in range(7)
    ])
    _make_mirror(mirror_path)
    _save_profile(
        acc_path, mirror_path, cid_campaign_map={"118742": "CXO"},
        pacing_skipped_campaigns=["CXO"],
    )

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.selectbox[0].set_value("IBM APAC").run()
    at.button(key="pick_and_send_button").click().run()

    assert not at.exception
    assert not at.warning  # no shortfall for an uncapped campaign

    wb = openpyxl.load_workbook(mirror_path)
    assert wb["Approval Sheet"].max_row == 1 + 7  # all 7 leads, no diff+buffer cap

    pacing_ws = wb["Pacing"]
    # CXO's row (row 4) "D" column under "Week of 7" must be untouched (still 0).
    assert pacing_ws.cell(row=4, column=7).value == 0


def test_write_cleared_leads_to_lead_template_fills_micro_audience_and_industry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    template_path = str(tmp_path / "bob_template.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741",
         "Status": "Sent for Approval - 07-Sep"},
    ])
    _make_mirror(mirror_path)
    _make_lead_template(template_path)
    _save_profile(acc_path, mirror_path, cid_lead_template_path={"118741": template_path})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.selectbox[0].set_value("IBM APAC").run()

    clear_checkbox = next(cb for cb in at.checkbox if cb.key == "clear_lead1@x.com")
    clear_checkbox.set_value(True).run()

    write_button = next(b for b in at.button if b.key == "write_lead_template_button")
    write_button.click().run()

    assert not at.exception

    template_df = pd.read_excel(template_path, sheet_name="Template")
    assert template_df.loc[0, "Email"] == "lead1@x.com"
    assert template_df.loc[0, "micro_audience"] == "Platform_SWE"  # CID 118741 = Bob
    assert template_df.loc[0, "Industry"] == "All"

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    status = accumulated_df.loc[accumulated_df["Email"] == "lead1@x.com", "Status"].iloc[0]
    assert status.startswith("Cleared for Upload")


def test_write_cleared_leads_copies_lob_for_wxo_cids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    template_path = str(tmp_path / "wxo_template.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "119750",
         "Status": "Sent for Approval - 07-Sep", "LOB": "Cloud Infra"},
    ])
    _make_mirror(mirror_path)
    _make_lead_template(template_path)
    _save_profile(acc_path, mirror_path, cid_lead_template_path={"119750": template_path})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.selectbox[0].set_value("IBM APAC").run()
    at.checkbox(key="clear_lead1@x.com").set_value(True).run()
    at.button(key="write_lead_template_button").click().run()

    assert not at.exception
    template_df = pd.read_excel(template_path, sheet_name="Template")
    assert template_df.loc[0, "micro_audience"] == "Cloud Infra"


def test_write_cleared_leads_warns_when_no_template_path_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741",
         "Status": "Sent for Approval - 07-Sep"},
    ])
    _make_mirror(mirror_path)
    _save_profile(acc_path, mirror_path)  # no cid_lead_template_path configured

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.selectbox[0].set_value("IBM APAC").run()
    at.checkbox(key="clear_lead1@x.com").set_value(True).run()
    at.button(key="write_lead_template_button").click().run()

    assert not at.exception
    assert any("118741" in w.value for w in at.warning)
    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    status = accumulated_df.loc[accumulated_df["Email"] == "lead1@x.com", "Status"].iloc[0]
    assert status.startswith("Sent for Approval")  # left untouched


def test_upload_reconciliation_moves_rejected_to_refund_and_logs_accepted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741",
         "Status": "Cleared for Upload - 07-Sep"},
        {"Email": "lead2@x.com", "First": "F", "Last": "L", "Company": "Y", "CID": "118741",
         "Status": "Cleared for Upload - 07-Sep"},
    ])
    _make_mirror(mirror_path)
    _save_profile(acc_path, mirror_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.selectbox[0].set_value("IBM APAC").run()

    reject_checkbox = next(cb for cb in at.checkbox if cb.key == "reject_lead2@x.com")
    reject_checkbox.set_value(True).run()
    reason_input = next(t for t in at.text_input if t.key == "reject_reason_lead2@x.com")
    reason_input.set_value("Portal duplicate").run()

    reconcile_button = next(b for b in at.button if b.key == "reconcile_upload_button")
    reconcile_button.click().run()

    assert not at.exception

    refund_df = pd.read_excel(acc_path, sheet_name="Refund")
    assert "lead2@x.com" in refund_df["Email"].values
    assert refund_df.loc[refund_df["Email"] == "lead2@x.com", "Refund Reason"].iloc[0] == "Portal duplicate"

    response_wb = openpyxl.load_workbook(mirror_path)
    response_ws = response_wb["Response Details"]
    company_col_values = [c.value for c in response_ws["D"]]  # Company is column D
    assert "X" in company_col_values  # lead1 (accepted) logged
    assert "Y" not in company_col_values  # lead2 (rejected) not logged

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    status_by_email = dict(zip(accumulated_df["Email"], accumulated_df["Status"]))
    assert status_by_email["lead1@x.com"].startswith("Accepted - Uploaded")
    assert status_by_email["lead2@x.com"].startswith("Rejected - Refunded")


def test_upload_reconciliation_requires_a_reason_for_rejected_leads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741",
         "Status": "Cleared for Upload - 07-Sep"},
    ])
    _make_mirror(mirror_path)
    _save_profile(acc_path, mirror_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.selectbox[0].set_value("IBM APAC").run()

    reject_checkbox = next(cb for cb in at.checkbox if cb.key == "reject_lead1@x.com")
    reject_checkbox.set_value(True).run()

    reconcile_button = next(b for b in at.button if b.key == "reconcile_upload_button")
    reconcile_button.click().run()

    assert not at.exception
    assert any("lead1@x.com" in e.value for e in at.error)
    refund_df = pd.read_excel(acc_path, sheet_name="Refund")
    assert refund_df.empty
