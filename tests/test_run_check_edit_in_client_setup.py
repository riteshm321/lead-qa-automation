import os

from streamlit.testing.v1 import AppTest

from core.client_picker import ALL_GROUPS_LABEL, preselect_client_state

_SUMMARY_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Summary.py")
_RUN_CHECK = "pages/2_Run_Check.py"
_CLIENT_SETUP = "pages/1_Client_Setup.py"
_BUTTON_LABEL = "Edit in Client Setup"


def test_preselect_client_state_without_groups_sets_only_the_client_key():
    assert preselect_client_state("client_setup", "Solo", {"Solo": "", "Other": ""}) == {
        "client_setup_client_profile": "Solo"}


def test_preselect_client_state_uses_the_clients_own_group():
    groups = {"Autodesk APAC": "Autodesk", "Autodesk EMEA": "Autodesk", "Bee": ""}
    assert preselect_client_state("client_setup", "Autodesk EMEA", groups) == {
        "client_setup_group_filter": "Autodesk", "client_setup_client_profile": "Autodesk EMEA"}


def test_preselect_client_state_ungrouped_client_falls_back_to_all_groups():
    groups = {"Autodesk APAC": "Autodesk", "Bee": ""}
    assert preselect_client_state("x", "Bee", groups) == {
        "x_group_filter": ALL_GROUPS_LABEL, "x_client_profile": "Bee"}


def test_preselect_client_state_unknown_client_returns_nothing():
    assert preselect_client_state("x", "Gone", {"Bee": "G"}) == {}


def _save(tmp_path, profiles):
    from core.app_settings import get_clients_dir, save_app_settings
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    for name, (path, group) in profiles.items():
        save_profile(ClientProfile(name=name, accumulated_report_path=path, client_group=group),
                     get_clients_dir())


def _open_run_check():
    at = AppTest.from_file(_SUMMARY_PATH, default_timeout=30)
    at.run()
    at.switch_page(_RUN_CHECK).run()
    assert not at.exception
    return at


def _click_edit_button(at):
    next(b for b in at.button if b.label == _BUTTON_LABEL).click().run()
    assert not at.exception


def _assert_client_setup_shows(at, name, path, group=None):
    mode = next(r for r in at.radio if r.label == "Mode")
    assert mode.value == "Edit existing client"
    assert at.selectbox(key="client_setup_client_profile").value == name
    if group is not None:
        assert at.selectbox(key="client_setup_group_filter").value == group
    assert next(t for t in at.text_input if t.label == "Client name").value == name
    assert at.text_input(key="accumulated_path_input").value == path
    assert at.session_state["_loaded_sources_for"] == f"Edit existing client::{name}"


def test_edit_button_opens_client_setup_on_the_same_client_without_groups(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save(tmp_path, {"Alpha": ("alpha.xlsx", ""), "Beta": ("beta.xlsx", ""), "Gamma": ("gamma.xlsx", "")})
    at = _open_run_check()
    at.selectbox(key="run_check_client_profile").set_value("Beta").run()

    _click_edit_button(at)

    _assert_client_setup_shows(at, "Beta", "beta.xlsx")
    assert not any(b.label == _BUTTON_LABEL for b in at.button)


def test_edit_button_opens_client_setup_on_the_same_client_with_groups(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save(tmp_path, {"Alpha One": ("alpha1.xlsx", "Group A"), "Alpha Two": ("alpha2.xlsx", "Group A"),
                     "Beta One": ("beta1.xlsx", "Group B"), "Beta Two": ("beta2.xlsx", "Group B"),
                     "Loner": ("loner.xlsx", "")})
    at = _open_run_check()
    at.selectbox(key="run_check_group_filter").set_value("Group B").run()
    at.selectbox(key="run_check_client_profile").set_value("Beta Two").run()

    _click_edit_button(at)

    _assert_client_setup_shows(at, "Beta Two", "beta2.xlsx", group="Group B")
    assert at.selectbox(key="client_group_select").value == "Group B"


def test_edit_button_ungrouped_client_among_groups(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save(tmp_path, {"Alpha One": ("alpha1.xlsx", "Group A"), "Loner": ("loner.xlsx", "")})
    at = _open_run_check()
    at.selectbox(key="run_check_client_profile").set_value("Loner").run()

    _click_edit_button(at)

    _assert_client_setup_shows(at, "Loner", "loner.xlsx", group=ALL_GROUPS_LABEL)
    assert at.selectbox(key="client_group_select").value == ""


def test_edit_button_overrides_a_previous_client_setup_visit(tmp_path, monkeypatch):
    # Client Setup's widgets (Mode radio, group filter, client box, config
    # fields) already exist in session_state from an earlier visit showing a
    # DIFFERENT client in a different group -- the jump must still land on
    # Run Check's client with that client's saved values, nothing stale.
    monkeypatch.chdir(tmp_path)
    _save(tmp_path, {"Alpha One": ("alpha1.xlsx", "Group A"), "Alpha Two": ("alpha2.xlsx", "Group A"),
                     "Beta One": ("beta1.xlsx", "Group B"), "Beta Two": ("beta2.xlsx", "Group B")})
    at = AppTest.from_file(_SUMMARY_PATH, default_timeout=30)
    at.run()
    at.switch_page(_CLIENT_SETUP).run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    at.selectbox(key="client_setup_group_filter").set_value("Group A").run()
    at.selectbox(key="client_setup_client_profile").set_value("Alpha Two").run()
    assert at.text_input(key="accumulated_path_input").value == "alpha2.xlsx"

    at.switch_page(_RUN_CHECK).run()
    assert not at.exception
    at.selectbox(key="run_check_group_filter").set_value("Group B").run()
    at.selectbox(key="run_check_client_profile").set_value("Beta One").run()
    _click_edit_button(at)

    _assert_client_setup_shows(at, "Beta One", "beta1.xlsx", group="Group B")
    assert at.selectbox(key="client_group_select").value == "Group B"


def test_edit_button_overrides_a_previous_create_mode_visit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save(tmp_path, {"Alpha": ("alpha.xlsx", ""), "Beta": ("beta.xlsx", "")})
    at = AppTest.from_file(_SUMMARY_PATH, default_timeout=30)
    at.run()
    at.switch_page(_CLIENT_SETUP).run()
    assert next(r for r in at.radio if r.label == "Mode").value == "Create new client"

    at.switch_page(_RUN_CHECK).run()
    at.selectbox(key="run_check_client_profile").set_value("Alpha").run()
    _click_edit_button(at)

    _assert_client_setup_shows(at, "Alpha", "alpha.xlsx")


def test_edit_button_hidden_when_no_client_profiles(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    at = _open_run_check()
    assert not any(b.label == _BUTTON_LABEL for b in at.button)
