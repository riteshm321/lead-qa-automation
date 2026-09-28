import os

from streamlit.testing.v1 import AppTest

from core.client_picker import group_profile_names


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
