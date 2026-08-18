import os
from unittest.mock import patch

import openpyxl
import pandas as pd
from streamlit.testing.v1 import AppTest

from core.app_settings import get_clients_dir, save_jira_settings
from core.models import ClientProfile, FieldMapping, DuplicateConfig
from core.pipeline import PipelineResult
from core.profile_store import save_profile

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "2_Run_Check.py")


def _make_accumulated_report(path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID", "Date"])
    ws.append(["existing@dup.com", "Existing", "Person", "DupCo", "1", "2026-08-01"])
    wb.create_sheet("Refund").append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID", "Date"])
    wb.save(path)


def test_approved_refund_lead_lands_in_accumulated_tab_not_just_refund(tmp_path, monkeypatch):
    # End-to-end regression test for the "approve a refunded lead as valid"
    # feature: AppTest can't simulate a real file upload, so this pre-seeds
    # session_state exactly as it looks right after a real Run Check click
    # (one valid lead, one refund-flagged lead), then drives the actual
    # Refund Reasons checkbox and Finalize button.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
        {"Email_Address": "existing@dup.com", "First_Name": "Existing", "Last_Name": "Person",
         "Company_Name": "DupCo", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={1: "Duplicate - exact email"})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    assert not at.exception

    checkbox = next(c for c in at.checkbox if c.key == "refund_approve_1")
    checkbox.set_value(True).run()
    assert not at.exception

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    wb = openpyxl.load_workbook(acc_path)
    acc_rows = [tuple(r) for r in wb["Accumulated"].iter_rows(min_row=2, values_only=True) if r[0] is not None]
    refund_rows = [tuple(r) for r in wb["Refund"].iter_rows(min_row=2, values_only=True) if r[0] is not None]

    acc_emails = {row[0] for row in acc_rows}
    refund_emails = {row[0] for row in refund_rows}

    assert "bob@new.com" in acc_emails
    assert "existing@dup.com" in acc_emails  # approved despite being auto-flagged for refund
    assert refund_emails == set()  # nothing left in Refund tab once approved


def test_unapproved_refund_lead_stays_refund_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "existing@dup.com", "First_Name": "Existing", "Last_Name": "Person",
         "Company_Name": "DupCo", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[], refund_reasons={0: "Duplicate - exact email"})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    # Leave the checkbox unticked and finalize directly.
    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    wb = openpyxl.load_workbook(acc_path)
    acc_rows = [r for r in wb["Accumulated"].iter_rows(min_row=2, values_only=True) if r[0] is not None]
    refund_rows = [r for r in wb["Refund"].iter_rows(min_row=2, values_only=True) if r[0] is not None]

    assert len(acc_rows) == 1  # only the pre-existing accumulated row, nothing new added
    assert len(refund_rows) == 1
    assert refund_rows[0][0] == "existing@dup.com"


def test_select_all_as_valid_approves_every_refund_lead(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
        {"Email_Address": "b@x.com", "First_Name": "B", "Last_Name": "Two", "Company_Name": "X", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[], refund_reasons={0: "Exclusion - domain", 1: "Exclusion - domain"})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    select_all = next(b for b in at.button if b.label == "Select all as valid")
    select_all.click().run()
    assert not at.exception

    assert at.checkbox(key="refund_approve_0").value is True
    assert at.checkbox(key="refund_approve_1").value is True

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    wb = openpyxl.load_workbook(acc_path)
    acc_emails = {r[0] for r in wb["Accumulated"].iter_rows(min_row=2, values_only=True) if r[0] is not None}
    refund_rows = [r for r in wb["Refund"].iter_rows(min_row=2, values_only=True) if r[0] is not None]

    assert {"a@x.com", "b@x.com"} <= acc_emails
    assert refund_rows == []


def test_post_summary_to_jira_after_finalize(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    save_jira_settings("https://example.atlassian.net", "me@example.com", "token123")

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
        jira_ticket_key="PROJ-1234",
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    # The "Post to Jira" prompt should now be showing, pre-filled with a
    # summary — verify it before actually posting anything.
    import datetime as _dt
    opening_box = next(t for t in at.text_area if t.key == "jira_comment_opening")
    assert _dt.date.today().strftime("%d-%m-%y") in opening_box.value
    assert "1 leads in" in opening_box.value
    assert "1 valid" in opening_box.value
    closing_box = next(t for t in at.text_area if t.key == "jira_comment_closing")
    assert closing_box.value == "Thanks"

    # The Accumulated File link checkbox should be offered (ticked by default).
    link_checkbox = next(c for c in at.checkbox if c.key == "jira_link_Accumulated File")
    assert link_checkbox.value is True

    with patch("core.jira_client.post_comment_body") as mock_post:
        post_button = next(b for b in at.button if b.key == "jira_post_button")
        post_button.click().run()
        assert not at.exception

    mock_post.assert_called_once()
    call_args = mock_post.call_args[0]
    assert call_args[0] == "https://example.atlassian.net"
    assert call_args[1] == "me@example.com"
    assert call_args[2] == "token123"
    assert call_args[3] == "PROJ-1234"
    adf_body = call_args[4]
    assert adf_body["type"] == "doc"
    # The file link should show up as a real ADF link mark, not plain text.
    all_marks = [
        mark
        for node in adf_body["content"] if node["type"] == "orderedList"
        for item in node["content"]
        for para in item["content"]
        for text_node in para["content"]
        for mark in text_node.get("marks", [])
    ]
    assert any(mark["type"] == "link" for mark in all_marks)

    # Session state cleaned up so the prompt disappears after a successful post.
    assert "last_finalized_summary" not in at.session_state


def test_jira_prompt_does_not_appear_without_ticket_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    assert not any(t.key == "jira_comment_opening" for t in at.text_area)


def test_post_summary_to_jira_includes_pacing_overview_as_native_table(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    save_jira_settings("https://example.atlassian.net", "me@example.com", "token123")

    wb = openpyxl.load_workbook(acc_path)
    pacing = wb.create_sheet("Pacing Overview")
    pacing.append(["SR No", "CID", "Campaign Segment"])
    pacing.append([1, "118118", "APAC Mgr+ Q3"])
    pacing.append([2, "118119", "EMEA Mgr+ Q3"])
    wb.save(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
        jira_ticket_key="PROJ-1234",
        jira_reporter_name="Jane",
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    opening_box = next(t for t in at.text_area if t.key == "jira_comment_opening")
    assert "Hi Jane" in opening_box.value

    pacing_checkbox = next(c for c in at.checkbox if c.key == "jira_include_pacing")
    assert pacing_checkbox.value is True

    with patch("core.jira_client.post_comment_body") as mock_post:
        post_button = next(b for b in at.button if b.key == "jira_post_button")
        post_button.click().run()
        assert not at.exception

    adf_body = mock_post.call_args[0][4]
    table_nodes = [n for n in adf_body["content"] if n["type"] == "table"]
    assert len(table_nodes) == 1
    header_row = table_nodes[0]["content"][0]
    header_texts = [c["content"][0]["content"][0]["text"] for c in header_row["content"]]
    assert header_texts == ["SR No", "CID", "Campaign Segment"]
    data_row_1 = table_nodes[0]["content"][1]
    assert data_row_1["content"][1]["content"][0]["content"][0]["text"] == "118118"
