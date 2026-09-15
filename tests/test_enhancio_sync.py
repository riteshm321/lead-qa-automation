import datetime

import pandas as pd

from core.app_settings import save_app_settings
from core.enhancio_sync import (
    rejection_reason_from_status_entry, select_rows_for_test_mode, filter_already_uploaded,
    load_pending_leads, save_pending_leads, remove_pending_leads,
    load_uploaded_emails, save_uploaded_emails, format_enhancio_field_value,
)


def test_format_enhancio_field_value_reformats_a_real_datetime_cell():
    # A leadfile date column read by pandas comes back as an actual
    # datetime, not a pre-formatted string -- Enhancio expects MM-DD-YYYY
    # HH:MM:SS regardless of what format the source file used.
    value = datetime.datetime(2026, 3, 5, 14, 30, 0)
    assert format_enhancio_field_value("Created Timestamp", value) == "03-05-2026 14:30:00"


def test_format_enhancio_field_value_reformats_a_pandas_timestamp():
    value = pd.Timestamp("2026-03-05 14:30:00")
    assert format_enhancio_field_value("Created Timestamp", value) == "03-05-2026 14:30:00"


def test_format_enhancio_field_value_parses_a_date_held_as_plain_text():
    # Some leadfiles hold their date column as plain text (a text-formatted
    # Excel cell, or any CSV) instead of a real date cell -- still coerced
    # to the same MM-DD-YYYY HH:MM:SS output, not passed through as-is.
    assert format_enhancio_field_value("Created Timestamp", "2026-03-05 14:30:00") == "03-05-2026 14:30:00"
    assert format_enhancio_field_value("Created Timestamp", "3/5/2026") == "03-05-2026 00:00:00"


def test_format_enhancio_field_value_matches_date_field_labels_case_insensitively():
    assert format_enhancio_field_value("created date", "2026-03-05") == "03-05-2026 00:00:00"
    assert format_enhancio_field_value("Modified_Date", "2026-03-05") == "03-05-2026 00:00:00"


def test_format_enhancio_field_value_leaves_non_date_fields_untouched():
    # A CID/phone/zip that happens to contain digits must never be run
    # through date parsing just because it looks numeric.
    assert format_enhancio_field_value("Zip Code", "20261") == "20261"
    assert format_enhancio_field_value("Work Phone", "12026135000") == "12026135000"
    assert format_enhancio_field_value("First Name", "Joe") == "Joe"


def test_format_enhancio_field_value_falls_back_to_plain_text_when_unparseable():
    assert format_enhancio_field_value("Created Timestamp", "not a date") == "not a date"


def test_format_enhancio_field_value_handles_blank_values():
    assert format_enhancio_field_value("Created Timestamp", "") == ""
    assert format_enhancio_field_value("Created Timestamp", None) == ""
    assert format_enhancio_field_value("First Name", None) == ""


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

    assert load_uploaded_emails("Amazon Business EMEA", "L-22256") == set()

    save_uploaded_emails("Amazon Business EMEA", "L-22256", {" A@X.com ", "b@x.com"})
    assert load_uploaded_emails("Amazon Business EMEA", "L-22256") == {"a@x.com", "b@x.com"}


def test_uploaded_emails_scoped_per_allocation_not_per_client(tmp_path, monkeypatch):
    # The same lead can legitimately be routed to two different
    # allocations for the same client (e.g. two CIDs mapped to different
    # allocations) -- uploading it to one must not block uploading it to
    # the other.
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    save_uploaded_emails("Amazon Business EMEA", "L-22256", {"a@x.com"})
    assert load_uploaded_emails("Amazon Business EMEA", "L-22256") == {"a@x.com"}
    assert load_uploaded_emails("Amazon Business EMEA", "L-22257") == set()
