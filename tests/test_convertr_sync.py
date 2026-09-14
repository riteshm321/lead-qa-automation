from core.app_settings import save_app_settings
from core.convertr_sync import (
    classify_lead, rejection_reason, lead_field_values, lead_to_leadfile_row,
    load_synced_lead_ids, mark_leads_synced,
    save_email_to_cid_map, load_email_to_cid_map, cid_for_email,
)


def _lead(status_name: str | None, **extra) -> dict:
    lead = {"id": 1, "firstName": "Joe", "lastName": "Bloggs", "email": "j@x.com"}
    if status_name is not None:
        lead["leadStatus"] = {"name": status_name}
    lead.update(extra)
    return lead


def test_classify_lead_valid_is_accepted():
    assert classify_lead(_lead("Valid")) == "accepted"


def test_classify_lead_invalid_is_rejected():
    assert classify_lead(_lead("Invalid")) == "rejected"


def test_classify_lead_is_case_insensitive():
    assert classify_lead(_lead("VALID")) == "accepted"


def test_classify_lead_unknown_or_missing_status_is_pending():
    assert classify_lead(_lead(None)) == "pending"
    assert classify_lead(_lead("Caution")) == "pending"


def test_rejection_reason_prefers_lead_flag_reason():
    lead = _lead("Invalid", leadFlag={"reason": "Unable to Contact", "name": "Returned"})
    assert rejection_reason(lead) == "Unable to Contact"


def test_rejection_reason_falls_back_to_lead_flag_name():
    lead = _lead("Invalid", leadFlag={"name": "Returned"})
    assert rejection_reason(lead) == "Returned"


def test_rejection_reason_falls_back_to_qa_result_name():
    lead = _lead("Invalid", qaResult={"name": "Duplicate"})
    assert rejection_reason(lead) == "Duplicate"


def test_rejection_reason_generic_fallback_when_nothing_else_available():
    assert rejection_reason(_lead("Invalid")) == "Rejected by Convertr"


def test_lead_field_values_merges_core_fields_and_lead_data():
    lead = _lead("Valid", leadData=[
        {"name": "job_title", "value": "PM"},
        {"name": "cid", "value": "120022"},
    ])
    values = lead_field_values(lead)
    assert values["email"] == "j@x.com"
    assert values["job_title"] == "PM"
    assert values["cid"] == "120022"


def test_lead_field_values_core_fields_win_over_lead_data_with_same_name():
    lead = _lead("Valid", leadData=[{"name": "email", "value": "stale@old.com"}])
    assert lead_field_values(lead)["email"] == "j@x.com"


def test_lead_to_leadfile_row_maps_convertr_fields_to_leadfile_columns():
    lead = _lead("Valid", leadData=[{"name": "cid", "value": "120022"}])
    mapping = {"email": "Email", "firstName": "First Name", "cid": "CID"}

    row = lead_to_leadfile_row(lead, mapping)

    assert row == {"Email": "j@x.com", "First Name": "Joe", "CID": "120022"}


def test_lead_to_leadfile_row_blank_for_a_field_the_lead_never_carried():
    lead = _lead("Valid")
    row = lead_to_leadfile_row(lead, {"telephone": "Phone"})
    assert row == {"Phone": ""}


def test_synced_lead_ids_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    assert load_synced_lead_ids("Amazon Business EMEA") == set()

    mark_leads_synced("Amazon Business EMEA", ["1", "2"])
    assert load_synced_lead_ids("Amazon Business EMEA") == {"1", "2"}

    mark_leads_synced("Amazon Business EMEA", ["2", "3"])
    assert load_synced_lead_ids("Amazon Business EMEA") == {"1", "2", "3"}


def test_synced_lead_ids_scoped_per_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    mark_leads_synced("Client A", ["1"])
    assert load_synced_lead_ids("Client B") == set()


def test_synced_lead_ids_empty_when_no_shared_root_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_synced_lead_ids("Amazon Business EMEA") == set()


def test_email_to_cid_map_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    save_email_to_cid_map("Amazon Business EMEA", {"a@x.com": "120022", "b@x.com": "120028"})

    mapping = load_email_to_cid_map("Amazon Business EMEA")
    assert mapping == {"a@x.com": "120022", "b@x.com": "120028"}


def test_email_to_cid_map_matches_case_and_whitespace_insensitively():
    mapping = {"a@x.com": "120022"}
    assert cid_for_email("  A@X.com  ", mapping) == "120022"
    assert cid_for_email("unknown@x.com", mapping) == ""


def test_email_to_cid_map_merges_across_multiple_uploads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    save_email_to_cid_map("Amazon Business EMEA", {"a@x.com": "120022"})
    save_email_to_cid_map("Amazon Business EMEA", {"b@x.com": "120028"})

    mapping = load_email_to_cid_map("Amazon Business EMEA")
    assert mapping == {"a@x.com": "120022", "b@x.com": "120028"}


def test_email_to_cid_map_a_later_upload_overwrites_an_earlier_cid_for_the_same_email(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    save_email_to_cid_map("Amazon Business EMEA", {"a@x.com": "120022"})
    save_email_to_cid_map("Amazon Business EMEA", {"a@x.com": "120028"})

    assert load_email_to_cid_map("Amazon Business EMEA") == {"a@x.com": "120028"}
