import os
from unittest.mock import patch

import openpyxl
import pandas as pd
from streamlit.testing.v1 import AppTest

from core.app_settings import get_clients_dir, save_enhancio_client_id, save_app_settings
from core.enhancio_sync import save_pending_leads
from core.models import ClientProfile, FieldMapping, EnhancioConfig, EnhancioAllocationMapping
from core.profile_store import save_profile

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "8_Enhancio.py")


def _make_accumulated(path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Date", "CID", "Email", "First Name", "Last Name", "Company"])
    wb.create_sheet("Refund").append(
        ["Date", "CID", "Email", "First Name", "Last Name", "Company", "Refund Reason"])
    wb.save(path)


def _save_profile(acc_path: str, jira_ticket_key: str = "") -> ClientProfile:
    fm = FieldMapping(email="Email", first_name="First Name", last_name="Last Name", company="Company", cid="CID")
    profile = ClientProfile(
        name="Amazon Business EMEA", accumulated_report_path=acc_path, field_mapping=fm,
        jira_ticket_key=jira_ticket_key,
        enhancio=EnhancioConfig(
            enabled=True,
            allocations=[
                EnhancioAllocationMapping(cid="120022", allocation_uid="L-22256"),
                EnhancioAllocationMapping(cid="120028", allocation_uid="L-22257"),
            ],
            field_mapping={"Email": "Email Address", "First Name": "First Name"},
        ),
    )
    save_profile(profile, get_clients_dir())
    return profile


def test_warns_when_no_client_has_enhancio_enabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert any("No client has Enhancio enabled" in w.value for w in at.warning)


def test_upload_batches_leads_by_allocation_and_reports_results(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path)
    save_enhancio_client_id("CID123")

    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([
        {"CID": "120022", "Email": "a@x.com", "First Name": "A", "Last Name": "One", "Company": "Acme"},
        {"CID": "120028", "Email": "b@x.com", "First Name": "B", "Last Name": "Two", "Company": "Acme"},
    ]).to_csv(leads_csv, index=False)

    def _fake_import_leads(token, allocation_uid, leads):
        return [{"leadId": f"lead-{allocation_uid}-{i}", "status": "Submitted", "email": lead["Email Address"]}
                for i, lead in enumerate(leads)]

    with patch("core.enhancio_client.get_access_token", return_value={"access_token": "tok"}), \
         patch("core.enhancio_client.import_leads", side_effect=_fake_import_leads):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        with open(leads_csv, "rb") as f:
            at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
        next(b for b in at.button if b.label == "Upload to Enhancio").click().run()
        assert not at.exception

    results_df = at.session_state["enhancio_upload_results"]
    assert results_df["Result"].str.startswith("✅").sum() == 2
    assert any("lead-L-22256" in r for r in results_df["Result"])
    assert any("lead-L-22257" in r for r in results_df["Result"])


def test_reconcile_writes_accepted_to_accumulated_and_rejected_to_refund_with_cid_and_reason(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path)
    save_enhancio_client_id("CID123")
    save_pending_leads("Amazon Business EMEA", {
        "101": {"Email": "accepted@x.com", "CID": "120022", "First Name": "A", "Last Name": "One"},
        "102": {"Email": "rejected@x.com", "CID": "120028", "First Name": "B", "Last Name": "Two"},
    })

    def _fake_get_lead_status(token, lead_ids):
        return [
            {"leadId": "101", "status": "Accepted", "email": "accepted@x.com"},
            {"leadId": "102", "status": "Rejected", "email": "rejected@x.com", "rejectionReason": "Lead Duplicate"},
        ]

    with patch("core.enhancio_client.get_access_token", return_value={"access_token": "tok"}), \
         patch("core.enhancio_client.get_lead_status", side_effect=_fake_get_lead_status):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        fetch_button = next(b for b in at.button if b.label == "Fetch decisions from Enhancio")
        fetch_button.click().run()
        assert not at.exception

        write_button = next(b for b in at.button if b.label == "Write to Accumulated & Refund")
        write_button.click().run()
        assert not at.exception

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    assert len(accumulated_df) == 1
    assert accumulated_df.loc[0, "Email"] == "accepted@x.com"
    assert str(accumulated_df.loc[0, "CID"]) == "120022"
    assert pd.notna(accumulated_df.loc[0, "Date"])

    refund_df = pd.read_excel(acc_path, sheet_name="Refund")
    assert len(refund_df) == 1
    assert refund_df.loc[0, "Email"] == "rejected@x.com"
    assert str(refund_df.loc[0, "CID"]) == "120028"
    assert refund_df.loc[0, "Refund Reason"] == "Lead Duplicate"


def test_reconcile_leaves_unresolved_leads_pending(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path)
    save_enhancio_client_id("CID123")
    save_pending_leads("Amazon Business EMEA", {"201": {"Email": "still@x.com", "CID": "120022"}})

    with patch("core.enhancio_client.get_access_token", return_value={"access_token": "tok"}), \
         patch("core.enhancio_client.get_lead_status", return_value=[]):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        next(b for b in at.button if b.label == "Fetch decisions from Enhancio").click().run()
        assert not at.exception
        assert any("No new decided leads" in c.value for c in at.caption)

    from core.enhancio_sync import load_pending_leads
    assert load_pending_leads("Amazon Business EMEA") == {"201": {"Email": "still@x.com", "CID": "120022"}}


def test_jira_section_hidden_without_a_ticket_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated(acc_path)
    _save_profile(acc_path)  # no jira_ticket_key

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert any("No Jira ticket configured" in c.value for c in at.caption)
    assert not any(t.key == "enhancio_jira_message" for t in at.text_area)


def test_jira_section_posts_a_summary_after_reconcile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path, jira_ticket_key="PROJ-1234")
    save_enhancio_client_id("CID123")
    save_pending_leads("Amazon Business EMEA", {"301": {"Email": "accepted@x.com", "CID": "120022"}})

    from core.app_settings import save_jira_settings
    save_jira_settings("https://example.atlassian.net", "me@example.com", "token123")

    with patch("core.enhancio_client.get_access_token", return_value={"access_token": "tok"}), \
         patch("core.enhancio_client.get_lead_status",
               return_value=[{"leadId": "301", "status": "Accepted", "email": "accepted@x.com"}]):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        next(b for b in at.button if b.label == "Fetch decisions from Enhancio").click().run()
        next(b for b in at.button if b.label == "Write to Accumulated & Refund").click().run()

        message_box = next(t for t in at.text_area if t.key == "enhancio_jira_message")
        assert "1 accepted, 0 rejected" in message_box.value

        with patch("core.jira_client.post_comment_body") as mock_post:
            post_button = next(b for b in at.button if b.key == "enhancio_jira_post")
            post_button.click().run()
            assert not at.exception
            mock_post.assert_called_once()
            args, _ = mock_post.call_args
            assert args[0] == "https://example.atlassian.net"
            assert args[3] == "PROJ-1234"
