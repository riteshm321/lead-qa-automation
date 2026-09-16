import datetime
import os

import openpyxl
import pandas as pd
from streamlit.testing.v1 import AppTest

from core.app_settings import get_clients_dir
from core.box_tracker import current_week_label
from core.models import ClientProfile, FieldMapping, BoxTrackerConfig, ComplexAccountConfig
from core.profile_store import save_profile

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "5_Box_Tracker.py")
# set_pacing_delivered looks up THIS week's column by label -- computing it
# from today's actual date (rather than hardcoding e.g. "Week of 7") keeps
# these tests passing regardless of which day they happen to run on.
_CURRENT_WEEK_LABEL = current_week_label(datetime.date.today())


def _make_accumulated(path: str, rows: list[dict]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Email", "First", "Last", "Company", "CID", "Status", "LOB", "Asset Title", "Country",
               "Project Code", "AMAL ID", "Segment", "2nd Asset OV Code", "Asset", "Second Asset"])
    for row in rows:
        ws.append([row["Email"], row["First"], row["Last"], row["Company"], row["CID"],
                    row.get("Status", ""), row.get("LOB", ""), row.get("Asset Title", ""), row.get("Country", ""),
                    row.get("Project Code", ""), row.get("AMAL ID", ""), row.get("Segment", ""),
                    row.get("2nd Asset OV Code", ""), row.get("Asset", ""), row.get("Second Asset", "")])
    wb.create_sheet("Refund").append(["Email", "First", "Last", "Company", "CID", "Status", "Refund Reason"])
    wb.save(path)


def _make_mirror(path: str) -> None:
    wb = openpyxl.Workbook()
    approval = wb.active
    approval.title = "Approval Sheet"
    approval.append(["Company Name", "Market", "Date", "Segment", "Persona/Industry", "Project Code",
                     "Job Title", "AMAL ID", "Approval"])
    pacing = wb.create_sheet("Pacing")
    pacing.append(["Funding Source", "Publisher", "Country", "Segment", "Campaign", _CURRENT_WEEK_LABEL, ""])
    pacing.append([None, None, None, None, None, "P", "D"])
    pacing.append(["Cash", "Madison Logic", "IN", "Select-T", "Bob", 18, 0])
    pacing.append(["Cash", "Madison Logic", "IN", "Named", "CXO", 0, 0])
    pacing["B13"] = "Bob"
    pacing["A14"], pacing["B14"] = "Pending", 20
    pacing["A15"], pacing["B15"] = "Delivered", 7
    pacing["A16"], pacing["B16"] = "Diff", 13
    response_ws = wb.create_sheet("Response Details")
    response_ws.append([])  # real file's row 1 is blank; headers are row 2
    response_ws.append(
        ["Publisher Name", "source_site", "Market", "Company", "UUCID", "Project Code",
         "Uploaded Date", "Campaign Name", "Segment", "Job Title", "Contact Type", "State",
         "Campaign Type", "Asset Title"])
    wb.save(path)


def _make_lead_template(path: str, existing_rows: list[list] | None = None) -> None:
    # Mirrors the real IBM APAC Lead Template's actual header shape --
    # note there's no CID column at all; AID/NC_*/campaign_code are the
    # same for every row in the file, carried by whatever's already there
    # (even a template/example row with no real lead, per the CXO file).
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "LEAD_TEMPLATE"
    ws.append([
        "AID", "NC_EMAIL_DETAIL", "NC_TELE_DETAIL", "user_transaction_date", "campaign_code",
        "asset_title", "country", "micro_audience", "Industry", "First", "Last", "Email", "Company",
    ])
    for row in (existing_rows or []):
        ws.append(row)
    wb.save(path)


def _save_profile(acc_path, mirror_path, cid_campaign_map=None, cid_lead_template_path=None,
                   pacing_skipped_campaigns=None):
    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="IBM APAC Interactive Avenues Pvt Ltd", accumulated_report_path=acc_path, field_mapping=fm,
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
        {"Email": f"lead{i}@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741",
         "Project Code": "PVLAP", "AMAL ID": "old-id, new-id", "Segment": "SelectT"}
        for i in range(20)
    ])
    _make_mirror(mirror_path)
    _save_profile(acc_path, mirror_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    pick_button = next(b for b in at.button if b.label == "Pick leads and send for approval")
    pick_button.click().run()

    assert not at.exception

    wb = openpyxl.load_workbook(mirror_path)
    approval_ws = wb["Approval Sheet"]
    assert approval_ws.max_row == 1 + 18  # header + (13 diff + 5 buffer)
    headers = [c.value for c in approval_ws[1]]
    row2 = dict(zip(headers, [c.value for c in approval_ws[2]]))
    assert row2["Persona/Industry"] == "Bob"
    assert row2["Project Code"] == "PVLAP"  # passed through from the leadfile
    assert row2["AMAL ID"] == "new-id"      # later of the two comma-separated values
    assert row2["Approval"] is None         # left blank for the client to fill in

    pacing_ws = wb["Pacing"]
    assert pacing_ws.cell(row=3, column=7).value == 18  # "D" column under this week

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
    at.button(key="pick_and_send_button").click().run()

    assert not at.exception
    assert not at.warning  # no shortfall for an uncapped campaign

    wb = openpyxl.load_workbook(mirror_path)
    assert wb["Approval Sheet"].max_row == 1 + 7  # all 7 leads, no diff+buffer cap

    pacing_ws = wb["Pacing"]
    # CXO's row (row 4) "D" column under "Week of 7" must be untouched (still 0).
    assert pacing_ws.cell(row=4, column=7).value == 0


def test_write_cleared_leads_to_lead_template_fills_all_columns_and_wipes_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    template_path = str(tmp_path / "bob_template.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741",
         "Status": "Sent for Approval - 07-Sep", "Asset Title": "Omdia Universe", "Country": "IN",
         "Asset": "Normal Asset", "Second Asset": "Touch 2 Asset"},
    ])
    _make_mirror(mirror_path)
    # An existing lead from a previous cycle -- carries the AID/NC_*/
    # campaign_code every new row must reuse, and must itself be wiped.
    _make_lead_template(template_path, existing_rows=[
        ["L-22SD7", "UC", "UC", "2026-08-20 06:55:41", "PVLAP", "Old Asset", "IN", "Platform_SWE", "All",
         "Old", "Lead", "old.lead@x.com", "Old Co"],
    ])
    _save_profile(acc_path, mirror_path, cid_lead_template_path={"118741": template_path})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    clear_checkbox = next(cb for cb in at.checkbox if cb.label == "Clear lead1@x.com")
    clear_checkbox.set_value(True).run()

    write_button = next(b for b in at.button if b.key == "write_lead_template_button")
    write_button.click().run()

    assert not at.exception

    template_df = pd.read_excel(template_path, sheet_name="LEAD_TEMPLATE")
    assert len(template_df) == 1  # the old lead was wiped, not appended alongside
    row = template_df.iloc[0]
    assert row["Email"] == "lead1@x.com"
    assert row["micro_audience"] == "Platform_SWE"  # CID 118741 = Bob
    assert row["Industry"] == "All"
    assert row["AID"] == "L-22SD7"  # carried over from the old row before it was wiped
    assert row["NC_EMAIL_DETAIL"] == "UC"
    assert row["NC_TELE_DETAIL"] == "UC"
    assert row["campaign_code"] == "PVLAP"
    assert row["asset_title"] == "Touch 2 Asset"  # CID 118741 = Bob = 2T -> Second Asset, not Asset Title
    assert row["country"] == "IN"
    assert str(row["user_transaction_date"]).count(":") == 2  # HH:MM:SS present

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    status = accumulated_df.loc[accumulated_df["Email"] == "lead1@x.com", "Status"].iloc[0]
    assert status.startswith("Cleared for Upload")


def test_write_cleared_leads_uses_accumulated_field_mapping_not_raw_leadfile_mapping(tmp_path, monkeypatch):
    # Regression test for a real bug found in IBM APAC's own data: Company
    # (and, by the same mechanism, any of the other 4 roles) silently wrote
    # blank whenever field_mapping (the RAW LEADFILE's own column names,
    # e.g. "company" lowercase) differed from accumulated_field_mapping
    # (what that role is actually called INSIDE the Accumulated Report,
    # e.g. "Company") -- every DataFrame this page touches comes from the
    # Accumulated Report, never a raw leadfile, so only the latter mapping
    # is ever correct here.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    template_path = str(tmp_path / "bob_template.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "Acme Corp", "CID": "118741",
         "Status": "Sent for Approval - 07-Sep", "Asset Title": "Omdia Universe", "Country": "IN"},
    ])
    _make_mirror(mirror_path)
    _make_lead_template(template_path)

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="company", cid="CID")
    acc_fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="IBM APAC Interactive Avenues Pvt Ltd", accumulated_report_path=acc_path,
        field_mapping=fm, accumulated_field_mapping=acc_fm,
        complex_account=ComplexAccountConfig(enabled=True),
        box_tracker=BoxTrackerConfig(
            enabled=True, mirror_workbook_path=mirror_path,
            cid_campaign_map={"118741": "Bob"}, cid_lead_template_path={"118741": template_path},
        ),
    )
    save_profile(profile, get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    clear_checkbox = next(cb for cb in at.checkbox if cb.label == "Clear lead1@x.com")
    clear_checkbox.set_value(True).run()
    write_button = next(b for b in at.button if b.key == "write_lead_template_button")
    write_button.click().run()

    assert not at.exception
    template_df = pd.read_excel(template_path, sheet_name="LEAD_TEMPLATE")
    assert template_df.iloc[0]["Company"] == "Acme Corp"


def test_manual_marking_hides_blank_leads_from_step_2_until_marked(tmp_path, monkeypatch):
    # A lead the user approved by hand (added straight to the real
    # Approval Sheet themselves, skipping step 1) starts with a blank
    # Status. It must stay hidden from step 2 until explicitly marked via
    # the "I already added these myself" flow, so the guided flow's
    # per-CID Pacing target isn't quietly bypassed by untouched leads.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    template_path = str(tmp_path / "bob_template.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "manual@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741", "Status": ""},
    ])
    _make_mirror(mirror_path)
    _make_lead_template(template_path)
    _save_profile(acc_path, mirror_path, cid_lead_template_path={"118741": template_path})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not any(cb.label == "Clear manual@x.com" for cb in at.checkbox)
    assert any(cb.label == "Mark manual@x.com" for cb in at.checkbox)

    next(cb for cb in at.checkbox if cb.label == "Mark manual@x.com").set_value(True).run()
    at.button(key="mark_manual_button").click().run()

    assert not at.exception
    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    status = accumulated_df.loc[accumulated_df["Email"] == "manual@x.com", "Status"].iloc[0]
    assert status.startswith("Uploaded to Approval Sheet")

    assert any(cb.label == "Clear manual@x.com" for cb in at.checkbox)


def test_manual_marking_handles_two_leads_with_a_blank_email_without_crashing(tmp_path, monkeypatch):
    # Regression test for a real production crash: two blank-Status leads
    # both had a blank email (a genuine data-quality gap in the real
    # Accumulated Report, not a fixture artifact). Email-keyed checkbox
    # keys collapsed both into "manual_" and Streamlit raised
    # StreamlitDuplicateElementKey. Row-index-keyed widgets must handle
    # this instead of crashing the whole page.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "", "First": "F", "Last": "L", "Company": "X", "CID": "118741", "Status": ""},
        {"Email": "", "First": "F", "Last": "L", "Company": "Y", "CID": "118741", "Status": ""},
    ])
    _make_mirror(mirror_path)
    _save_profile(acc_path, mirror_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not at.exception
    mark_checkboxes = [cb for cb in at.checkbox if cb.label.startswith("Mark (no email")]
    assert len(mark_checkboxes) == 2

    mark_checkboxes[0].set_value(True).run()
    at.button(key="mark_manual_button").click().run()

    assert not at.exception
    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    statuses = accumulated_df["Status"].fillna("").astype(str)
    # Only the ONE checked row was marked -- not both, which a
    # blank-email-keyed write-back would have done.
    assert statuses.str.startswith("Uploaded to Approval Sheet").sum() == 1


def test_write_cleared_leads_uses_fixed_micro_audience_for_in_lob_cid(tmp_path, monkeypatch):
    # 119750 (IN LOB) is a fixed "LOB" value, same pattern as every other
    # known CID -- not read from a leadfile column at all (confirmed
    # against a real rejected batch: no such "LOB" column exists in
    # practice, which used to silently blank micro_audience for this CID).
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    template_path = str(tmp_path / "wxo_template.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "119750",
         "Status": "Sent for Approval - 07-Sep"},
    ])
    _make_mirror(mirror_path)
    _make_lead_template(template_path, existing_rows=[
        ["L-22SD8", "UC", "UC", "2026-08-11 07:25:59", "PAIAP", "Old Asset", "IN", "AI Leaders", "All",
         "Old", "Lead", "old.lead@x.com", "Old Co"],
    ])
    _save_profile(acc_path, mirror_path, cid_lead_template_path={"119750": template_path})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(cb for cb in at.checkbox if cb.label == "Clear lead1@x.com").set_value(True).run()
    at.button(key="write_lead_template_button").click().run()

    assert not at.exception
    template_df = pd.read_excel(template_path, sheet_name="LEAD_TEMPLATE")
    assert template_df.loc[0, "micro_audience"] == "LOB"
    assert template_df.loc[0, "campaign_code"] == "PAIAP"  # carried over from the template's own row


def test_write_cleared_leads_combines_multiple_cids_sharing_one_template(tmp_path, monkeypatch):
    # IN WXO (118743) and IN LOB (119750) route to the same Lead Template
    # file. Writing both in one pass must not let the second CID's
    # clear_existing wipe out the first CID's just-written rows.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    template_path = str(tmp_path / "wxo_template.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118743",
         "Status": "Sent for Approval - 07-Sep"},
        {"Email": "lead2@x.com", "First": "F", "Last": "L", "Company": "Y", "CID": "119750",
         "Status": "Sent for Approval - 07-Sep"},
    ])
    _make_mirror(mirror_path)
    _make_lead_template(template_path, existing_rows=[
        ["L-22SD8", "UC", "UC", "2026-08-11 07:25:59", "PAIAP", "Old Asset", "IN", "AI Leaders", "All",
         "Old", "Lead", "old.lead@x.com", "Old Co"],
    ])
    _save_profile(acc_path, mirror_path, cid_lead_template_path={
        "118743": template_path, "119750": template_path,
    })

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(cb for cb in at.checkbox if cb.label == "Clear lead1@x.com").set_value(True).run()
    next(cb for cb in at.checkbox if cb.label == "Clear lead2@x.com").set_value(True).run()
    at.button(key="write_lead_template_button").click().run()

    assert not at.exception
    template_df = pd.read_excel(template_path, sheet_name="LEAD_TEMPLATE")
    assert len(template_df) == 2  # both new leads present, old row wiped exactly once
    emails = set(template_df["Email"])
    assert emails == {"lead1@x.com", "lead2@x.com"}
    micro_audience_by_email = dict(zip(template_df["Email"], template_df["micro_audience"]))
    assert micro_audience_by_email["lead1@x.com"] == "AI Leaders"  # fixed value for 118743
    assert micro_audience_by_email["lead2@x.com"] == "LOB"  # fixed value for 119750


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
    next(cb for cb in at.checkbox if cb.label == "Clear lead1@x.com").set_value(True).run()
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
         "Status": "Cleared for Upload - 07-Sep", "Country": "IN", "Project Code": "PVLAP",
         "2nd Asset OV Code": "OV-123"},
        {"Email": "lead2@x.com", "First": "F", "Last": "L", "Company": "Y", "CID": "118741",
         "Status": "Cleared for Upload - 07-Sep"},
    ])
    _make_mirror(mirror_path)
    _save_profile(acc_path, mirror_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    reject_checkbox = next(cb for cb in at.checkbox if cb.label == "Reject lead2@x.com")
    reject_checkbox.set_value(True).run()
    reason_input = next(t for t in at.text_input if t.key == "reject_reason_" + reject_checkbox.key.removeprefix("reject_"))
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

    headers = [c.value for c in response_ws[2]]
    row = dict(zip(headers, [c.value for c in response_ws[3]]))  # header row 2, first data row 3
    assert row["Publisher Name"] == "Madison Logic"
    assert row["source_site"] == "madisonlogic.com"
    assert row["Market"] == "IN"
    assert row["Project Code"] == "PVLAP"
    assert row["Campaign Name"] == "Bob"
    assert row["UUCID"] == "OV-123"
    assert row["Campaign Type"] == "2T"

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    status_by_email = dict(zip(accumulated_df["Email"], accumulated_df["Status"]))
    assert status_by_email["lead1@x.com"].startswith("Accepted - Uploaded")
    assert status_by_email["lead2@x.com"].startswith("Rejected - Refunded")


def test_upload_reconciliation_warns_about_response_details_columns_it_cant_fill(tmp_path, monkeypatch):
    # Regression test: append_mirror_rows had no unmatched-column feedback
    # at all -- a real mirror workbook column beyond the ~15 keys this
    # page writes went silently blank forever. Now it must be surfaced.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741",
         "Status": "Cleared for Upload - 07-Sep"},
    ])
    _make_mirror(mirror_path)
    # Add a real column this page's Response Details write never populates.
    wb = openpyxl.load_workbook(mirror_path)
    ws = wb["Response Details"]
    ws.cell(row=2, column=ws.max_column + 1, value="Extra Client Tracking Column")
    wb.save(mirror_path)
    _save_profile(acc_path, mirror_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.button(key="reconcile_upload_button").click().run()

    assert not at.exception
    assert any("Extra Client Tracking Column" in w.value for w in at.warning)


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

    reject_checkbox = next(cb for cb in at.checkbox if cb.label == "Reject lead1@x.com")
    reject_checkbox.set_value(True).run()

    reconcile_button = next(b for b in at.button if b.key == "reconcile_upload_button")
    reconcile_button.click().run()

    assert not at.exception
    assert any("lead1@x.com" in e.value for e in at.error)
    refund_df = pd.read_excel(acc_path, sheet_name="Refund")
    assert refund_df.empty
