import pandas as pd

from core.app_settings import save_app_settings
from core.integrate_sync import filter_already_uploaded, load_uploaded_emails, save_uploaded_emails


def test_filter_already_uploaded_splits_by_normalized_email():
    df = pd.DataFrame([
        {"Email": "A@x.com", "First": "A"},
        {"Email": "b@x.com", "First": "B"},
    ])
    to_send, already_sent = filter_already_uploaded(df, "Email", {"a@x.com"})
    assert list(to_send["First"]) == ["B"]
    assert list(already_sent["First"]) == ["A"]


def test_save_and_load_uploaded_emails_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    assert load_uploaded_emails("Everpure EMEA") == set()
    save_uploaded_emails("Everpure EMEA", {"A@x.com", "b@x.com"})
    assert load_uploaded_emails("Everpure EMEA") == {"a@x.com", "b@x.com"}

    # A second save merges with, doesn't replace, what's already there.
    save_uploaded_emails("Everpure EMEA", {"c@x.com"})
    assert load_uploaded_emails("Everpure EMEA") == {"a@x.com", "b@x.com", "c@x.com"}
