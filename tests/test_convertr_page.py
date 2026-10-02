import os
from unittest.mock import patch

import openpyxl
import pandas as pd
from streamlit.testing.v1 import AppTest

from core.app_settings import get_clients_dir, save_convertr_account_credentials, save_app_settings
from core.convertr_sync import save_pending_leads as _save_pending_leads, load_pending_leads
from core.models import ClientProfile, FieldMapping, ConvertrConfig, ConvertrCampaignMapping
from core.profile_store import save_profile

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "7_Convertr.py")


def save_pending_leads(client_name, lead_id_to_row, batch_id="20260101T000000000000"):
    # These tests stand in for leads saved by an Upload click, so they carry
    # an upload-batch tag like real ones (an untagged lead counts as an
    # earlier upload and isn't fetched by default).
    _save_pending_leads(client_name, lead_id_to_row, batch_id=batch_id)


def _make_accumulated(path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Date", "CID", "Email", "First Name", "Last Name", "Company"])
    wb.create_sheet("Refund").append(
        ["Date", "CID", "Email", "First Name", "Last Name", "Company", "Refund Reason"])
    wb.save(path)


def _save_profile(acc_path: str, jira_ticket_key: str = "", accumulated_report_link: str = "") -> ClientProfile:
    fm = FieldMapping(email="Email", first_name="First Name", last_name="Last Name", company="Company", cid="CID")
    profile = ClientProfile(
        name="Amazon Business EMEA", accumulated_report_path=acc_path, field_mapping=fm,
        jira_ticket_key=jira_ticket_key, accumulated_report_link=accumulated_report_link,
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


def test_reupload_checkbox_lets_you_resend_an_already_uploaded_lead(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path)
    save_convertr_account_credentials("Amazon Business EMEA", "me@x.com", "hunter2")

    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([{"CID": "120022", "Email": "a@x.com", "First Name": "A", "Last Name": "One"}]).to_csv(
        leads_csv, index=False)

    submit_calls = []

    def _fake_submit(enterprise, token, publisher_id, campaign_id, form_id, form_data, link_id=""):
        submit_calls.append(form_data)
        return {"data": len(submit_calls), "message": "ok"}

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}), \
         patch("core.convertr_client.submit_lead_as_publisher", side_effect=_fake_submit):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        with open(leads_csv, "rb") as f:
            at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
        next(b for b in at.button if b.label == "Upload to Convertr").click().run()
        assert not at.exception
        assert len(submit_calls) == 1

        # Re-uploading the same file without the checkbox: skipped, nothing new sent.
        at2 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at2.run()
        next(s for s in at2.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        with open(leads_csv, "rb") as f:
            at2.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
        assert any("already uploaded" in w.value for w in at2.warning)
        next(b for b in at2.button if b.label == "Upload to Convertr").click().run()
        assert not at2.exception
        assert len(submit_calls) == 1

        # Checking "upload anyway" resends it.
        at3 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at3.run()
        next(s for s in at3.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        with open(leads_csv, "rb") as f:
            at3.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
        at3.checkbox(key="convertr_reupload_duplicates").set_value(True).run()
        next(b for b in at3.button if b.label == "Upload to Convertr").click().run()
        assert not at3.exception

    assert len(submit_calls) == 2


def test_rejected_lead_can_be_resent_without_resending_already_accepted_leads(tmp_path, monkeypatch):
    # Same bug class as Enhancio: Convertr's own "submitted" step 1 just
    # means the lead was received for evaluation, not that it was
    # accepted. Reconciling a rejected lead must free its email back up
    # from the already-uploaded memory, so re-uploading the same file
    # resends just that lead -- not every already-accepted lead in the
    # file too (the only alternative being the blanket "resend
    # duplicates" checkbox).
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path)
    save_convertr_account_credentials("Amazon Business EMEA", "me@x.com", "hunter2")

    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([
        {"CID": "120022", "Email": "accepted@x.com", "First Name": "A", "Last Name": "One"},
        {"CID": "120028", "Email": "rejected@x.com", "First Name": "B", "Last Name": "Two"},
    ]).to_csv(leads_csv, index=False)

    submit_calls = []

    def _fake_submit(enterprise, token, publisher_id, campaign_id, form_id, form_data, link_id=""):
        submit_calls.append(form_data)
        return {"data": len(submit_calls), "message": "ok"}

    def _fake_get_lead_result(enterprise, token, publisher_id, lead_id):
        if lead_id == "1":
            return {"status": "valid"}
        return {"status": "invalid", "reasons": ["Unable to Contact"], "lead_data": {}}

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}), \
         patch("core.convertr_client.submit_lead_as_publisher", side_effect=_fake_submit), \
         patch("core.convertr_client.get_lead_result", side_effect=_fake_get_lead_result):
        # First upload: both leads go through, Convertr "submits" both.
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        with open(leads_csv, "rb") as f:
            at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
        next(b for b in at.button if b.label == "Upload to Convertr").click().run()
        assert not at.exception
        assert len(submit_calls) == 2

        # Reconcile: lead "1" accepted, lead "2" rejected.
        next(b for b in at.button if b.label == "Fetch decisions from Convertr").click().run()
        assert not at.exception
        next(b for b in at.button if b.label == "Write to Accumulated & Refund").click().run()
        assert not at.exception

        submit_calls.clear()

        # Second upload of the SAME file: the accepted lead must still be
        # skipped as a duplicate, but the rejected (now refunded) lead must
        # go out again -- without the "resend duplicates" checkbox.
        at2 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at2.run()
        next(s for s in at2.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        with open(leads_csv, "rb") as f:
            at2.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
        next(b for b in at2.button if b.label == "Upload to Convertr").click().run()
        assert not at2.exception

    assert len(submit_calls) == 1
    assert submit_calls[0]["email"] == "rejected@x.com"

    results_df = at2.session_state["convertr_upload_results"]
    skipped = results_df[results_df["Result"].str.startswith("Skipped")]
    assert len(skipped) == 1
    assert skipped.iloc[0]["Email"] == "accepted@x.com"


def test_preview_shows_leads_to_send_without_calling_the_api(tmp_path, monkeypatch):
    # The user must be able to see exactly what would be sent, and
    # download it, before ever clicking "Upload to Convertr" -- this
    # must never call submit_lead_as_publisher.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path)
    save_convertr_account_credentials("Amazon Business EMEA", "me@x.com", "hunter2")

    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([
        {"CID": "120022", "Email": "a@x.com", "First Name": "A", "Last Name": "One"},
        {"CID": "120028", "Email": "b@x.com", "First Name": "B", "Last Name": "Two"},
    ]).to_csv(leads_csv, index=False)

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}), \
         patch("core.convertr_client.submit_lead_as_publisher") as mock_submit:
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        with open(leads_csv, "rb") as f:
            at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()

        assert not at.exception
        mock_submit.assert_not_called()

    preview_expander = next(e for e in at.status if e.label.startswith("Preview leads to send"))
    assert "2 lead(s)" in preview_expander.label
    assert "2 CID(s)" in preview_expander.label
    assert any(dl.key == "convertr_preview_download" for dl in at.download_button)


def test_reconcile_works_with_no_qa_field_mapping_using_convertrs_own_leadfile_mapping(tmp_path, monkeypatch):
    # Regression: a client with no QA configured at all (e.g. Amazon) used
    # to force a trip through Run Check just to populate field_mapping,
    # purely so Convertr's CID/email lookups had somewhere to read from.
    # Convertr's own leadfile_field_mapping (set on Client Setup's Convertr
    # section, independent of QA) must be enough on its own.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)

    fm = FieldMapping(email="Email", first_name="First Name", last_name="Last Name", company="Company", cid="CID")
    profile = ClientProfile(
        name="Amazon Business EMEA", accumulated_report_path=acc_path,
        field_mapping=None,  # no QA configured for this client at all
        convertr=ConvertrConfig(
            enabled=True, enterprise="amazonbusiness", publisher_id="11003",
            campaigns=[ConvertrCampaignMapping(cid="120022", campaign_id="44709", global_form_id="75")],
            field_mapping={"Email": "email", "First Name": "firstName"},
            leadfile_field_mapping=fm,
        ),
    )
    save_profile(profile, get_clients_dir())
    save_convertr_account_credentials("Amazon Business EMEA", "me@x.com", "hunter2")
    save_pending_leads("Amazon Business EMEA", {
        "101": {"Email": "accepted@x.com", "CID": "120022", "First Name": "A", "Last Name": "One"},
    })

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}), \
         patch("core.convertr_client.get_lead_result", return_value={"status": "valid"}):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        next(b for b in at.button if b.label == "Fetch decisions from Convertr").click().run()
        assert not at.exception
        next(b for b in at.button if b.label == "Write to Accumulated & Refund").click().run()
        assert not at.exception

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    assert len(accumulated_df) == 1
    assert accumulated_df.loc[0, "Email"] == "accepted@x.com"
    assert str(accumulated_df.loc[0, "CID"]) == "120022"


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


def test_reconcile_still_processes_other_leads_when_one_lead_fetch_fails(tmp_path, monkeypatch):
    # Regression test for a real, confirmed P1 bug: the reconcile loop used
    # to wrap the ENTIRE per-lead polling loop in one try/except, so a
    # single pending lead's get_lead_result failure (e.g. its campaign was
    # deleted at Convertr) aborted reconciliation of every OTHER
    # already-decided pending lead too, and st.stop() lost all progress
    # made in that pass. Every future "Fetch decisions" click would hit the
    # same failing lead_id and re-abort, silently blocking reconciliation
    # for the whole client indefinitely.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path)
    save_convertr_account_credentials("Amazon Business EMEA", "me@x.com", "hunter2")
    save_pending_leads("Amazon Business EMEA", {
        "101": {"Email": "bad@x.com", "CID": "120022"},
        "102": {"Email": "good@x.com", "CID": "120022"},
    })

    from core.convertr_client import ConvertrError

    def _fake_get_lead_result(enterprise, token, publisher_id, lead_id):
        if lead_id == "101":
            raise ConvertrError("Campaign no longer exists")
        return {"status": "valid"}

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}), \
         patch("core.convertr_client.get_lead_result", side_effect=_fake_get_lead_result):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        next(b for b in at.button if b.label == "Fetch decisions from Convertr").click().run()
        assert not at.exception
        assert any("Campaign no longer exists" in w.value for w in at.warning)
        assert any("1 newly accepted" in i.value for i in at.info)

        next(b for b in at.button if b.label == "Write to Accumulated & Refund").click().run()
        assert not at.exception

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    assert len(accumulated_df) == 1
    assert accumulated_df.loc[0, "Email"] == "good@x.com"

    # The failing lead stays pending for a future retry -- it was never
    # resolved, so it must not have been removed from the pending store.
    remaining_pending = load_pending_leads("Amazon Business EMEA")
    assert "101" in remaining_pending
    assert "102" not in remaining_pending


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


def test_switching_client_after_fetch_does_not_write_the_other_clients_leads(tmp_path, monkeypatch):
    # Regression test for a real, confirmed P0 bug: fetched accepted/
    # rejected decisions were never scoped to the client selected at fetch
    # time. Fetching for Client A, then switching to Client B before
    # clicking "Write to Accumulated & Refund", used to silently write
    # Client A's leads into Client B's Accumulated/Refund tabs.
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    acc_a_path = str(tmp_path / "accumulated_a.xlsx")
    _make_accumulated(acc_a_path)
    _save_profile(acc_a_path)  # "Amazon Business EMEA"
    save_convertr_account_credentials("Amazon Business EMEA", "me@x.com", "hunter2")
    save_pending_leads("Amazon Business EMEA", {"101": {"Email": "a@x.com", "CID": "120022"}})

    acc_b_path = str(tmp_path / "accumulated_b.xlsx")
    _make_accumulated(acc_b_path)
    fm = FieldMapping(email="Email", first_name="First Name", last_name="Last Name", company="Company", cid="CID")
    profile_b = ClientProfile(
        name="Other Client", accumulated_report_path=acc_b_path, field_mapping=fm,
        convertr=ConvertrConfig(
            enabled=True, enterprise="otherclient", publisher_id="99999",
            campaigns=[ConvertrCampaignMapping(cid="1", campaign_id="1", global_form_id="1")],
            field_mapping={"Email": "email"},
        ),
    )
    save_profile(profile_b, get_clients_dir())

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}), \
         patch("core.convertr_client.get_lead_result", return_value={"status": "valid"}):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        next(b for b in at.button if b.label == "Fetch decisions from Convertr").click().run()
        assert not at.exception
        assert any("1 newly accepted" in i.value for i in at.info)

        # Switch to the other client WITHOUT writing Client A's fetch first.
        next(s for s in at.selectbox if s.label == "Client").set_value("Other Client").run()
        assert not at.exception
        # Client A's fetched rows must not be visible/writable for Client B.
        assert not any("newly accepted" in i.value for i in at.info)
        write_buttons = [b for b in at.button if b.label == "Write to Accumulated & Refund"]
        assert write_buttons == []

    accumulated_b_df = pd.read_excel(acc_b_path, sheet_name="Accumulated")
    assert len(accumulated_b_df) == 0  # Client A's lead never landed here

    accumulated_a_df = pd.read_excel(acc_a_path, sheet_name="Accumulated")
    assert len(accumulated_a_df) == 0  # never written for A either -- still pending


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
    _save_profile(acc_path, jira_ticket_key="PROJ-1234",
                  accumulated_report_link="https://madlog.sharepoint.com/:x:/s/Team/AccLink")
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
            adf_body = args[4]
            assert "https://madlog.sharepoint.com/:x:/s/Team/AccLink" in str(adf_body)
            assert "Accumulated File" in str(adf_body)


def test_write_to_accumulated_shows_a_toast_that_survives_the_rerun(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path)
    save_convertr_account_credentials("Amazon Business EMEA", "me@x.com", "hunter2")
    save_pending_leads("Amazon Business EMEA", {"101": {"Email": "accepted@x.com", "CID": "120022"}})

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}), \
         patch("core.convertr_client.get_lead_result", return_value={"status": "valid"}):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Amazon Business EMEA").run()
        next(b for b in at.button if b.label == "Fetch decisions from Convertr").click().run()
        next(b for b in at.button if b.label == "Write to Accumulated & Refund").click().run()
        assert not at.exception

    assert any("1 accepted" in t.value and "0 rejected" in t.value for t in at.toast)


def test_convertr_status_strip_shows_credentials_and_jira_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _save_profile(str(tmp_path / "accumulated.xlsx"))  # no account credentials, no Jira ticket

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    strip = next(m.value for m in at.markdown if "badge[Account credentials" in m.value)
    assert ":orange-badge[Account credentials :material/warning: Needs setup]" in strip
    assert ":gray-badge[Jira ticket :material/radio_button_unchecked: Off]" in strip

    save_convertr_account_credentials("Amazon Business EMEA", "me@x.com", "hunter2")
    at.run()
    strip = next(m.value for m in at.markdown if "badge[Account credentials" in m.value)
    assert ":blue-badge[Account credentials :material/task_alt: Configured]" in strip


def test_convertr_sections_are_icon_titled_cards_and_icons_replace_emoji(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save_profile(str(tmp_path / "accumulated.xlsx"), jira_ticket_key="PROJ-1234")

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert at.title[0].value == ":material/link: Convertr"
    assert [s.value for s in at.subheader] == [
        ":material/upload: 1. Upload leads to Convertr",
        ":material/sync: 2. Reconcile accepted/rejected leads",
        ":material/forum: Post to Jira",
    ]
    post = at.button(key="convertr_jira_post")
    assert post.label == "Post to PROJ-1234"
    assert post.proto.icon == ":material/send:"


def test_convertr_upload_summary_uses_icon_metric_cards(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save_profile(str(tmp_path / "accumulated.xlsx"))

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["convertr_upload_results"] = pd.DataFrame([
        {"CID": "44709", "Email": "a@x.com", "Result": "Uploaded — Lead ID 1"},
        {"CID": "44709", "Email": "b@x.com", "Result": "Failed — Convertr returned 400: bad email"},
        {"CID": "44709", "Email": "c@x.com", "Result": "Skipped (already uploaded previously)"},
    ])
    at.run()
    assert not at.exception
    assert [m.label for m in at.metric] == ["Uploaded", "Failed", "Skipped"]
    assert [m.value for m in at.metric] == ["1", "1", "1"]
    assert [m.proto.icon for m in at.metric] == [
        ":material/check_circle:", ":material/error:", ":material/skip_next:"]


def test_convertr_download_button_and_no_credentials_error_use_icons(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save_profile(str(tmp_path / "accumulated.xlsx"))

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([{"Email": "a@x.com", "First Name": "A", "Last Name": "One", "Company": "Acme",
                   "CID": "120022"}]).to_csv(leads_csv, index=False)
    with open(leads_csv, "rb") as f:
        at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
    assert not at.exception
    download = next(d for d in at.download_button if d.key == "convertr_preview_download")
    assert download.proto.label == "Download these leads (.xlsx)"
    assert download.proto.icon == ":material/download:"

    next(b for b in at.button if b.label == "Upload to Convertr").click().run()
    assert not at.exception
    err = next(e for e in at.error if "Convertr account username/password" in e.value)
    assert err.icon == ":material/error:"
    assert not err.value.startswith("Failed")


def test_switching_client_resets_the_jira_message_to_the_new_clients_default(tmp_path, monkeypatch):
    # Regression: the keyed Jira "Message" box kept the previously selected
    # client's greeting/summary after switching the Client dropdown, so
    # Post would send client A's text to client B's ticket.
    monkeypatch.chdir(tmp_path)
    for name, reporter, ticket in (("Switch A", "Alice", "AAA-1"), ("Switch B", "Bob", "BBB-2")):
        save_profile(ClientProfile(
            name=name, accumulated_report_path=str(tmp_path / f"{name}.xlsx"),
            jira_ticket_key=ticket, jira_reporter_name=reporter,
            convertr=ConvertrConfig(enabled=True, enterprise="ent", publisher_id="1"),
        ), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(s for s in at.selectbox if s.label == "Client").set_value("Switch A").run()
    assert at.text_area(key="convertr_jira_message").value.startswith("Hi Alice,")

    next(s for s in at.selectbox if s.label == "Client").set_value("Switch B").run()
    assert not at.exception
    assert at.text_area(key="convertr_jira_message").value.startswith("Hi Bob,")


def _upload_csv(at, tmp_path, name, rows):
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    with open(path, "rb") as f:
        at.get("file_uploader")[0].set_value((name, f.read(), "text/csv")).run()
    next(b for b in at.button if b.label == "Upload to Convertr").click().run()
    assert not at.exception


def test_fetch_decisions_polls_only_the_latest_upload_unless_earlier_ones_are_ticked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path)
    save_convertr_account_credentials("Amazon Business EMEA", "me@x.com", "hunter2")

    submit_calls = []
    polled = []

    def _fake_submit(enterprise, token, publisher_id, campaign_id, form_id, form_data, link_id=""):
        submit_calls.append(form_data)
        return {"data": len(submit_calls), "message": "ok"}

    def _fake_get_lead_result(enterprise, token, publisher_id, lead_id):
        polled.append(lead_id)
        return {"status": "pending"}

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}),          patch("core.convertr_client.submit_lead_as_publisher", side_effect=_fake_submit),          patch("core.convertr_client.get_lead_result", side_effect=_fake_get_lead_result):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        _upload_csv(at, tmp_path, "first.csv", [{"CID": "120022", "Email": "first@x.com"}])
        _upload_csv(at, tmp_path, "second.csv", [
            {"CID": "120022", "Email": "second@x.com"}, {"CID": "120028", "Email": "third@x.com"}])
        assert len(submit_calls) == 3

        assert any(c.value.startswith("Checking the latest upload: 2 lead(s) (uploaded ") for c in at.caption)
        include_earlier = at.checkbox(key="convertr_fetch_include_earlier")
        assert include_earlier.label == "Also check 1 pending lead(s) from earlier uploads"

        next(b for b in at.button if b.label == "Fetch decisions from Convertr").click().run()
        assert not at.exception
        assert sorted(polled) == ["2", "3"]

        polled.clear()
        at.checkbox(key="convertr_fetch_include_earlier").check().run()
        next(b for b in at.button if b.label == "Fetch decisions from Convertr").click().run()
        assert not at.exception
        assert sorted(polled) == ["1", "2", "3"]


def test_untagged_pending_leads_from_before_batching_count_as_earlier_uploads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)
    _save_profile(acc_path)
    save_convertr_account_credentials("Amazon Business EMEA", "me@x.com", "hunter2")
    _save_pending_leads("Amazon Business EMEA", {"901": {"Email": "legacy@x.com", "CID": "120022"}})

    polled = []

    def _fake_get_lead_result(enterprise, token, publisher_id, lead_id):
        polled.append(lead_id)
        return {"status": "pending"}

    with patch("core.convertr_client.login", return_value={"access_token": "tok"}),          patch("core.convertr_client.get_lead_result", side_effect=_fake_get_lead_result):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        assert at.checkbox(key="convertr_fetch_include_earlier").label ==             "Also check 1 pending lead(s) from earlier uploads"
        next(b for b in at.button if b.label == "Fetch decisions from Convertr").click().run()
        assert polled == []

        at.checkbox(key="convertr_fetch_include_earlier").check().run()
        next(b for b in at.button if b.label == "Fetch decisions from Convertr").click().run()
        assert polled == ["901"]


def test_no_earlier_uploads_checkbox_when_every_pending_lead_is_from_the_latest_upload(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _save_profile(str(tmp_path / "accumulated.xlsx"))
    save_pending_leads("Amazon Business EMEA", {"1": {"Email": "a@x.com", "CID": "120022"}})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert not any(c.key == "convertr_fetch_include_earlier" for c in at.checkbox)
    assert any(c.value == "Checking the latest upload: 1 lead(s) (uploaded 01 Jan 2026 00:00)." for c in at.caption)
