import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "1_Client_Setup.py")


def test_browse_button_does_not_raise_session_state_exception(tmp_path, monkeypatch):
    # Regression test: clicking Browse used to raise StreamlitAPIException
    # ("cannot be modified after the widget ... is instantiated") because
    # the text_input with key "clients_dir_input" was created before the
    # Browse button's session_state write in script order.
    monkeypatch.chdir(tmp_path)
    fake_dir = str(tmp_path / "OneDriveShared" / "Clients")

    with patch("core.file_browser.browse_for_folder", return_value=fake_dir):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        assert not at.exception

        browse_button = next(b for b in at.button if b.key == "clients_dir_browse")
        browse_button.click().run()
        assert not at.exception

        text_input = next(t for t in at.text_input if t.key == "clients_dir_input")
        assert text_input.value == fake_dir


def test_save_button_persists_shared_root_and_migrates_aliases(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs("aliases", exist_ok=True)
    with open("aliases/company_aliases.json", "w", encoding="utf-8") as f:
        f.write('[["acme", "acme corp"]]')

    new_root = str(tmp_path / "Shared" / "LeadQA")

    with patch("core.file_browser.browse_for_folder", return_value=new_root):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()

        browse_button = next(b for b in at.button if b.key == "clients_dir_browse")
        browse_button.click().run()
        assert not at.exception

        save_button = next(b for b in at.button if b.key == "clients_dir_save")
        save_button.click().run()
        assert not at.exception

    from core.app_settings import load_app_settings, get_clients_dir, get_aliases_path
    assert load_app_settings()["shared_root_dir"] == new_root
    assert os.path.isdir(get_clients_dir())
    assert get_clients_dir() == os.path.join(new_root, "clients")
    assert os.path.isfile(get_aliases_path())
    assert get_aliases_path() == os.path.join(new_root, "aliases", "company_aliases.json")


def test_migrated_aliases_do_not_pollute_client_list_in_shared_folder(tmp_path, monkeypatch):
    # Regression test for the exact reported crash: after pointing the
    # shared team data folder at a root (which migrates company_aliases.json
    # into a subfolder under it), a real client profile saved under that
    # same root's "clients" subfolder must still be the only thing
    # list_profile_names() returns for it — mirrors the exact layout a user
    # naturally created by hand (root/clients/*.json, root/aliases/...).
    monkeypatch.chdir(tmp_path)
    os.makedirs("aliases", exist_ok=True)
    with open("aliases/company_aliases.json", "w", encoding="utf-8") as f:
        f.write('[["acme", "acme corp"]]')

    new_root = str(tmp_path / "Shared" / "LeadQA")

    with patch("core.file_browser.browse_for_folder", return_value=new_root):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        at.button(key="clients_dir_browse").click().run()
        at.button(key="clients_dir_save").click().run()
        assert not at.exception

    from core.app_settings import get_clients_dir
    from core.models import ClientProfile, FieldMapping
    from core.profile_store import save_profile, list_profile_names

    save_profile(
        ClientProfile(
            name="Real Client",
            accumulated_report_path="unused.xlsx",
            field_mapping=FieldMapping(email="e", first_name="f", last_name="l", company="c", cid="cid"),
        ),
        clients_dir=get_clients_dir(),
    )

    assert list_profile_names(clients_dir=get_clients_dir()) == ["Real Client"]


def test_saving_a_jira_ticket_link_normalizes_to_the_bare_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    next(t for t in at.text_input if t.label == "Client name").set_value("Jira Link Test Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    next(t for t in at.text_input if t.label == "Jira ticket key or link (optional)").set_value(
        "https://yourteam.atlassian.net/browse/PROJ-9876"
    ).run()

    save_button = next(b for b in at.button if "Save Client Profile" in b.label)
    save_button.click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("Jira Link Test Client", get_clients_dir())
    assert loaded.jira_ticket_key == "PROJ-9876"
