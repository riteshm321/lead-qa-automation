import pandas as pd

from core.app_settings import save_app_settings
from core.enhancio_sync import (
    rejection_reason_from_status_entry, select_rows_for_test_mode, filter_already_uploaded,
    load_pending_leads, save_pending_leads, remove_pending_leads,
    load_uploaded_emails, save_uploaded_emails,
)


def test_rejection_reason_prefers_rejection_reason_field():
    entry = {"status": "Rejected", "rejectionReason": "Lead Duplicate", "comments": "Duplicate lead within campaign"}
    assert rejection_reason_from_status_entry(entry) == "Lead Duplicate"


def test_rejection_reason_falls_back_to_comments_then_generic():
    assert rejection_reason_from_status_entry(
        {"status": "Rejected", "comments": "Invalid domain"}) == "Invalid domain"
    assert rejection_reason_from_status_entry({"status": "Rejected"}) == "Rejected by Enhancio"


def test_select_rows_for_test_mode_picks_one_row_per_unique_allocation_not_per_cid():
    leads_df = pd.DataFrame([
        {"CID": "120022", "Email": "a@x.com"},
        {"CID": "120021", "Email": "b@x.com"},
        {"CID": "120028", "Email": "c@x.com"},
    ])
    cid_to_allocation_uid = {"120022": "L-1", "120021": "L-1", "120028": "L-2"}

    send_df, skip_df = select_rows_for_test_mode(leads_df, "CID", cid_to_allocation_uid)

    assert list(send_df["Email"]) == ["a@x.com", "c@x.com"]
    assert list(skip_df["Email"]) == ["b@x.com"]


def test_select_rows_for_test_mode_ignores_cids_with_no_allocation_mapping():
    leads_df = pd.DataFrame([{"CID": "999999", "Email": "a@x.com"}])

    send_df, skip_df = select_rows_for_test_mode(leads_df, "CID", {})

    assert send_df.empty
    assert skip_df.empty


def test_filter_already_uploaded_splits_by_normalized_email():
    leads_df = pd.DataFrame([
        {"Email": "A@x.com", "CID": "1"},
        {"Email": " b@x.com ", "CID": "2"},
        {"Email": "c@x.com", "CID": "3"},
    ])

    send_df, dup_df = filter_already_uploaded(leads_df, "Email", {"a@x.com", "b@x.com"})

    assert list(send_df["Email"]) == ["c@x.com"]
    assert list(dup_df["Email"]) == ["A@x.com", " b@x.com "]


def test_pending_leads_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    assert load_pending_leads("Amazon Business EMEA") == {}

    save_pending_leads("Amazon Business EMEA", {"1": {"Email": "a@x.com", "CID": "120022"}})
    assert load_pending_leads("Amazon Business EMEA") == {"1": {"Email": "a@x.com", "CID": "120022"}}


def test_pending_leads_scoped_per_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    save_pending_leads("Client A", {"1": {"Email": "a@x.com"}})
    assert load_pending_leads("Client B") == {}


def test_remove_pending_leads_drops_only_the_given_ids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    save_pending_leads("Amazon Business EMEA", {
        "1": {"Email": "a@x.com"}, "2": {"Email": "b@x.com"}, "3": {"Email": "c@x.com"},
    })
    remove_pending_leads("Amazon Business EMEA", ["1", "3"])

    assert load_pending_leads("Amazon Business EMEA") == {"2": {"Email": "b@x.com"}}


def test_uploaded_emails_round_trip_and_normalizes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    assert load_uploaded_emails("Amazon Business EMEA") == set()

    save_uploaded_emails("Amazon Business EMEA", {" A@X.com ", "b@x.com"})
    assert load_uploaded_emails("Amazon Business EMEA") == {"a@x.com", "b@x.com"}
