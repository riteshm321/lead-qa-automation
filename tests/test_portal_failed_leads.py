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
import pytest
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


# ------------------------------------------- persistent failed-leads list
#
# Each portal is driven through the same scenario: upload two leads, one
# fails; a FRESH AppTest (simulating navigating away and back, or a
# restart) with no file uploaded still shows the failed lead, offers it as
# a download with every original column plus "Failure reason", and
# "Retry failed leads" resends only that lead -- dropping it from the list
# once it succeeds.

_PORTALS = {
    "convertr": (_CONVERTR_PAGE, "Upload to Convertr"),
    "enhancio": (_ENHANCIO_PAGE, "Upload to Enhancio"),
    "integrate": (_INTEGRATE_PAGE, "Upload to Integrate"),
}


class _Portal:
    """Sets up one portal for the synthetic client and patches its API
    client; `reject` toggles whether a Company of "REJECT" fails."""

    def __init__(self, name, tmp_path, monkeypatch, setup=True):
        self.name = name
        self.page, self.upload_label = _PORTALS[name]
        self.calls: list = []
        self.reject = True
        if setup:
            {"convertr": _setup_convertr, "enhancio": _setup_enhancio, "integrate": _setup_integrate}[name](
                tmp_path, monkeypatch)
        self._patchers = self._make_patchers()

    def _is_bad(self, company) -> bool:
        return self.reject and company == "REJECT"

    def _make_patchers(self):
        if self.name == "convertr":
            def _submit(enterprise, token, publisher_id, campaign_id, form_id, form_data, link_id=""):
                self.calls.append(form_data["email"])
                if self._is_bad(form_data["company"]):
                    raise ConvertrError("Convertr returned 422: company is required")
                return {"data": f"lead-{len(self.calls)}"}
            return [patch("core.convertr_client.login", return_value={"access_token": "tok"}),
                    patch("core.convertr_client.submit_lead_as_publisher", side_effect=_submit)]
        if self.name == "enhancio":
            def _import(token, allocation_uid, leads):
                submitted, errors = [], []
                for lead in leads:
                    self.calls.append(lead["Email Address"])
                    if self._is_bad(lead["Company Name"]):
                        errors.append({"message": "Company Name is mandatory"})
                    else:
                        submitted.append({"leadId": f"lead-{len(self.calls)}", "status": "Submitted",
                                          "email": lead["Email Address"]})
                return {"submitted": submitted, "errors": errors}
            return [patch("core.enhancio_client.get_access_token", return_value={"access_token": "tok"}),
                    patch("core.enhancio_client.import_leads", side_effect=_import)]

        def _submit_integrate(sid, api_key, api_secret, attributes, callback_url=""):
            self.calls.append(attributes["email"])
            if self._is_bad(attributes["company"]):
                raise IntegrateError("Integrate returned 422: company is required")
            return {"id": f"lead-{len(self.calls)}"}
        return [patch("core.integrate_client.submit_lead", side_effect=_submit_integrate)]

    def __enter__(self):
        for patcher in self._patchers:
            patcher.start()
        return self

    def __exit__(self, *exc):
        for patcher in self._patchers:
            patcher.stop()

    def fresh(self) -> AppTest:
        at = AppTest.from_file(self.page, default_timeout=15)
        at.run()
        assert not at.exception
        return at


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def _has_button(at: AppTest, label: str) -> bool:
    return any(b.label == label for b in at.button)


@pytest.mark.parametrize("portal", sorted(_PORTALS))
def test_failed_leads_persist_download_and_retry(portal, tmp_path, monkeypatch):
    with _Portal(portal, tmp_path, monkeypatch) as p:
        at = p.fresh()
        _upload(at, _two_leads_csv(tmp_path), p.upload_label)
        assert sorted(p.calls) == ["bad@example.com", "good@example.com"]

        # A fresh session with no file uploaded still has the failed lead.
        import core.failed_leads as failed_leads_module
        real_to_excel = failed_leads_module.dataframe_to_excel_bytes
        captured = {}

        def _capture(df, sheet_name="Sheet1"):
            captured["df"] = df.copy()
            return real_to_excel(df, sheet_name=sheet_name)

        with patch("core.failed_leads.dataframe_to_excel_bytes", side_effect=_capture):
            at2 = p.fresh()
        download = next(d for d in at2.get("download_button") if d.proto.label == "Download failed leads (.xlsx)")
        assert download.proto.icon == ":material/download:"
        df = captured["df"]
        assert list(df.columns) == ["CID", "Email", "First Name", "Last Name", "Company", "Failure reason"]
        assert list(df["Email"]) == ["bad@example.com"]
        assert df.iloc[0]["Company"] == "REJECT"
        assert df.iloc[0]["Failure reason"]

        # Retry sends only the failed lead; once it succeeds it leaves the list.
        p.calls.clear()
        p.reject = False
        _button(at2, "Retry failed leads").click().run()
        assert not at2.exception
        assert p.calls == ["bad@example.com"]
        assert not _has_button(at2, "Retry failed leads")
        assert not _has_button(p.fresh(), "Retry failed leads")


@pytest.mark.parametrize("portal", sorted(_PORTALS))
def test_retry_ignores_test_mode_and_a_lead_that_fails_again_stays_listed(portal, tmp_path, monkeypatch):
    with _Portal(portal, tmp_path, monkeypatch) as p:
        at = p.fresh()
        _upload(at, _two_leads_csv(tmp_path), p.upload_label)
        p.calls.clear()
        _set_test_mode(at)
        _button(at, "Retry failed leads").click().run()
        assert not at.exception
        assert p.calls == ["bad@example.com"]
        assert _has_button(at, "Retry failed leads")


@pytest.mark.parametrize("portal", sorted(_PORTALS))
def test_clear_upload_summary_keeps_the_failed_list_and_clear_failed_list_empties_it(
        portal, tmp_path, monkeypatch):
    with _Portal(portal, tmp_path, monkeypatch) as p:
        at = p.fresh()
        _upload(at, _two_leads_csv(tmp_path), p.upload_label)
        results_key = f"{portal}_upload_results"
        assert at.session_state[results_key] is not None

        clear_summary = _button(at, "Clear upload summary")
        assert clear_summary.proto.icon == ":material/clear_all:"
        clear_summary.click().run()
        assert not at.exception
        assert results_key not in at.session_state
        assert not _has_button(at, "Clear upload summary")
        assert _has_button(at, "Retry failed leads")

        _button(at, "Clear failed list").click().run()
        assert not at.exception
        assert not _has_button(at, "Retry failed leads")
        assert not _has_button(p.fresh(), "Retry failed leads")


def test_enhancio_retry_of_a_lead_pulled_from_the_accumulated_report_stamps_its_status(tmp_path, monkeypatch):
    import datetime

    import openpyxl

    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    acc_path = str(tmp_path / "acc.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Date", "CID", "Email", "First Name", "Last Name", "Company", "Status"])
    ws.append([datetime.date.today(), "111", "acc@example.com", "Acc", "Lead", "REJECT", ""])
    wb.save(acc_path)
    save_profile(ClientProfile(
        name=_CLIENT, accumulated_report_path=acc_path, field_mapping=_FM,
        enhancio=EnhancioConfig(
            enabled=True, allocations=[EnhancioAllocationMapping(cid="111", allocation_uid="L-1")],
            field_mapping={"Email": "Email Address", "Company": "Company Name"},
        ),
    ), get_clients_dir())
    save_enhancio_client_id("client-id")

    with _Portal("enhancio", tmp_path, monkeypatch, setup=False) as p:
        at = p.fresh()
        at.radio(key="enhancio_lead_source").set_value("Pull from Accumulated Report by date range").run()
        next(b for b in at.button if b.label == "Upload to Enhancio").click().run()
        assert not at.exception
        assert p.calls == ["acc@example.com"]

        p.calls.clear()
        p.reject = False
        at2 = p.fresh()
        _button(at2, "Retry failed leads").click().run()
        assert not at2.exception
        assert p.calls == ["acc@example.com"]
        assert not _has_button(at2, "Retry failed leads")

    status = pd.read_excel(acc_path, sheet_name="Accumulated")["Status"].iloc[0]
    assert str(status).startswith("Uploaded to Enhancio")
