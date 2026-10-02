"""The Jira greeting/reporter shared by Run Check and the upload portals
(core/jira_summary.py). All data here is synthetic."""
import os

import openpyxl
import pandas as pd
from streamlit.testing.v1 import AppTest

from core.app_settings import get_clients_dir, save_app_settings
from core.jira_summary import jira_greeting, jira_reporter_name
from core.models import (
    ClientProfile, ConvertrConfig, DuplicateConfig, EnhancioAllocationMapping, EnhancioConfig, FieldMapping,
)
from core.pipeline import PipelineResult
from core.profile_store import load_profile, save_profile

_PAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages")
_CLIENT = "Synthetic Jira Client"


def test_greeting_names_the_reporter_or_falls_back_to_a_plain_hi():
    assert jira_greeting("Jane") == "Hi Jane,"
    assert jira_greeting("") == "Hi,"


def test_reporter_name_comes_from_the_client_profile():
    assert jira_reporter_name(ClientProfile(name="X", accumulated_report_path="", jira_reporter_name="Jane")) == "Jane"
    assert jira_reporter_name(ClientProfile(name="X", accumulated_report_path="")) == ""


def _save_client(acc_path: str, reporter: str) -> None:
    save_profile(ClientProfile(
        name=_CLIENT, accumulated_report_path=acc_path,
        field_mapping=FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                                   company="Company_Name", cid="CID"),
        duplicate=DuplicateConfig(enabled=True),
        jira_ticket_key="PROJ-1234", jira_reporter_name=reporter,
        convertr=ConvertrConfig(enabled=True, enterprise="ent", publisher_id="1"),
        enhancio=EnhancioConfig(enabled=True, allocations=[EnhancioAllocationMapping(cid="1", allocation_uid="L-1")]),
    ), get_clients_dir())


def _run_check_greeting() -> str:
    at = AppTest.from_file(os.path.join(_PAGES_DIR, "2_Run_Check.py"), default_timeout=15)
    at.session_state["run_new_leads"] = pd.DataFrame([
        {"Email_Address": "bob@new.example", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta",
         "CID": "1"},
    ])
    at.session_state["run_result"] = PipelineResult(valid_indices=[0], refund_reasons={})
    at.session_state["run_result_for"] = _CLIENT
    at.run()
    next(b for b in at.button if b.label == "Finalize").click().run()
    assert not at.exception
    return at.text_area(key="jira_comment_opening").value.splitlines()[0]


def test_portals_greet_the_same_reporter_as_run_check_after_the_reporter_changes(tmp_path, monkeypatch):
    # The portals' keyed Jira "Message" box used to keep whatever greeting it
    # was first drawn with (Streamlit ignores a keyed text_area's value= after
    # its first render), so once the client's reporter was changed on Client
    # Setup the portals kept greeting the old name while Run Check, which reads
    # the reporter fresh at Finalize, greeted the new one.
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    acc_path = str(tmp_path / "accumulated.xlsx")
    wb = openpyxl.Workbook()
    wb.active.title = "Accumulated"
    wb.active.append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID", "Date"])
    wb.create_sheet("Refund").append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID", "Date"])
    wb.save(acc_path)
    _save_client(acc_path, reporter="Old Reporter")

    portals = {
        "convertr_jira_message": AppTest.from_file(os.path.join(_PAGES_DIR, "7_Convertr.py"), default_timeout=15),
        "enhancio_jira_message": AppTest.from_file(os.path.join(_PAGES_DIR, "8_Enhancio.py"), default_timeout=15),
    }
    for key, at in portals.items():
        at.run()
        assert at.text_area(key=key).value.startswith("Hi Old Reporter,")

    profile = load_profile(_CLIENT, get_clients_dir())
    profile.jira_reporter_name = "Jane Reporter"
    save_profile(profile, get_clients_dir())
    os.utime(os.path.join(get_clients_dir(), f"{_CLIENT}.json"), (2_000_000_000, 2_000_000_000))

    run_check_greeting = _run_check_greeting()
    assert run_check_greeting == "Hi Jane Reporter,"
    for key, at in portals.items():
        at.run()
        assert not at.exception
        assert at.text_area(key=key).value.splitlines()[0] == run_check_greeting


def test_portal_message_picks_up_new_upload_results_after_first_render(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _save_client(str(tmp_path / "accumulated.xlsx"), reporter="Jane")

    at = AppTest.from_file(os.path.join(_PAGES_DIR, "7_Convertr.py"), default_timeout=15)
    at.run()
    assert at.text_area(key="convertr_jira_message").value == "Hi Jane,\n"

    at.session_state["convertr_upload_results"] = pd.DataFrame(
        [{"CID": "1", "Email": "a@x.example", "Result": "Uploaded — Lead ID 1"}])
    at.run()
    assert at.text_area(key="convertr_jira_message").value == \
        "Hi Jane,\nUploaded 1 lead(s) to Convertr (1 succeeded)."


def test_a_hand_edited_portal_message_is_kept_while_its_default_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _save_client(str(tmp_path / "accumulated.xlsx"), reporter="Jane")

    at = AppTest.from_file(os.path.join(_PAGES_DIR, "8_Enhancio.py"), default_timeout=15)
    at.run()
    at.text_area(key="enhancio_jira_message").input("Hi Jane,\nMy own words").run()
    at.run()
    assert at.text_area(key="enhancio_jira_message").value == "Hi Jane,\nMy own words"
