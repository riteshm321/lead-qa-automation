import os
from unittest.mock import patch

import openpyxl
import pandas as pd
from streamlit.testing.v1 import AppTest

from core.app_settings import get_clients_dir, save_convertr_account_credentials, save_app_settings
from core.convertr_sync import save_email_to_cid_map
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


def _save_profile(acc_path: str) -> ClientProfile:
    fm = FieldMapping(email="Email", first_name="First Name", last_name="Last Name", company="Company", cid="CID")
    profile = ClientProfile(
        name="Amazon Business EMEA", accumulated_report_path=acc_path, field_mapping=fm,
        convertr=ConvertrConfig(
            enabled=True, enterprise="amazonbusiness",
            campaigns=[
                ConvertrCampaignMapping(cid="120022", campaign_id="44709", global_form_id="75"),
                ConvertrCampaignMapping(cid="120028", campaign_id="44706", global_form_id="80"),
            ],
            field_mapping={"Email": "email", "First Name": "firstName", "Last Name": "lastName"},
        ),
    )
    save_profile(profile, get_clients_dir())
    return profile


def _lead(lead_id: int, status: str, email: str, reason: str | None = None) -> dict:
    # Deliberately carries no "cid" field of any kind -- CID is recovered
    # purely by matching email back to save_email_to_cid_map's record of
    # the leadfile used at upload time, not from anything Convertr itself
    # echoes back (it has no native place to carry CID at all).
    lead = {
        "id": lead_id, "email": email, "firstName": "A", "lastName": "One",
        "leadStatus": {"name": status},
    }
    if reason:
        lead["leadFlag"] = {"reason": reason}
    return lead


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
    # Simulates what step 1 (Upload) records for every lead in the file,
    # regardless of upload outcome -- reconcile has no other way to know
    # which CID an email belongs to.
    save_email_to_cid_map("Amazon Business EMEA", {"accepted@x.com": "120022", "rejected@x.com": "120028"})

    accepted_lead = _lead(101, "Valid", "accepted@x.com")
    rejected_lead = _lead(102, "Invalid", "rejected@x.com", reason="Unable to Contact")

    def _fake_get_leads(enterprise, token, campaign_id, page=1, items_per_page=100, updated_after=None):
        if campaign_id == "44709":
            return {"hydra:member": [accepted_lead] if page == 1 else []}
        return {"hydra:member": [rejected_lead] if page == 1 else []}

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}), \
         patch("core.convertr_client.get_leads", side_effect=_fake_get_leads):
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
    save_email_to_cid_map("Amazon Business EMEA", {"already@x.com": "120022"})

    accepted_lead = _lead(201, "Valid", "already@x.com")

    def _fake_get_leads(enterprise, token, campaign_id, page=1, items_per_page=100, updated_after=None):
        if campaign_id == "44709":
            return {"hydra:member": [accepted_lead] if page == 1 else []}
        return {"hydra:member": []}

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}), \
         patch("core.convertr_client.get_leads", side_effect=_fake_get_leads):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        next(b for b in at.button if b.label == "Fetch decisions from Convertr").click().run()
        next(b for b in at.button if b.label == "Write to Accumulated & Refund").click().run()

        # Second sync: same lead comes back from Convertr again (still
        # "Valid") -- must not be appended a second time.
        at2 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at2.run()
        next(s for s in at2.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        next(b for b in at2.button if b.label == "Fetch decisions from Convertr").click().run()
        assert not at2.exception
        assert any("No new decided leads" in c.value for c in at2.caption)

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    assert len(accumulated_df) == 1  # not 2
