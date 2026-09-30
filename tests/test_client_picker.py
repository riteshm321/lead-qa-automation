import os

from streamlit.testing.v1 import AppTest

from core.client_picker import NEW_GROUP_SENTINEL, group_choices, group_filter_options, profiles_in_group


_MIXED = {"Autodesk EMEA": "Autodesk", "Autodesk APAC": "Autodesk", "zeta solo": "", "Beta": "bravo"}


def test_group_filter_options_lists_all_then_groups_then_ungrouped():
    assert group_filter_options(_MIXED) == ["All groups", "Autodesk", "bravo", "Ungrouped"]


def test_group_filter_options_omits_ungrouped_when_everyone_is_grouped():
    assert group_filter_options({"A": "G1", "B": "g0"}) == ["All groups", "g0", "G1"]


def test_group_filter_options_empty_when_no_groups():
    assert group_filter_options({"A": "", "B": ""}) == []
    assert group_filter_options({}) == []


def test_profiles_in_group_filters_and_sorts():
    assert profiles_in_group(_MIXED, "All groups") == ["Autodesk APAC", "Autodesk EMEA", "Beta", "zeta solo"]
    assert profiles_in_group(_MIXED, "Autodesk") == ["Autodesk APAC", "Autodesk EMEA"]
    assert profiles_in_group(_MIXED, "Ungrouped") == ["zeta solo"]


def _save(tmp_path, profiles):
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    for name, group in profiles.items():
        save_profile(ClientProfile(name=name, accumulated_report_path="a.xlsx", client_group=group),
                     get_clients_dir())


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


def test_groups_render_group_filter_then_filtered_client_box(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save(tmp_path, {"Autodesk APAC": "Autodesk", "Autodesk EMEA": "Autodesk", "Solo": "", "Bee": "Bravo"})

    at = AppTest.from_file(_write_host_script(tmp_path), default_timeout=15)
    at.run()
    assert not at.exception
    assert [s.label for s in at.selectbox] == ["Group", "Client"]
    group_box = at.selectbox(key="test_group_filter")
    assert group_box.options == ["All groups", "Autodesk", "Bravo", "Ungrouped"]
    assert group_box.value == "All groups"
    assert at.selectbox(key="test_client_profile").options == ["Autodesk APAC", "Autodesk EMEA", "Bee", "Solo"]

    group_box.set_value("Autodesk").run()
    assert not at.exception
    assert at.selectbox(key="test_client_profile").options == ["Autodesk APAC", "Autodesk EMEA"]
    at.selectbox(key="test_client_profile").set_value("Autodesk EMEA").run()
    assert at.session_state["picked"] == "Autodesk EMEA"

    at.selectbox(key="test_group_filter").set_value("Ungrouped").run()
    assert not at.exception
    assert at.selectbox(key="test_client_profile").options == ["Solo"]
    assert at.session_state["picked"] == "Solo"

    at.selectbox(key="test_group_filter").set_value("All groups").run()
    assert not at.exception
    assert at.selectbox(key="test_client_profile").options == ["Autodesk APAC", "Autodesk EMEA", "Bee", "Solo"]


def test_switching_group_falls_back_to_first_client_of_new_group(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save(tmp_path, {"Autodesk APAC": "Autodesk", "Autodesk EMEA": "Autodesk", "Bee": "Bravo"})

    at = AppTest.from_file(_write_host_script(tmp_path), default_timeout=15)
    at.run()
    at.selectbox(key="test_client_profile").set_value("Autodesk EMEA").run()
    at.selectbox(key="test_group_filter").set_value("Bravo").run()
    assert not at.exception
    assert at.selectbox(key="test_client_profile").value == "Bee"
    assert at.session_state["picked"] == "Bee"


def test_switching_group_auto_selects_and_displays_new_groups_first_client(tmp_path, monkeypatch):
    # Regression test: after changing Group, the Client box kept DISPLAYING
    # the previously picked client while the page loaded a different
    # profile. The new group's first client must be the widget's value, be
    # pushed to the browser (set_value), and be what the picker returns --
    # with no manual Client pick.
    monkeypatch.chdir(tmp_path)
    _save(tmp_path, {"Alpha One": "Group A", "Alpha Two": "Group A", "Beta One": "Group B", "Beta Two": "Group B"})

    at = AppTest.from_file(_write_host_script(tmp_path), default_timeout=15)
    at.run()
    at.selectbox(key="test_group_filter").set_value("Group A").run()
    at.selectbox(key="test_client_profile").set_value("Alpha Two").run()
    assert at.session_state["picked"] == "Alpha Two"

    at.selectbox(key="test_group_filter").set_value("Group B").run()
    assert not at.exception
    client_box = at.selectbox(key="test_client_profile")
    assert client_box.options == ["Beta One", "Beta Two"]
    assert client_box.value == "Beta One"
    assert client_box.proto.set_value is True
    assert at.session_state["picked"] == "Beta One"


def test_group_and_client_selectboxes_are_plain_dropdowns(tmp_path, monkeypatch):
    # filter_mode=None disables type-to-filter so the boxes behave like
    # dropdowns rather than editable text fields.
    monkeypatch.chdir(tmp_path)
    _save(tmp_path, {"Alpha One": "Group A", "Beta One": "Group B"})
    at = AppTest.from_file(_write_host_script(tmp_path), default_timeout=15)
    at.run()
    from streamlit.proto.SelectWidgetFilterMode_pb2 import SelectWidgetFilterMode
    assert len(at.selectbox) == 2
    for box in at.selectbox:
        assert box.proto.filter_mode == SelectWidgetFilterMode.FILTER_MODE_NONE, box.label


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


def test_singleton_group_still_lists_the_profile_by_its_own_name(tmp_path, monkeypatch):
    # A profile assigned to a group with no siblings yet still appears
    # under its own exact name in the Client box.
    monkeypatch.chdir(tmp_path)
    _save(tmp_path, {"Autodesk EMEA": "Autodesk"})

    at = AppTest.from_file(_write_host_script(tmp_path), default_timeout=15)
    at.run()
    assert not at.exception
    assert at.selectbox(key="test_group_filter").options == ["All groups", "Autodesk"]
    assert at.selectbox(key="test_client_profile").options == ["Autodesk EMEA"]
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
