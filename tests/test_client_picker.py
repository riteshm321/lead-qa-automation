import os

from streamlit.testing.v1 import AppTest

from core.client_picker import NEW_GROUP_SENTINEL, group_choices, group_profile_names


def test_ungrouped_profile_becomes_its_own_singleton_group():
    result = group_profile_names({"Solo Client": ""})
    assert result == {"Solo Client": ["Solo Client"]}


def test_shared_group_collects_all_its_profiles_sorted():
    result = group_profile_names({
        "Autodesk EMEA": "Autodesk", "Autodesk APAC": "Autodesk", "Solo Client": "",
    })
    assert result == {
        "Autodesk": ["Autodesk APAC", "Autodesk EMEA"],
        "Solo Client": ["Solo Client"],
    }


def test_groups_are_sorted_case_insensitively():
    result = group_profile_names({"zebra corp": "", "Acme": ""})
    assert list(result.keys()) == ["Acme", "zebra corp"]


def test_empty_input_returns_empty_dict():
    assert group_profile_names({}) == {}


def _write_host_script(tmp_path) -> str:
    script = tmp_path / "_host.py"
    script.write_text(
        "import streamlit as st\n"
        "from core.app_settings import get_clients_dir\n"
        "from core.client_picker import render_client_picker\n"
        "st.session_state['picked'] = render_client_picker(get_clients_dir(), key_prefix='test')\n",
        encoding="utf-8",
    )
    return str(script)


def test_single_profile_group_renders_one_selectbox_labeled_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Solo Client", accumulated_report_path="a.xlsx"), get_clients_dir())

    at = AppTest.from_file(_write_host_script(tmp_path), default_timeout=15)
    at.run()
    assert not at.exception
    client_selectboxes = [s for s in at.selectbox if s.label == "Client"]
    assert len(client_selectboxes) == 1
    assert client_selectboxes[0].options == ["Solo Client"]
    assert at.session_state["picked"] == "Solo Client"


def test_multi_profile_group_shows_a_second_step_with_a_region_count(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Autodesk APAC", accumulated_report_path="a.xlsx",
                                client_group="Autodesk"), get_clients_dir())
    save_profile(ClientProfile(name="Autodesk EMEA", accumulated_report_path="a.xlsx",
                                client_group="Autodesk"), get_clients_dir())

    at = AppTest.from_file(_write_host_script(tmp_path), default_timeout=15)
    at.run()
    assert not at.exception
    group_box = next(s for s in at.selectbox if s.label == "Client")
    assert group_box.options == ["Autodesk (2 regions)"]

    group_box.set_value("Autodesk (2 regions)").run()
    assert not at.exception
    profile_box = next(s for s in at.selectbox if s.label == "Client (region)")
    assert set(profile_box.options) == {"Autodesk APAC", "Autodesk EMEA"}


def test_several_ungrouped_profiles_render_exactly_one_selectbox(tmp_path, monkeypatch):
    # Regression test for the deleted `len(candidates) == 1` short-circuit:
    # with 3+ ungrouped profiles, a second (region) selectbox must never
    # appear, no matter which profile is picked. Asserting on
    # `len(at.selectbox)` directly (not just the "Client"-labeled box) is
    # what catches a stray second selectbox that the old label-filtered
    # assertions couldn't see.
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    names = ["Acme Corp", "Beta Industries", "Gamma LLC"]
    for name in names:
        save_profile(
            ClientProfile(name=name, accumulated_report_path="a.xlsx"), get_clients_dir()
        )

    for name in names:
        at = AppTest.from_file(_write_host_script(tmp_path), default_timeout=15)
        at.run()
        assert not at.exception
        assert len(at.selectbox) == 1

        at.selectbox[0].set_value(name).run()
        assert not at.exception
        assert len(at.selectbox) == 1
        assert at.session_state["picked"] == name


def test_singleton_group_with_client_group_set_shows_own_name_as_label(tmp_path, monkeypatch):
    # A profile can be assigned a client_group before any sibling profile
    # in that group exists. The picker must still show the profile's own
    # name as its option -- not the abstract group key -- exactly like the
    # fully-ungrouped case.
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(
        ClientProfile(
            name="Autodesk EMEA", accumulated_report_path="a.xlsx", client_group="Autodesk"
        ),
        get_clients_dir(),
    )

    at = AppTest.from_file(_write_host_script(tmp_path), default_timeout=15)
    at.run()
    assert not at.exception
    client_selectboxes = [s for s in at.selectbox if s.label == "Client"]
    assert len(client_selectboxes) == 1
    assert client_selectboxes[0].options == ["Autodesk EMEA"]
    assert at.session_state["picked"] == "Autodesk EMEA"


def test_group_choices_lists_no_group_existing_groups_with_counts_then_create_new():
    choices = group_choices({"A APAC": "autodesk", "A EMEA": "autodesk", "S": "Solo", "U": "", "B": "Bravo"})
    assert choices == [
        ("No group", ""),
        ("autodesk (2 clients)", "autodesk"),
        ("Bravo (1 client)", "Bravo"),
        ("Solo (1 client)", "Solo"),
        ("+ Create new group…", NEW_GROUP_SENTINEL),
    ]


def test_group_choices_with_no_profiles():
    assert group_choices({}) == [("No group", ""), ("+ Create new group…", NEW_GROUP_SENTINEL)]


def test_group_choices_includes_unknown_current_group():
    choices = group_choices({"X": "Alpha"}, current_group="Ghost")
    assert ("Ghost (0 clients)", "Ghost") in choices
    assert [v for _, v in choices] == ["", "Alpha", "Ghost", NEW_GROUP_SENTINEL]
