import datetime

import pandas as pd

from core.app_settings import save_app_settings
from core.failed_leads import (
    FAILURE_REASON_COLUMN, clear_failed_leads, failed_leads_dataframe, failed_leads_source_df,
    load_failed_leads, make_failed_entry, update_failed_leads,
)


def _entry(email, reason, **extra):
    return make_failed_entry({"Email": email, "CID": "111", **extra}, email, reason)


def test_entries_persist_on_disk_per_portal_and_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    update_failed_leads("convertr", "Client A", [_entry("a@example.com", "Boom")], set())

    assert (tmp_path / "Shared" / "convertr_failed_leads" / "Client A.json").is_file()
    assert list(load_failed_leads("convertr", "Client A")) == ["a@example.com"]
    assert load_failed_leads("convertr", "Client B") == {}
    assert load_failed_leads("enhancio", "Client A") == {}


def test_new_failure_replaces_same_email_and_success_removes_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    update_failed_leads("integrate", "C", [_entry("A@example.com", "Old"), _entry("b@example.com", "B")], set())
    update_failed_leads("integrate", "C", [_entry("a@example.com", "New")], {"B@Example.com "})

    entries = load_failed_leads("integrate", "C")
    assert list(entries) == ["a@example.com"]
    assert entries["a@example.com"]["reason"] == "New"


def test_without_a_shared_root_the_memory_dict_is_the_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    memory: dict = {}
    update_failed_leads("enhancio", "C", [_entry("a@example.com", "X")], set(), memory=memory)
    assert list(load_failed_leads("enhancio", "C", memory=memory)) == ["a@example.com"]
    clear_failed_leads("enhancio", "C", memory=memory)
    assert load_failed_leads("enhancio", "C", memory=memory) == {}


def test_clear_empties_the_disk_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    update_failed_leads("convertr", "C", [_entry("a@example.com", "X")], set())
    clear_failed_leads("convertr", "C")
    assert load_failed_leads("convertr", "C") == {}


def test_dataframe_keeps_every_original_column_and_adds_failure_reason_last(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    update_failed_leads("convertr", "C", [
        _entry("a@example.com", "Reason A", **{"First Name": "A", "Created": pd.Timestamp("2026-01-02")}),
        _entry("b@example.com", "Reason B", **{"Phone": float("nan")}),
    ], set())

    df = failed_leads_dataframe(load_failed_leads("convertr", "C"))
    assert list(df.columns) == ["Email", "CID", "First Name", "Created", "Phone", FAILURE_REASON_COLUMN]
    assert list(df[FAILURE_REASON_COLUMN]) == ["Reason A", "Reason B"]
    assert df.loc[0, "Created"] == "2026-01-02T00:00:00"
    assert df.loc[1, "Phone"] == ""

    source = failed_leads_source_df(load_failed_leads("convertr", "C"))
    assert FAILURE_REASON_COLUMN not in source.columns
    assert list(source["Email"]) == ["a@example.com", "b@example.com"]


def test_blank_email_rows_are_kept_as_separate_entries():
    e1 = make_failed_entry({"Email": "", "CID": "1"}, "", "No email")
    e2 = make_failed_entry({"Email": "", "CID": "2"}, "", "No email")
    memory: dict = {}
    update_failed_leads("integrate", "C", [e1, e2], set(), memory=memory)
    assert len(load_failed_leads("integrate", "C", memory=memory)) == 2


def test_date_values_are_json_safe():
    _, entry = make_failed_entry({"Email": "a@example.com", "D": datetime.date(2026, 1, 2)}, "a@example.com", "X")
    assert entry["row"]["D"] == "2026-01-02"
    assert entry == {"row": {"Email": "a@example.com", "D": "2026-01-02"}, "reason": "X"}
