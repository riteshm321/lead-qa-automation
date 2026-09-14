import os
from unittest.mock import patch

import openpyxl
import pandas as pd
from streamlit.testing.v1 import AppTest

from core.app_settings import get_clients_dir, save_convertr_account_credentials, save_app_settings
from core.convertr_sync import save_pending_leads
from core.models import ClientProfile, FieldMapping, ConvertrConfig, ConvertrCampaignMapping
from core.profile_store import save_profile

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "7_Convertr.py")


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
        convertr=ConvertrConfig(
            enabled=True, enterprise="amazonbusiness", publisher_id="11003",
            campaigns=[
                ConvertrCampaignMapping(cid="120022", campaign_id="44709", global_form_id="75"),
                ConvertrCampaignMapping(cid="120028", campaign_id="44706", global_form_id="80"),
            ],
            field_mapping={"Email": "email", "First Name": "firstName", "Last Name": "lastName"},
        ),
    )
    save_profile(profile, get_clients_dir())
    return profile


def test_warns_when_no_client_has_convertr_enabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert any("No client has Convertr enabled" in w.value for w in at.warning)


def test_reconcile_writes_accepted_to_accumulated_and_rejected_to_refund_with_cid_and_reason(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path)
    save_convertr_account_credentials("Amazon Business EMEA", "me@x.com", "hunter2")
    # Simulates what step 1 (Upload) records for every successfully
    # submitted lead: the exact row that was uploaded, keyed by the lead
    # id Convertr returned -- reconcile has no other way to recover an
    # accepted lead's data, since Convertr's own result for a valid lead
    # comes back completely empty.
    save_pending_leads("Amazon Business EMEA", {
        "101": {"Email": "accepted@x.com", "CID": "120022", "First Name": "A", "Last Name": "One"},
        "102": {"Email": "rejected@x.com", "CID": "120028", "First Name": "B", "Last Name": "Two"},
    })

    def _fake_get_lead_result(enterprise, token, publisher_id, lead_id):
        if lead_id == "101":
            return {"status": "valid"}
        return {"status": "invalid", "reasons": ["Unable to Contact"], "lead_data": {}}

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}), \
         patch("core.convertr_client.get_lead_result", side_effect=_fake_get_lead_result):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        fetch_button = next(b for b in at.button if b.label == "Fetch decisions from Convertr")
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
    assert refund_df.loc[0, "Refund Reason"] == "Unable to Contact"


def test_reconcile_does_not_rewrite_already_synced_leads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path)
    save_convertr_account_credentials("Amazon Business EMEA", "me@x.com", "hunter2")
    save_pending_leads("Amazon Business EMEA", {"201": {"Email": "already@x.com", "CID": "120022"}})

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}), \
         patch("core.convertr_client.get_lead_result", return_value={"status": "valid"}):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        next(b for b in at.button if b.label == "Fetch decisions from Convertr").click().run()
        next(b for b in at.button if b.label == "Write to Accumulated & Refund").click().run()

        # Second sync: the lead was removed from the pending store once
        # written, so a repeated fetch has nothing left to check for it.
        at2 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at2.run()
        next(s for s in at2.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        next(b for b in at2.button if b.label == "Fetch decisions from Convertr").click().run()
        assert not at2.exception
        assert any("No new decided leads" in c.value for c in at2.caption)

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    assert len(accumulated_df) == 1  # not 2


def test_jira_section_hidden_without_a_ticket_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated(acc_path)
    _save_profile(acc_path)  # no jira_ticket_key

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert any("No Jira ticket configured" in c.value for c in at.caption)
    assert not any(t.key == "convertr_jira_message" for t in at.text_area)


def test_jira_section_posts_a_summary_after_reconcile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path, jira_ticket_key="PROJ-1234")
    save_convertr_account_credentials("Amazon Business EMEA", "me@x.com", "hunter2")
    save_pending_leads("Amazon Business EMEA", {"301": {"Email": "accepted@x.com", "CID": "120022"}})

    from core.app_settings import save_jira_settings
    save_jira_settings("https://example.atlassian.net", "me@example.com", "token123")

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}), \
         patch("core.convertr_client.get_lead_result", return_value={"status": "valid"}):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        next(b for b in at.button if b.label == "Fetch decisions from Convertr").click().run()
        next(b for b in at.button if b.label == "Write to Accumulated & Refund").click().run()

        message_box = next(t for t in at.text_area if t.key == "convertr_jira_message")
        assert "1 accepted, 0 rejected" in message_box.value

        with patch("core.jira_client.post_comment_body") as mock_post:
            post_button = next(b for b in at.button if b.key == "convertr_jira_post")
            post_button.click().run()
            assert not at.exception
            mock_post.assert_called_once()
            args, _ = mock_post.call_args
            assert args[0] == "https://example.atlassian.net"
            assert args[3] == "PROJ-1234"
