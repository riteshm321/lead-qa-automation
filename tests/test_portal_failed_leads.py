"""Failed-lead handling shared by the three upload portals (Convertr,
Enhancio, Integrate): a lead that failed at upload time must never be
remembered as "already uploaded", so re-uploading the same (corrected)
file sends only the leads that failed before and skips the ones the portal
accepted -- without needing the "re-upload already uploaded leads"
checkbox. All data here is synthetic.
"""
import os
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from core.app_settings import (
    get_clients_dir, save_app_settings, save_convertr_account_credentials, save_enhancio_client_id,
    save_integrate_credentials,
)
from core.convertr_client import ConvertrError
from core.integrate_client import IntegrateError
from core.models import (
    ClientProfile, ConvertrCampaignMapping, ConvertrConfig, EnhancioAllocationMapping, EnhancioConfig,
    FieldMapping, IntegrateConfig,
)
from core.profile_store import save_profile

_PAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages")
_CONVERTR_PAGE = os.path.join(_PAGES_DIR, "7_Convertr.py")
_ENHANCIO_PAGE = os.path.join(_PAGES_DIR, "8_Enhancio.py")
_INTEGRATE_PAGE = os.path.join(_PAGES_DIR, "9_Integrate.py")

_CLIENT = "Synthetic Client"
_FM = FieldMapping(email="Email", first_name="First Name", last_name="Last Name", company="Company", cid="CID")


def _two_leads_csv(tmp_path, bad_value: str = "REJECT") -> str:
    """Two leads on two different CIDs (so test mode, one-per-campaign or
    one-per-allocation, still sends both). The second lead's Company is
    `bad_value` -- the fakes below reject the lead while it's "REJECT"."""
    path = tmp_path / f"leads_{bad_value.replace(' ', '_')}.csv"
    pd.DataFrame([
        {"CID": "111", "Email": "good@example.com", "First Name": "Good", "Last Name": "Lead", "Company": "Acme"},
        {"CID": "222", "Email": "bad@example.com", "First Name": "Bad", "Last Name": "Lead", "Company": bad_value},
    ]).to_csv(path, index=False)
    return str(path)


def _upload(at: AppTest, csv_path: str, button_label: str) -> None:
    with open(csv_path, "rb") as f:
        at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
    next(b for b in at.button if b.label == button_label).click().run()
    assert not at.exception


def _set_test_mode(at: AppTest) -> None:
    next(c for c in at.checkbox if c.label.startswith("Test mode")).check().run()


# ---------------------------------------------------------------- Convertr


def _setup_convertr(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(
        name=_CLIENT, accumulated_report_path=str(tmp_path / "acc.xlsx"), field_mapping=_FM,
        convertr=ConvertrConfig(
            enabled=True, enterprise="synthetic", publisher_id="1",
            campaigns=[
                ConvertrCampaignMapping(cid="111", campaign_id="C1", global_form_id="F1"),
                ConvertrCampaignMapping(cid="222", campaign_id="C2", global_form_id="F2"),
            ],
            field_mapping={"Email": "email", "Company": "company"},
        ),
    ), get_clients_dir())
    save_convertr_account_credentials(_CLIENT, "me@example.com", "pw")


def _fake_convertr_submit(calls: list):
    def _submit(enterprise, token, publisher_id, campaign_id, form_id, form_data, link_id=""):
        calls.append(form_data["email"])
        if form_data["company"] == "REJECT":
            raise ConvertrError("Convertr returned 422: company is required")
        return {"data": f"lead-{len(calls)}"}
    return _submit


def test_convertr_reupload_sends_only_the_previously_failed_lead(tmp_path, monkeypatch):
    _setup_convertr(tmp_path, monkeypatch)
    calls: list = []
    with patch("core.convertr_client.login", return_value={"access_token": "tok"}), \
         patch("core.convertr_client.submit_lead_as_publisher", side_effect=_fake_convertr_submit(calls)):
        at = AppTest.from_file(_CONVERTR_PAGE, default_timeout=15)
        at.run()
        _set_test_mode(at)
        _upload(at, _two_leads_csv(tmp_path), "Upload to Convertr")
        assert sorted(calls) == ["bad@example.com", "good@example.com"]

        calls.clear()
        at2 = AppTest.from_file(_CONVERTR_PAGE, default_timeout=15)
        at2.run()
        _set_test_mode(at2)
        _upload(at2, _two_leads_csv(tmp_path, bad_value="Fixed Co"), "Upload to Convertr")

    assert calls == ["bad@example.com"]


# ---------------------------------------------------------------- Enhancio


def _setup_enhancio(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(
        name=_CLIENT, accumulated_report_path=str(tmp_path / "acc.xlsx"), field_mapping=_FM,
        enhancio=EnhancioConfig(
            enabled=True,
            allocations=[
                EnhancioAllocationMapping(cid="111", allocation_uid="L-1"),
                EnhancioAllocationMapping(cid="222", allocation_uid="L-2"),
            ],
            field_mapping={"Email": "Email Address", "Company": "Company Name"},
        ),
    ), get_clients_dir())
    save_enhancio_client_id("client-id")


def _fake_enhancio_import(calls: list, rejected_status: str | None = None):
    """A Company of "REJECT" is not accepted. With rejected_status unset, the
    lead is simply missing from submittedLeads (plus a batch error); with
    it set, Enhancio echoes the lead back in submittedLeads but with that
    non-success status and no lead id."""
    def _import(token, allocation_uid, leads):
        submitted, errors = [], []
        for lead in leads:
            calls.append(lead["Email Address"])
            if lead["Company Name"] != "REJECT":
                submitted.append({"leadId": f"lead-{len(calls)}", "status": "Submitted",
                                  "email": lead["Email Address"]})
            elif rejected_status:
                submitted.append({"leadId": None, "status": rejected_status, "email": lead["Email Address"]})
                errors.append({"message": "Company Name is mandatory"})
            else:
                errors.append({"message": "Company Name is mandatory"})
        return {"submitted": submitted, "errors": errors}
    return _import


def _run_enhancio_scenario(tmp_path, monkeypatch, rejected_status=None) -> list:
    _setup_enhancio(tmp_path, monkeypatch)
    calls: list = []
    with patch("core.enhancio_client.get_access_token", return_value={"access_token": "tok"}), \
         patch("core.enhancio_client.import_leads", side_effect=_fake_enhancio_import(calls, rejected_status)):
        at = AppTest.from_file(_ENHANCIO_PAGE, default_timeout=15)
        at.run()
        _set_test_mode(at)
        _upload(at, _two_leads_csv(tmp_path), "Upload to Enhancio")
        assert sorted(calls) == ["bad@example.com", "good@example.com"]

        calls.clear()
        at2 = AppTest.from_file(_ENHANCIO_PAGE, default_timeout=15)
        at2.run()
        _set_test_mode(at2)
        _upload(at2, _two_leads_csv(tmp_path, bad_value="Fixed Co"), "Upload to Enhancio")
    return calls


def test_enhancio_reupload_sends_only_the_previously_failed_lead(tmp_path, monkeypatch):
    assert _run_enhancio_scenario(tmp_path, monkeypatch) == ["bad@example.com"]


def test_enhancio_lead_echoed_back_with_a_failure_status_is_not_remembered_as_uploaded(tmp_path, monkeypatch):
    assert _run_enhancio_scenario(tmp_path, monkeypatch, rejected_status="Rejected") == ["bad@example.com"]


# ---------------------------------------------------------------- Integrate


def _setup_integrate(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_integrate_credentials("key", "secret")
    save_profile(ClientProfile(
        name=_CLIENT, accumulated_report_path=str(tmp_path / "acc.xlsx"), field_mapping=_FM,
        integrate=IntegrateConfig(enabled=True, sid="SID-1",
                                  field_mapping={"Email": "email", "Company": "company"}),
    ), get_clients_dir())


def _fake_integrate_submit(calls: list):
    def _submit(sid, api_key, api_secret, attributes, callback_url=""):
        calls.append(attributes["email"])
        if attributes["company"] == "REJECT":
            raise IntegrateError("Integrate returned 422: company is required")
        return {"id": f"lead-{len(calls)}"}
    return _submit


def test_integrate_reupload_sends_only_the_previously_failed_lead(tmp_path, monkeypatch):
    # Integrate's test mode sends one lead total, so this scenario runs it
    # off to get one accepted + one failed lead in a single upload.
    _setup_integrate(tmp_path, monkeypatch)
    calls: list = []
    with patch("core.integrate_client.submit_lead", side_effect=_fake_integrate_submit(calls)):
        at = AppTest.from_file(_INTEGRATE_PAGE, default_timeout=15)
        at.run()
        _upload(at, _two_leads_csv(tmp_path), "Upload to Integrate")
        assert calls == ["good@example.com", "bad@example.com"]

        calls.clear()
        at2 = AppTest.from_file(_INTEGRATE_PAGE, default_timeout=15)
        at2.run()
        _upload(at2, _two_leads_csv(tmp_path, bad_value="Fixed Co"), "Upload to Integrate")

    assert calls == ["bad@example.com"]


def test_integrate_reupload_checkbox_deliberately_resends_an_accepted_lead(tmp_path, monkeypatch):
    _setup_integrate(tmp_path, monkeypatch)
    calls: list = []
    with patch("core.integrate_client.submit_lead", side_effect=_fake_integrate_submit(calls)):
        at = AppTest.from_file(_INTEGRATE_PAGE, default_timeout=15)
        at.run()
        _upload(at, _two_leads_csv(tmp_path, bad_value="Fixed Co"), "Upload to Integrate")
        calls.clear()

        at2 = AppTest.from_file(_INTEGRATE_PAGE, default_timeout=15)
        at2.run()
        with open(_two_leads_csv(tmp_path, bad_value="Fixed Co"), "rb") as f:
            at2.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
        at2.checkbox(key="integrate_reupload_duplicates").check().run()
        next(b for b in at2.button if b.label == "Upload to Integrate").click().run()
        assert not at2.exception

    assert sorted(calls) == ["bad@example.com", "good@example.com"]


def test_is_accepted_submission_requires_a_lead_id_and_a_non_failure_status():
    from core.enhancio_sync import is_accepted_submission
    assert is_accepted_submission({"leadId": "1", "status": "Submitted", "email": "a@example.com"})
    assert is_accepted_submission({"leadId": "1", "status": "Accepted"})
    assert not is_accepted_submission({"leadId": None, "status": "Submitted"})
    assert not is_accepted_submission({"leadId": "1", "status": "Rejected"})
    assert not is_accepted_submission({"leadId": "1", "status": " duplicate "})
    assert not is_accepted_submission("not a dict")
