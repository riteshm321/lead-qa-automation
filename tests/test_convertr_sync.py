import pandas as pd

from core.app_settings import save_app_settings
from core.convertr_sync import (
    rejection_reason_from_result, select_rows_for_test_mode, filter_already_uploaded,
    load_pending_leads, save_pending_leads, remove_pending_leads,
    load_uploaded_emails, save_uploaded_emails,
)


def test_rejection_reason_prefers_reasons_list():
    result = {"status": "invalid", "reasons": ["Unable to Contact", "Duplicate"]}
    assert rejection_reason_from_result(result) == "Unable to Contact; Duplicate"


def test_rejection_reason_generic_fallback_when_no_reasons_available():
    assert rejection_reason_from_result({"status": "invalid", "reasons": []}) == "Rejected by Convertr"
    assert rejection_reason_from_result({"status": "invalid"}) == "Rejected by Convertr"


def test_select_rows_for_test_mode_picks_one_row_per_unique_campaign_not_per_cid():
    # 120022 and 120021 both share campaign 44709 -- test mode should send
    # only the FIRST of them, not both.
    leads_df = pd.DataFrame([
        {"CID": "120022", "Email": "a@x.com"},
        {"CID": "120021", "Email": "b@x.com"},
        {"CID": "120028", "Email": "c@x.com"},
    ])
    cid_to_campaign_id = {"120022": "44709", "120021": "44709", "120028": "44706"}

    send_df, skip_df = select_rows_for_test_mode(leads_df, "CID", cid_to_campaign_id)

    assert list(send_df["Email"]) == ["a@x.com", "c@x.com"]
    assert list(skip_df["Email"]) == ["b@x.com"]


def test_select_rows_for_test_mode_ignores_cids_with_no_campaign_mapping():
    leads_df = pd.DataFrame([{"CID": "999999", "Email": "a@x.com"}])

    send_df, skip_df = select_rows_for_test_mode(leads_df, "CID", {})

    assert send_df.empty
    assert skip_df.empty


def test_select_rows_for_test_mode_preserves_original_dataframe_index():
    leads_df = pd.DataFrame(
        [{"CID": "120022", "Email": "a@x.com"}, {"CID": "120022", "Email": "b@x.com"}],
        index=[10, 11],
    )

    send_df, skip_df = select_rows_for_test_mode(leads_df, "CID", {"120022": "44709"})

    assert list(send_df.index) == [10]
    assert list(skip_df.index) == [11]


def test_pending_leads_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    assert load_pending_leads("Amazon Business EMEA") == {}

    save_pending_leads("Amazon Business EMEA", {"1": {"Email": "a@x.com", "CID": "120022"}})
    assert load_pending_leads("Amazon Business EMEA") == {"1": {"Email": "a@x.com", "CID": "120022"}}

    save_pending_leads("Amazon Business EMEA", {"2": {"Email": "b@x.com", "CID": "120028"}})
    assert load_pending_leads("Amazon Business EMEA") == {
        "1": {"Email": "a@x.com", "CID": "120022"}, "2": {"Email": "b@x.com", "CID": "120028"},
    }


def test_pending_leads_scoped_per_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    save_pending_leads("Client A", {"1": {"Email": "a@x.com"}})
    assert load_pending_leads("Client B") == {}


def test_pending_leads_empty_when_no_shared_root_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_pending_leads("Amazon Business EMEA") == {}


def test_filter_already_uploaded_splits_by_normalized_email():
    leads_df = pd.DataFrame([
        {"Email": "A@x.com", "CID": "1"},
        {"Email": " b@x.com ", "CID": "2"},
        {"Email": "c@x.com", "CID": "3"},
    ])

    send_df, dup_df = filter_already_uploaded(leads_df, "Email", {"a@x.com", "b@x.com"})

    assert list(send_df["Email"]) == ["c@x.com"]
    assert list(dup_df["Email"]) == ["A@x.com", " b@x.com "]


def test_filter_already_uploaded_preserves_original_dataframe_index():
    leads_df = pd.DataFrame(
        [{"Email": "a@x.com"}, {"Email": "b@x.com"}], index=[10, 11],
    )

    send_df, dup_df = filter_already_uploaded(leads_df, "Email", {"a@x.com"})

    assert list(dup_df.index) == [10]
    assert list(send_df.index) == [11]


def test_uploaded_emails_round_trip_and_normalizes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    assert load_uploaded_emails("Amazon Business EMEA") == set()

    save_uploaded_emails("Amazon Business EMEA", {" A@X.com ", "b@x.com"})
    assert load_uploaded_emails("Amazon Business EMEA") == {"a@x.com", "b@x.com"}

    save_uploaded_emails("Amazon Business EMEA", {"c@x.com"})
    assert load_uploaded_emails("Amazon Business EMEA") == {"a@x.com", "b@x.com", "c@x.com"}


def test_uploaded_emails_empty_when_no_shared_root_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_uploaded_emails("Amazon Business EMEA") == set()


def test_remove_pending_leads_drops_only_the_given_ids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    save_pending_leads("Amazon Business EMEA", {
        "1": {"Email": "a@x.com"}, "2": {"Email": "b@x.com"}, "3": {"Email": "c@x.com"},
    })
    remove_pending_leads("Amazon Business EMEA", ["1", "3"])

    assert load_pending_leads("Amazon Business EMEA") == {"2": {"Email": "b@x.com"}}
