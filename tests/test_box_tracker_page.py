import datetime
import os
from unittest.mock import patch

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


def test_pick_and_send_leaves_status_blank_when_the_mirror_write_fails(tmp_path, monkeypatch):
    # Regression test for a real, confirmed P0 bug: Status used to be
    # marked "Sent for Approval" BEFORE the leads were actually written to
    # the mirror Approval Sheet. If that write failed for any reason
    # (wrong tab, mirror file locked mid-Box-sync, disk error), the leads
    # were already marked sent even though they were never actually
    # written -- both recovery paths on this page filter strictly on
    # blank Status, so those leads became permanently invisible to the
    # whole tool. Status must now only be marked once the mirror write
    # (and Pacing update) has actually succeeded.
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
    with patch("core.box_tracker.append_mirror_rows", side_effect=RuntimeError("mirror file locked")):
        pick_button.click().run()

    assert not at.exception  # caught and shown via render_error, not an unhandled crash

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    sent_count = (accumulated_df["Status"].astype(str).str.startswith("Sent for Approval")).sum()
    assert sent_count == 0  # never marked sent -- the mirror write never actually succeeded


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
    # No shortfall warning for an uncapped campaign.
    assert not any("shortfall" in w.value.lower() or "short by" in w.value.lower() for w in at.warning)

    wb = openpyxl.load_workbook(mirror_path)
    assert wb["Approval Sheet"].max_row == 1 + 7  # all 7 leads, no diff+buffer cap

    pacing_ws = wb["Pacing"]
    # CXO's row (row 4) "D" column under "Week of 7" must be untouched (still 0).
    assert pacing_ws.cell(row=4, column=7).value == 0


def test_manual_marking_marks_a_blank_status_lead_as_uploaded_to_approval_sheet(tmp_path, monkeypatch):
    # A lead the user approved by hand (added straight to the real
    # Approval Sheet themselves, skipping the automated picking) starts
    # with a blank Status and is marked via the "I already added these
    # myself" flow.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "manual@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741", "Status": ""},
    ])
    _make_mirror(mirror_path)
    _save_profile(acc_path, mirror_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert any(cb.label == "Mark manual@x.com" for cb in at.checkbox)

    next(cb for cb in at.checkbox if cb.label == "Mark manual@x.com").set_value(True).run()
    at.button(key="mark_manual_button").click().run()

    assert not at.exception
    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    status = accumulated_df.loc[accumulated_df["Email"] == "manual@x.com", "Status"].iloc[0]
    assert status.startswith("Uploaded to Approval Sheet")


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


def test_box_tracker_is_an_icon_titled_card_with_a_shared_empty_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    # One already-finished lead: not blank-Status, so the manual-marking
    # list is empty and shows its empty state.
    _make_accumulated(acc_path, [
        {"Email": "done@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741",
         "Status": "Accepted - Uploaded 01-Sep"},
    ])
    _make_mirror(mirror_path)
    _save_profile(acc_path, mirror_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert at.title[0].value == ":material/inventory_2: Box Tracker"
    assert [s.value for s in at.subheader] == [":material/outgoing_mail: Send leads for approval"]
    # st.expander(..., icon=...) is exposed by AppTest as at.status, not at.expander.
    expanders = [(e.label, e.icon) for e in at.status]
    assert expanders.count(("How this works", ":material/info:")) == 1
    assert ("Or: I already added these leads to the real Approval Sheet myself", ":material/back_hand:") in expanders
    captions = [c.value for c in at.caption]
    assert any(c.startswith(":material/task_alt: No blank-Status leads available to mark.") for c in captions)
