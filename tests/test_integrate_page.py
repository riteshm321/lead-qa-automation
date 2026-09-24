import os
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from core.app_settings import get_clients_dir, save_app_settings, save_integrate_credentials
from core.integrate_sync import load_uploaded_emails
from core.models import ClientProfile, FieldMapping, IntegrateConfig
from core.profile_store import save_profile

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "9_Integrate.py")


def _save_profile() -> ClientProfile:
    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="Everpure EMEA", accumulated_report_path="acc.xlsx", field_mapping=fm,
        integrate=IntegrateConfig(
            enabled=True, sid="d8a9deeb-7bb2-4832-b3d9-1df8a9fe5cab",
            field_mapping={"Email": "email", "First": "first_name", "Last": "last_name"},
            fixed_field_values={"country": "UK"},
        ),
    )
    save_profile(profile, get_clients_dir())
    return profile


def test_warns_when_no_client_has_integrate_enabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert any("No client has Integrate enabled" in w.value for w in at.warning)


def test_errors_when_credentials_are_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _save_profile()
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(s for s in at.selectbox if s.label == "Client").set_value("Everpure EMEA").run()
    assert any("Integrate API Key/Secret" in e.value for e in at.error)


def test_uploads_leads_and_saves_dedup_state_incrementally(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_integrate_credentials("key123", "secret456")
    _save_profile()

    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([
        {"CID": "1", "Email": "a@x.com", "First": "A", "Last": "One"},
        {"CID": "1", "Email": "b@x.com", "First": "B", "Last": "Two"},
    ]).to_csv(leads_csv, index=False)

    submit_calls = []

    def _fake_submit(sid, api_key, api_secret, attributes, callback_url=""):
        submit_calls.append((sid, api_key, api_secret, attributes))
        return {"id": f"lead-{len(submit_calls)}"}

    with patch("core.integrate_client.submit_lead", side_effect=_fake_submit):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Everpure EMEA").run()
        with open(leads_csv, "rb") as f:
            at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
        next(b for b in at.button if b.label == "Upload to Integrate").click().run()

    assert not at.exception
    assert len(submit_calls) == 2
    assert submit_calls[0][0] == "d8a9deeb-7bb2-4832-b3d9-1df8a9fe5cab"
    assert submit_calls[0][1:3] == ("key123", "secret456")
    assert submit_calls[0][3] == {"email": "a@x.com", "first_name": "A", "last_name": "One", "country": "UK"}
    assert load_uploaded_emails("Everpure EMEA") == {"a@x.com", "b@x.com"}


def test_test_mode_sends_only_the_first_lead(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_integrate_credentials("key123", "secret456")
    _save_profile()

    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([
        {"CID": "1", "Email": "a@x.com", "First": "A", "Last": "One"},
        {"CID": "1", "Email": "b@x.com", "First": "B", "Last": "Two"},
    ]).to_csv(leads_csv, index=False)

    with patch("core.integrate_client.submit_lead", return_value={"id": "lead-1"}) as mock_submit:
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Everpure EMEA").run()
        at.checkbox(key="integrate_test_mode").set_value(True).run()
        with open(leads_csv, "rb") as f:
            at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
        next(b for b in at.button if b.label == "Upload to Integrate").click().run()

    assert not at.exception
    assert mock_submit.call_count == 1
    assert load_uploaded_emails("Everpure EMEA") == {"a@x.com"}


def test_a_single_lead_failure_does_not_abort_the_rest_of_the_batch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_integrate_credentials("key123", "secret456")
    _save_profile()

    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([
        {"CID": "1", "Email": "bad@x.com", "First": "Bad", "Last": "Lead"},
        {"CID": "1", "Email": "good@x.com", "First": "Good", "Last": "Lead"},
    ]).to_csv(leads_csv, index=False)

    from core.integrate_client import IntegrateError

    def _fake_submit(sid, api_key, api_secret, attributes, callback_url=""):
        if attributes["email"] == "bad@x.com":
            raise IntegrateError("Integrate returned 422: Invalid email address")
        return {"id": "lead-ok"}

    with patch("core.integrate_client.submit_lead", side_effect=_fake_submit):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Everpure EMEA").run()
        with open(leads_csv, "rb") as f:
            at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
        next(b for b in at.button if b.label == "Upload to Integrate").click().run()

    assert not at.exception
    assert load_uploaded_emails("Everpure EMEA") == {"good@x.com"}


def test_dedup_skips_a_previously_uploaded_email(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_integrate_credentials("key123", "secret456")
    _save_profile()
    from core.integrate_sync import save_uploaded_emails
    save_uploaded_emails("Everpure EMEA", {"a@x.com"})

    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([{"CID": "1", "Email": "a@x.com", "First": "A", "Last": "One"}]).to_csv(leads_csv, index=False)

    with patch("core.integrate_client.submit_lead") as mock_submit:
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Everpure EMEA").run()
        with open(leads_csv, "rb") as f:
            at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()

    assert not at.exception
    assert any("already uploaded" in w.value for w in at.warning)
    mock_submit.assert_not_called()
