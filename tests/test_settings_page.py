import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "3_Settings.py")


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
    monkeypatch.setattr("core.onedrive.list_onedrive_mount_points", lambda: [str(tmp_path)])

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
    monkeypatch.setattr("core.onedrive.list_onedrive_mount_points", lambda: [str(tmp_path)])

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


def test_save_button_rejects_blank_shared_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.button(key="clients_dir_save").click().run()

    assert not at.exception
    assert len(at.error) == 1
    assert "required" in at.error[0].value
    from core.app_settings import get_shared_root_dir
    assert get_shared_root_dir() == ""


def test_save_button_rejects_a_folder_not_synced_by_onedrive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("core.onedrive.list_onedrive_mount_points", lambda: [])
    not_synced = str(tmp_path / "Downloads" / "MyLeads")

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.text_input(key="clients_dir_input").set_value(not_synced).run()
    at.button(key="clients_dir_save").click().run()

    assert not at.exception
    assert len(at.error) == 1
    assert "OneDrive" in at.error[0].value
    from core.app_settings import get_shared_root_dir
    assert get_shared_root_dir() == ""


def test_save_jira_account_persists_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    at.text_input(key="jira_base_url_input").set_value("https://example.atlassian.net").run()
    at.text_input(key="jira_email_input").set_value("me@example.com").run()
    at.text_input(key="jira_api_token_input").set_value("token123").run()

    save_button = next(b for b in at.button if b.key == "jira_settings_save")
    save_button.click().run()
    assert not at.exception

    from core.app_settings import get_jira_settings
    settings = get_jira_settings()
    assert settings["base_url"] == "https://example.atlassian.net"
    assert settings["email"] == "me@example.com"
    assert settings["api_token"] == "token123"


def test_admin_can_add_a_new_user_account(tmp_path, monkeypatch):
    # tests/conftest.py's autouse bypass logs every page test in as an
    # admin, so the "Manage user accounts" panel is always available here.
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception

    username_input = next(w for w in at.text_input if w.label == "Username")
    password_input = next(w for w in at.text_input if w.label == "Password")
    role_input = next(w for w in at.text_input if w.label == "Role/Title")
    username_input.set_value("colleague")
    password_input.set_value("their-password")
    role_input.set_value("Client Reporting Specialist")
    add_button = next(b for b in at.button if b.label == "Add account")
    add_button.click().run()

    assert not at.exception
    from core.auth import load_users
    added = load_users()["colleague"]
    assert added["role"] == "Client Reporting Specialist"


def test_admin_can_edit_an_existing_users_role(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.auth import create_user
    create_user("test-admin", "irrelevant", is_admin=True)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception

    role_input = next(w for w in at.text_input if w.key == "role_edit_test-admin")
    role_input.set_value("Sr. Client Reporting Specialist").run()
    save_button = next(b for b in at.button if b.key == "role_save_test-admin")
    save_button.click().run()

    assert not at.exception
    from core.auth import load_users
    assert load_users()["test-admin"]["role"] == "Sr. Client Reporting Specialist"


def test_admin_can_save_time_baseline_and_sees_per_person_breakdown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shared_root = str(tmp_path / "shared")
    from core.app_settings import save_app_settings
    save_app_settings({"shared_root_dir": shared_root})
    from core.activity_tracker import record_process_completed
    record_process_completed("test-admin")
    record_process_completed("test-admin")

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception

    automation_input = next(n for n in at.number_input if n.key == "time_baseline_automation")
    manual_input = next(n for n in at.number_input if n.key == "time_baseline_manual")
    automation_input.set_value(5).run()
    manual_input.set_value(50).run()
    save_button = next(b for b in at.button if b.key == "time_baseline_save")
    save_button.click().run()

    assert not at.exception
    from core.activity_tracker import get_time_baseline
    assert get_time_baseline() == {"automation_minutes": 5, "manual_minutes": 50}
    assert any("test-admin" in m.value and "2 process" in m.value for m in at.markdown)


def test_cannot_remove_the_only_remaining_admin(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.auth import create_user
    create_user("test-admin", "irrelevant", is_admin=True)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception

    remove_button = next(b for b in at.button if b.key == "remove_user_test-admin")
    assert remove_button.disabled
