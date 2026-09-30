import datetime
import os
from unittest.mock import patch

import openpyxl
import pandas as pd
from streamlit.testing.v1 import AppTest

from core.app_settings import get_clients_dir, save_jira_settings
from core.check_result import ReviewDetail
from core.jira_client import JiraError
from core.models import ClientProfile, FieldMapping, DuplicateConfig, LeadTemplateTab, ComplexAccountConfig
from core.models import LeadTemplateMappingConfig, LeadTemplateColumnRule
from core.models import GoogleSheetsConfig, GoogleSheetTab
from core.models import EnhancioConfig, EnhancioAllocationMapping, BoxTrackerConfig
from core.pipeline import PipelineResult, run_pipeline
from core.profile_store import save_profile

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "2_Run_Check.py")


def _make_accumulated_report(path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID", "Date"])
    ws.append(["existing@dup.com", "Existing", "Person", "DupCo", "1", "2026-08-01"])
    wb.create_sheet("Refund").append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID", "Date"])
    wb.save(path)


def test_cached_loaders_hash_their_mtime_argument():
    # Regression test for a real, confirmed bug: Streamlit's @st.cache_data
    # silently EXCLUDES any parameter whose name starts with an underscore
    # from the cache key hash. _cached_tal_index/_cached_asset_specs pass
    # os.path.getmtime(path) specifically to bust the cache when the
    # underlying file changes mid-session — naming that parameter "_mtime"
    # made Streamlit ignore it entirely, so a file edited and re-saved to
    # the same path during a running session kept silently serving the
    # first-loaded (now-stale) data. Verified by parsing the actual page
    # source (can't import a page module whose filename starts with a
    # digit) rather than re-deriving the bug in an unrelated toy function.
    import ast

    with open(_PAGE_PATH, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=_PAGE_PATH)

    checked_any = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        is_cached = any(
            (isinstance(d, ast.Call) and getattr(d.func, "attr", None) == "cache_data")
            or (isinstance(d, ast.Attribute) and d.attr == "cache_data")
            for d in node.decorator_list
        )
        if not is_cached:
            continue
        checked_any = True
        param_names = [a.arg for a in node.args.args]
        underscored = [p for p in param_names if p.startswith("_")]
        assert not underscored, (
            f"@st.cache_data function '{node.name}' has underscore-prefixed param(s) "
            f"{underscored} — Streamlit excludes these from the cache key, silently "
            f"breaking any cache-busting argument (e.g. a file's mtime) passed there."
        )

    assert checked_any, "expected at least one @st.cache_data-decorated function in this page"


def test_run_check_button_is_disabled_with_no_leadfile_uploaded(tmp_path, monkeypatch):
    # Regression test: "Run Check" used to be `if st.button("Run Check") and
    # new_leads_file:` -- clickable but a silent no-op with zero feedback
    # when nothing was uploaded yet, since the `and` just short-circuited.
    # The button must now be disabled instead, matching the Collate
    # button's existing disabled=not _collate_files pattern.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm)
    save_profile(profile, get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception

    run_check_button = next(b for b in at.button if b.label == "Run Check")
    assert run_check_button.disabled is True


def test_collation_expander_appears_only_when_enabled_and_leaves_normal_upload_intact(tmp_path, monkeypatch):
    # AppTest can't simulate a real file upload, so this only checks the
    # collation option's visibility is gated correctly and the page loads
    # without error either way -- core/collation.py's own tests cover the
    # actual collating logic.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")

    save_profile(ClientProfile(
        name="No Collation Client", accumulated_report_path=acc_path, field_mapping=fm,
    ), get_clients_dir())
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert not any("Collate multiple files" in e.label for e in at.status)

    save_profile(ClientProfile(
        name="Collation Client", accumulated_report_path=acc_path, field_mapping=fm,
        collation_enabled=True,
    ), get_clients_dir())
    at2 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at2.run()
    next(s for s in at2.selectbox if s.label == "Client").set_value("Collation Client").run()
    assert not at2.exception
    assert any("Collate multiple files" in e.label for e in at2.status)


def test_using_a_collated_file_does_not_crash_with_nameerror(tmp_path, monkeypatch):
    # Regression test for a real crash: new_leads_file was only assigned in
    # the non-collation upload branch, so a client with a collated file
    # already ready (the raw file_uploader branch never runs) crashed with
    # "NameError: name 'new_leads_file' is not defined" the moment the page
    # reached the mapping/Run Check button checks below.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    save_profile(ClientProfile(
        name="Collation Client", accumulated_report_path=acc_path, field_mapping=fm,
        collation_enabled=True,
    ), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["collated_new_leads_Collation Client"] = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "Acme", "CID": "1"},
    ])
    at.run()
    next(s for s in at.selectbox if s.label == "Client").set_value("Collation Client").run()

    assert not at.exception
    assert any("Using the collated file" in c.value for c in at.caption)


def test_collated_file_offers_a_download_button(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    save_profile(ClientProfile(
        name="Collation Client", accumulated_report_path=acc_path, field_mapping=fm,
        collation_enabled=True,
    ), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["collated_new_leads_Collation Client"] = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "Acme", "CID": "1"},
    ])
    at.run()
    next(s for s in at.selectbox if s.label == "Client").set_value("Collation Client").run()

    assert not at.exception
    download_button = next(d for d in at.download_button if d.key == "collated_download_button")
    assert download_button.label == "Download"


def test_approved_refund_lead_lands_in_accumulated_tab_not_just_refund(tmp_path, monkeypatch):
    # End-to-end regression test for the "approve a refunded lead as valid"
    # feature: AppTest can't simulate a real file upload, so this pre-seeds
    # session_state exactly as it looks right after a real Run Check click
    # (one valid lead, one refund-flagged lead), then drives the actual
    # Refund Reasons checkbox and Finalize button.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
        {"Email_Address": "existing@dup.com", "First_Name": "Existing", "Last_Name": "Person",
         "Company_Name": "DupCo", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={1: "Duplicate - exact email"})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    assert not at.exception

    # AppTest has no widget accessor for st.data_editor (and Streamlit
    # forbids writing a data_editor's own key via session_state directly),
    # so simulate "the user ticked the one refund row's checkbox" by
    # patching st.data_editor itself to return the edited table the real
    # widget would have, for this one render.
    edited_table = pd.DataFrame([{
        "Approve as valid": True, "Row": 3, "Email": "existing@dup.com",
        "Company": "DupCo", "CID": "1", "Reason": "Duplicate - exact email",
    }])
    with patch("streamlit.data_editor", return_value=edited_table):
        finalize_button = next(b for b in at.button if b.label == "Finalize")
        finalize_button.click().run()
    assert not at.exception

    wb = openpyxl.load_workbook(acc_path)
    acc_rows = [tuple(r) for r in wb["Accumulated"].iter_rows(min_row=2, values_only=True) if r[0] is not None]
    refund_rows = [tuple(r) for r in wb["Refund"].iter_rows(min_row=2, values_only=True) if r[0] is not None]

    acc_emails = {row[0] for row in acc_rows}
    refund_emails = {row[0] for row in refund_rows}

    assert "bob@new.com" in acc_emails
    assert "existing@dup.com" in acc_emails  # approved despite being auto-flagged for refund
    assert refund_emails == set()  # nothing left in Refund tab once approved


def test_review_bulk_approve_selected_leads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm)
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
        {"Email_Address": "b@x.com", "First_Name": "B", "Last_Name": "Two", "Company_Name": "Y", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[], refund_reasons={}, review_reasons={
        0: [ReviewDetail(check="Duplicate", message="reason a")],
        1: [ReviewDetail(check="Duplicate", message="reason b")],
    })

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    assert not at.exception

    # AppTest has no widget accessor for st.data_editor -- same workaround
    # as the Refund Reasons editor test above: patch it to return the
    # edited table the real widget would produce for "both rows ticked".
    edited_table = pd.DataFrame([
        {"Select": True, "Row": 2, "Email": "a@x.com", "Company": "X", "CID": "1", "Reasons": "Duplicate - reason a"},
        {"Select": True, "Row": 3, "Email": "b@x.com", "Company": "Y", "CID": "1", "Reasons": "Duplicate - reason b"},
    ])
    with patch("streamlit.data_editor", return_value=edited_table):
        bulk_approve_button = next(b for b in at.button if b.key == "review_bulk_approve")
        bulk_approve_button.click().run()
    assert not at.exception

    updated_result = at.session_state["run_result"]
    assert sorted(updated_result.valid_indices) == [0, 1]
    assert updated_result.review_reasons == {}


def test_review_download_button_and_refund_download_button_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm)
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
        {"Email_Address": "b@x.com", "First_Name": "B", "Last_Name": "Two", "Company_Name": "Y", "CID": "1"},
    ])
    result = PipelineResult(
        valid_indices=[], refund_reasons={0: "Duplicate - exact email"},
        review_reasons={1: [ReviewDetail(check="Duplicate", message="reason b")]},
    )

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    assert not at.exception
    # Both buttons show the same short "Download" label (a longer label
    # naming what it downloads made the button too wide) -- distinguished
    # by key instead, since AppTest can't tell them apart by label alone.
    download_keys = {d.key for d in at.download_button}
    assert "refund_download_button" in download_keys
    assert "review_download_button" in download_keys
    assert all(d.label == "Download" for d in at.download_button)

    # The old per-lead expander detail view is gone -- the bulk-select
    # table above is the only Needs Review UI now.
    assert not any("Excel row" in str(e.label) for e in at.expander)
    assert not any(b.key == "approve_1" for b in at.button)


def test_unapproved_refund_lead_stays_refund_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "existing@dup.com", "First_Name": "Existing", "Last_Name": "Person",
         "Company_Name": "DupCo", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[], refund_reasons={0: "Duplicate - exact email"})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    # Leave the checkbox unticked and finalize directly.
    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    wb = openpyxl.load_workbook(acc_path)
    acc_rows = [r for r in wb["Accumulated"].iter_rows(min_row=2, values_only=True) if r[0] is not None]
    refund_rows = [r for r in wb["Refund"].iter_rows(min_row=2, values_only=True) if r[0] is not None]

    assert len(acc_rows) == 1  # only the pre-existing accumulated row, nothing new added
    assert len(refund_rows) == 1
    assert refund_rows[0][0] == "existing@dup.com"


def test_successful_finalize_records_a_completed_process_for_the_logged_in_user(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shared_root = str(tmp_path / "shared")
    from core.app_settings import save_app_settings
    save_app_settings({"shared_root_dir": shared_root})
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm)
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    from core.activity_tracker import load_all_activity
    activity = load_all_activity()
    # tests/conftest.py's autouse login bypass logs every page test in as
    # "test-admin" -- that's who the completed process must be attributed to.
    assert activity["test-admin"]["process_count"] == 1


def test_finalize_for_convertr_client_skips_accumulated_but_still_writes_refund(tmp_path, monkeypatch):
    # Convertr-enabled clients hold valid leads back from Accumulated on
    # Finalize -- they still have to go through Convertr (and often a
    # client job-title review in between) before being accepted/rejected;
    # only the Convertr Reconcile step writes Accumulated/Refund for those.
    # QA-failed (refund) leads are unrelated to Convertr and still write
    # to Refund immediately, same as any other client.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    from core.models import ConvertrConfig

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
        convertr=ConvertrConfig(enabled=True, enterprise="amazonbusiness"),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "valid@new.com", "First_Name": "V", "Last_Name": "Lid", "Company_Name": "X", "CID": "1"},
        {"Email_Address": "existing@dup.com", "First_Name": "Existing", "Last_Name": "Person",
         "Company_Name": "DupCo", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={1: "Duplicate - exact email"})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    assert "valid@new.com" not in accumulated_df["Email_Address"].values  # not written yet

    refund_df = pd.read_excel(acc_path, sheet_name="Refund")
    assert "existing@dup.com" in refund_df["Email_Address"].values  # QA-failed leads still write immediately

    assert any("Valid leads ready for Convertr" in s.value for s in at.subheader)
    assert any(d.label == "Download valid leads" for d in at.download_button)


def test_finalize_for_enhancio_client_skips_accumulated_and_downloads_valid_leads(tmp_path, monkeypatch):
    # Same behavior as Convertr must hold for Enhancio -- the shared
    # _finalize_write() helper used to check only profile.convertr.enabled,
    # so an Enhancio-only client's valid leads were written straight to
    # Accumulated on Finalize instead of being held back for Upload +
    # Reconcile like Convertr's leads already correctly were.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        enhancio=EnhancioConfig(enabled=True, allocations=[EnhancioAllocationMapping(cid="1", allocation_uid="L-1")]),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "valid@new.com", "First_Name": "V", "Last_Name": "Lid", "Company_Name": "X", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    assert "valid@new.com" not in accumulated_df["Email_Address"].values  # not written yet

    assert any("Valid leads ready for Enhancio" in s.value for s in at.subheader)
    assert any(d.label == "Download valid leads" for d in at.download_button)


def test_complex_account_finalize_skips_accumulated_and_downloads_when_enhancio_enabled(tmp_path, monkeypatch):
    # The same "hold back for the upload tool" behavior must also hold on
    # the Complex Account two-stage Finalize path (Finalize (fill columns)
    # -> Confirm & Write), which shares _finalize_write() with the plain
    # single-step Finalize button above.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Email", "First", "Last", "Company", "CID"])
    wb.create_sheet("Refund").append(["Email", "First", "Last", "Company", "CID"])
    wb.save(acc_path)

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        complex_account=ComplexAccountConfig(enabled=True),
        enhancio=EnhancioConfig(enabled=True, allocations=[EnhancioAllocationMapping(cid="1", allocation_uid="L-1")]),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email": "a@wipro.com", "First": "A", "Last": "One", "Company": "Wipro", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    assert not at.exception

    next(b for b in at.button if b.label == "Finalize (fill columns)").click().run()
    assert not at.exception

    confirm_button = next(b for b in at.button if b.label == "Confirm & Write")
    confirm_button.click().run()
    assert not at.exception

    # Still just the header row -- held back for Enhancio, not written here.
    wb_after = openpyxl.load_workbook(acc_path)
    assert wb_after["Accumulated"].max_row == 1

    assert any("Valid leads ready for Enhancio" in s.value for s in at.subheader)
    assert any(d.label == "Download valid leads" for d in at.download_button)


def test_complex_account_finalize_writes_to_accumulated_for_a_box_tracker_client(tmp_path, monkeypatch):
    # Regression test: IBM APAC (Complex Account + Enhancio enabled, same
    # setup as the test above) reported Confirm & Write leaving Accumulated
    # empty -- by design at the time, since ANY Enhancio-enabled client held
    # valid leads back for Enhancio's own Upload + Reconcile. But IBM APAC's
    # real approval pipeline is Finalize -> Accumulated -> Box Tracker
    # (client approval) -> Enhancio, pulled later from Accumulated by date
    # range -- it never feeds Enhancio from Finalize's diverted output at
    # all, so diverting it away here just meant it silently never reached
    # Accumulated. A Box Tracker client (identified by box_tracker.enabled)
    # must write straight to Accumulated on Confirm & Write regardless of
    # Enhancio being enabled.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Email", "First", "Last", "Company", "CID"])
    wb.create_sheet("Refund").append(["Email", "First", "Last", "Company", "CID"])
    wb.save(acc_path)

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        complex_account=ComplexAccountConfig(enabled=True),
        enhancio=EnhancioConfig(enabled=True, allocations=[EnhancioAllocationMapping(cid="1", allocation_uid="L-1")]),
        box_tracker=BoxTrackerConfig(enabled=True),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email": "a@wipro.com", "First": "A", "Last": "One", "Company": "Wipro", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    assert not at.exception

    next(b for b in at.button if b.label == "Finalize (fill columns)").click().run()
    assert not at.exception

    confirm_button = next(b for b in at.button if b.label == "Confirm & Write")
    confirm_button.click().run()
    assert not at.exception

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    assert "a@wipro.com" in accumulated_df["Email"].values  # written immediately, not held back
    assert not any(d.label == "Download valid leads" for d in at.download_button)


def test_select_all_as_valid_approves_every_refund_lead(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
        {"Email_Address": "b@x.com", "First_Name": "B", "Last_Name": "Two", "Company_Name": "X", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[], refund_reasons={0: "Exclusion - domain", 1: "Exclusion - domain"})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    select_all = next(b for b in at.button if b.label == "Select all as valid")
    select_all.click().run()
    assert not at.exception

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    wb = openpyxl.load_workbook(acc_path)
    acc_emails = {r[0] for r in wb["Accumulated"].iter_rows(min_row=2, values_only=True) if r[0] is not None}
    refund_rows = [r for r in wb["Refund"].iter_rows(min_row=2, values_only=True) if r[0] is not None]

    assert {"a@x.com", "b@x.com"} <= acc_emails
    assert refund_rows == []


def test_post_summary_to_jira_after_finalize(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    save_jira_settings("https://example.atlassian.net", "me@example.com", "token123")

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
        jira_ticket_key="PROJ-1234",
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    # The "Post to Jira" prompt should now be showing, pre-filled with a
    # summary — verify it before actually posting anything.
    import datetime as _dt
    opening_box = next(t for t in at.text_area if t.key == "jira_comment_opening")
    assert _dt.date.today().strftime("%d-%m-%y") in opening_box.value
    assert "PFB summary for the Lead QA dated" in opening_box.value
    closing_box = next(t for t in at.text_area if t.key == "jira_comment_closing")
    assert closing_box.value == "Thanks"

    # The Accumulated File link checkbox should be offered (ticked by default).
    link_checkbox = next(c for c in at.checkbox if c.key == "jira_link_Accumulated File")
    assert link_checkbox.value is True

    with patch("core.jira_client.post_comment_body") as mock_post:
        post_button = next(b for b in at.button if b.key == "jira_post_button")
        post_button.click().run()
        assert not at.exception

    mock_post.assert_called_once()
    call_args = mock_post.call_args[0]
    assert call_args[0] == "https://example.atlassian.net"
    assert call_args[1] == "me@example.com"
    assert call_args[2] == "token123"
    assert call_args[3] == "PROJ-1234"
    adf_body = call_args[4]
    assert adf_body["type"] == "doc"
    # The file link should show up as a real ADF link mark, not plain text.
    all_marks = [
        mark
        for node in adf_body["content"] if node["type"] == "orderedList"
        for item in node["content"]
        for para in item["content"]
        for text_node in para["content"]
        for mark in text_node.get("marks", [])
    ]
    assert any(mark["type"] == "link" for mark in all_marks)

    # Session state cleaned up so the prompt disappears after a successful post.
    assert "last_finalized_summary" not in at.session_state


def test_jira_post_uploads_provided_attachment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    save_jira_settings("https://example.atlassian.net", "me@example.com", "token123")

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True), jira_ticket_key="PROJ-1234",
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    # Simulate a file already selected via st.file_uploader (AppTest can't
    # drive a real file upload — see the established limitation noted
    # elsewhere in this suite) by pre-seeding what the uploader branch
    # writes into session_state.
    at.session_state["jira_attachment_bytes"] = b"fake-file-bytes"
    at.session_state["jira_attachment_name"] = "notes.txt"

    with patch("core.jira_client.post_comment_body") as mock_post_comment, \
         patch("core.jira_client.upload_attachment") as mock_upload:
        post_button = next(b for b in at.button if b.key == "jira_post_button")
        post_button.click().run()
        assert not at.exception

    mock_post_comment.assert_called_once()
    mock_upload.assert_called_once()
    assert mock_upload.call_args[0][4] == "notes.txt"
    assert mock_upload.call_args[0][5] == b"fake-file-bytes"
    assert "jira_attachment_bytes" not in at.session_state


def test_jira_post_reports_attachment_failure_without_blocking_comment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    save_jira_settings("https://example.atlassian.net", "me@example.com", "token123")

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True), jira_ticket_key="PROJ-1234",
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    # This test drives more sequential button-click+rerun cycles than any
    # other in this file (Finalize, post, retry), which occasionally brushes
    # up against AppTest's default wait window under momentary system load —
    # a longer timeout here is slack for the test harness, not a change to
    # the app's own behavior.
    at = AppTest.from_file(_PAGE_PATH, default_timeout=30)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    at.session_state["jira_attachment_bytes"] = b"fake-file-bytes"
    at.session_state["jira_attachment_name"] = "notes.txt"

    with patch("core.jira_client.post_comment_body") as mock_post_comment, \
         patch("core.jira_client.upload_attachment", side_effect=JiraError("boom")):
        post_button = next(b for b in at.button if b.key == "jira_post_button")
        post_button.click().run()
        assert not at.exception

    mock_post_comment.assert_called_once()
    assert any("boom" in e.value for e in at.error)
    # The comment succeeded, so its success message must still show, and
    # last_finalized_summary must stay put so the retry button can appear.
    assert any("Posted to PROJ-1234" in s.value for s in at.success)
    assert "last_finalized_summary" in at.session_state

    # Retrying must not repost the comment — only the failed attachment.
    with patch("core.jira_client.post_comment_body") as mock_post_comment_retry, \
         patch("core.jira_client.upload_attachment") as mock_upload_retry:
        retry_button = next(b for b in at.button if b.key == "jira_post_button")
        assert "Retry failed attachment" in retry_button.label
        retry_button.click().run()
        assert not at.exception

    mock_post_comment_retry.assert_not_called()
    mock_upload_retry.assert_called_once()
    assert "last_finalized_summary" not in at.session_state


def test_jira_prompt_does_not_appear_without_ticket_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    assert not any(t.key == "jira_comment_opening" for t in at.text_area)


def test_post_summary_to_jira_includes_pacing_overview_as_native_table(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    save_jira_settings("https://example.atlassian.net", "me@example.com", "token123")

    wb = openpyxl.load_workbook(acc_path)
    pacing = wb.create_sheet("Pacing Overview")
    pacing.append(["SR No", "CID", "Campaign Segment"])
    pacing.append([1, "118118", "APAC Mgr+ Q3"])
    pacing.append([2, "118119", "EMEA Mgr+ Q3"])
    wb.save(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
        jira_ticket_key="PROJ-1234",
        jira_reporter_name="Jane",
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    opening_box = next(t for t in at.text_area if t.key == "jira_comment_opening")
    assert "Hi Jane" in opening_box.value

    pacing_checkbox = next(c for c in at.checkbox if c.key == "jira_include_pacing")
    assert pacing_checkbox.value is True

    with patch("core.jira_client.post_comment_body") as mock_post:
        post_button = next(b for b in at.button if b.key == "jira_post_button")
        post_button.click().run()
        assert not at.exception

    adf_body = mock_post.call_args[0][4]
    table_nodes = [n for n in adf_body["content"] if n["type"] == "table"]
    assert len(table_nodes) == 1
    header_row = table_nodes[0]["content"][0]
    header_texts = [c["content"][0]["content"][0]["text"] for c in header_row["content"]]
    assert header_texts == ["SR No", "CID", "Campaign Segment"]
    data_row_1 = table_nodes[0]["content"][1]
    assert data_row_1["content"][1]["content"][0]["content"][0]["text"] == "118118"


def test_jira_summary_includes_lead_report_link_for_lead_qa_mode_with_template(tmp_path, monkeypatch):
    # Regression test: the "Lead Report" file link must key off client_mode
    # == "Lead QA" (the mode that actually has lead_template_path set —
    # counterintuitively, "Lead QA & Upload" mode has no Lead Template at
    # all), not "Lead QA & Upload".
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    template_path = str(tmp_path / "lead_report.xlsx")
    wb = openpyxl.Workbook()
    wb.active.append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID"])
    wb.save(template_path)
    save_jira_settings("https://example.atlassian.net", "me@example.com", "token123")

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
        jira_ticket_key="PROJ-1234",
        client_mode="Lead QA",
        lead_template_path=template_path,
        lead_template_sheet_name="Sheet",
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    assert any(c.key == "jira_link_Lead Report" for c in at.checkbox)


def test_finalize_writes_to_a_csv_lead_template(tmp_path, monkeypatch):
    # Regression test for a real production incident (Intel APAC, a plain
    # "Lead QA" client): Confirm & Write crashed with "openpyxl does not
    # support .csv file format" right after the (unaffected, .xlsx)
    # Accumulated Report had already been backed up and updated -- the
    # Lead Template write has no CSV branch at all. Confirmed live.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    template_path = str(tmp_path / "template.csv")
    (tmp_path / "template.csv").write_text(
        "Email_Address,First_Name,Last_Name,Company_Name,CID\n", encoding="utf-8")

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        client_mode="Lead QA",
        lead_template_path=template_path,
        lead_template_sheet_name="(CSV file)",
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    result_df = pd.read_csv(template_path, dtype=str, keep_default_na=False)
    assert "bob@new.com" in result_df["Email_Address"].values


def test_jira_summary_omits_lead_report_link_for_lead_qa_and_upload_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    save_jira_settings("https://example.atlassian.net", "me@example.com", "token123")

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
        jira_ticket_key="PROJ-1234",
        client_mode="Lead QA & Upload",
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    assert not any(c.key == "jira_link_Lead Report" for c in at.checkbox)
    assert any(c.key == "jira_link_Accumulated File" for c in at.checkbox)


def test_multi_tab_routes_different_cids_to_completely_different_files(tmp_path, monkeypatch):
    # End-to-end regression test for per-CID Lead Template files: some CID
    # groups go to a totally different workbook, not just another tab in
    # the same one.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    shared_path = str(tmp_path / "shared_template.xlsx")
    wb = openpyxl.Workbook()
    apac = wb.active
    apac.title = "APAC"
    apac.append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID"])
    wb.save(shared_path)

    emea_only_path = str(tmp_path / "emea_only.xlsx")
    wb2 = openpyxl.Workbook()
    emea = wb2.active
    emea.title = "EMEA"
    emea.append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID"])
    wb2.save(emea_only_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        client_mode="Lead QA",
        lead_template_path=shared_path,
        lead_template_multi_tab=True,
        lead_template_tabs=[
            LeadTemplateTab(sheet_name="APAC", cids=["1"]),  # blank file_path -> shared_path
            LeadTemplateTab(sheet_name="EMEA", cids=["2"], file_path=emea_only_path),
        ],
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "apac@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
        {"Email_Address": "emea@x.com", "First_Name": "E", "Last_Name": "Two", "Company_Name": "X", "CID": "2"},
    ])
    result = PipelineResult(valid_indices=[0, 1], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    wb_shared = openpyxl.load_workbook(shared_path)
    assert wb_shared["APAC"].cell(row=2, column=1).value == "apac@x.com"

    wb_emea = openpyxl.load_workbook(emea_only_path)
    assert wb_emea["EMEA"].cell(row=2, column=1).value == "emea@x.com"

    # The EMEA-only file must not have gained an APAC lead, and vice versa.
    assert wb_shared["APAC"].max_row == 2
    assert wb_emea["EMEA"].max_row == 2


def test_jira_summary_uses_per_tab_sharepoint_links_for_multiple_lead_template_files(tmp_path, monkeypatch):
    # Regression test: per-CID Lead Template file routing means a single
    # run can write to more than one Lead Template workbook, each with its
    # own SharePoint link — the Jira link picker must offer one "Lead
    # Report" checkbox per distinct file, each pointing at that file's own
    # configured link rather than a single shared one.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    save_jira_settings("https://example.atlassian.net", "me@example.com", "token123")

    shared_path = str(tmp_path / "shared_template.xlsx")
    wb = openpyxl.Workbook()
    apac = wb.active
    apac.title = "APAC"
    apac.append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID"])
    wb.save(shared_path)

    emea_only_path = str(tmp_path / "emea_only.xlsx")
    wb2 = openpyxl.Workbook()
    emea = wb2.active
    emea.title = "EMEA"
    emea.append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID"])
    wb2.save(emea_only_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        accumulated_report_link="https://madlog.sharepoint.com/:x:/s/Team/AccLink",
        field_mapping=fm,
        jira_ticket_key="PROJ-1234",
        client_mode="Lead QA",
        lead_template_path=shared_path,
        lead_template_link="https://madlog.sharepoint.com/:x:/s/Team/SharedLink",
        lead_template_multi_tab=True,
        lead_template_tabs=[
            LeadTemplateTab(sheet_name="APAC", cids=["1"]),  # blank link -> shared link
            LeadTemplateTab(sheet_name="EMEA", cids=["2"], file_path=emea_only_path,
                             link="https://madlog.sharepoint.com/:x:/s/Team/EmeaLink"),
        ],
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "apac@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
        {"Email_Address": "emea@x.com", "First_Name": "E", "Last_Name": "Two", "Company_Name": "X", "CID": "2"},
    ])
    result = PipelineResult(valid_indices=[0, 1], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    checkbox_labels = [c.label for c in at.checkbox if c.key and c.key.startswith("jira_link_")]
    assert any("AccLink" in label for label in checkbox_labels)
    assert any("SharedLink" in label for label in checkbox_labels)
    assert any("EmeaLink" in label for label in checkbox_labels)


def test_complex_account_two_stage_finalize_previews_then_writes(tmp_path, monkeypatch):
    # End-to-end regression test for the Complex Account two-stage Finalize:
    # "Finalize (fill columns)" must not write anything, only preview the
    # column-filling rules on the valid leads — the Accumulated Report only
    # actually gets updated after "Confirm & Write".
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Email", "First", "Last", "Company", "CID", "Capture Date", "Email Opt-in", "Business Phone"])
    wb.create_sheet("Refund").append(
        ["Email", "First", "Last", "Company", "CID", "Capture Date", "Email Opt-in", "Business Phone"])
    wb.save(acc_path)

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        complex_account=ComplexAccountConfig(enabled=True),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email": "a@wipro.com", "First": "A", "Last": "One", "Company": "Wipro", "CID": "1",
         "Capture Date": "08/17/2026", "Email Opt-in": "Yes, Yes", "Business Phone": 919819719038},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    assert not at.exception

    fill_button = next(b for b in at.button if b.label == "Finalize (fill columns)")
    fill_button.click().run()
    assert not at.exception

    # Nothing written yet — the Accumulated tab must still be just the header row.
    wb_after_fill = openpyxl.load_workbook(acc_path)
    assert wb_after_fill["Accumulated"].max_row == 1

    assert any("Preview: filled columns" in s.value for s in at.subheader)

    confirm_button = next(b for b in at.button if b.label == "Confirm & Write")
    confirm_button.click().run()
    assert not at.exception

    wb_final = openpyxl.load_workbook(acc_path)
    row = next(wb_final["Accumulated"].iter_rows(min_row=2, max_row=2, values_only=True))
    headers = next(wb_final["Accumulated"].iter_rows(min_row=1, max_row=1, values_only=True))
    written = dict(zip(headers, row))
    # A real date value now, not text — so Excel stores/filters it as a date.
    assert written["Capture Date"] == datetime.datetime(2026, 8, 17)
    assert written["Email Opt-in"] == "Yes"
    assert written["Business Phone"] == "91 9819719038"


def test_complex_account_finalize_fills_segment_from_xlsx_tal_without_crashing(tmp_path, monkeypatch):
    # Regression test: complex_account.tal_path pointing at a multi-tab
    # Excel workbook (IBM APAC's shape -- domain->segment by which tab it's
    # listed on) previously always went through the Dell-only CSV loader
    # (load_tal_index/pandas.read_csv), which crashed with a
    # UnicodeDecodeError trying to parse .xlsx bytes as CSV text. The file
    # extension must route to load_tal_segment_index instead, and the
    # Segment column must actually get backfilled from it.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Email", "First", "Last", "Company", "CID", "Capture Date", "Email Opt-in",
               "Business Phone", "Segment"])
    wb.create_sheet("Refund").append(
        ["Email", "First", "Last", "Company", "CID", "Capture Date", "Email Opt-in",
         "Business Phone", "Segment"])
    wb.save(acc_path)

    tal_path = str(tmp_path / "TAL.xlsx")
    tal_wb = openpyxl.Workbook()
    select_t = tal_wb.active
    select_t.title = "TAL Q3 Select T IN"
    select_t.append(["company_domain"])
    select_t.append(["wipro.com"])
    tal_wb.create_sheet("TAL Named IN").append(["company_domain"])
    tal_wb.save(tal_path)

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        complex_account=ComplexAccountConfig(enabled=True, tal_path=tal_path),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email": "a@wipro.com", "First": "A", "Last": "One", "Company": "Wipro", "CID": "1",
         "Capture Date": "08/17/2026", "Email Opt-in": "Yes, Yes", "Business Phone": 919819719038,
         "Segment": ""},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    assert not at.exception

    fill_button = next(b for b in at.button if b.label == "Finalize (fill columns)")
    fill_button.click().run()
    assert not at.exception

    confirm_button = next(b for b in at.button if b.label == "Confirm & Write")
    confirm_button.click().run()
    assert not at.exception

    wb_final = openpyxl.load_workbook(acc_path)
    row = next(wb_final["Accumulated"].iter_rows(min_row=2, max_row=2, values_only=True))
    headers = next(wb_final["Accumulated"].iter_rows(min_row=1, max_row=1, values_only=True))
    written = dict(zip(headers, row))
    assert written["Segment"] == "SelectT"


def test_complex_account_finalize_corrects_mismatched_asset_urls_and_warns(tmp_path, monkeypatch):
    # End-to-end: a lead with a wrong Asset URN/Form URL/Dell Asset URL vs.
    # the specifications file gets corrected during "Finalize (fill
    # columns)" (not just flagged), the correction is surfaced as a
    # warning, and the corrected values are what actually get written on
    # "Confirm & Write".
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Email", "First", "Last", "Company", "CID", "Asset Title", "Asset URN", "Form URL",
               "Dell Asset URL"])
    wb.create_sheet("Refund").append(
        ["Email", "First", "Last", "Company", "CID", "Asset Title", "Asset URN", "Form URL", "Dell Asset URL"])
    wb.save(acc_path)

    specs_path = str(tmp_path / "specs.xlsx")
    wb2 = openpyxl.Workbook()
    ws2 = wb2.active
    ws2.append([
        "Asset Name\n[to be filled in by EssenceMediacom]", "URN \n[to be filled in by EssenceMediacom]",
        "Publisher Link [AU]_BHRS\n[to be filled in by Publisher]",
        "Publisher Link INDIA]_ECS\n[to be filled in by Publisher]", "Dell Link",
    ])
    ws2.append([
        "Fuel AI Innovation", "DT2503G0007_033", "https://a.com/au", "https://a.com/india", "https://dell.com/x",
    ])
    wb2.save(specs_path)

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="Test Client",
        accumulated_report_path=acc_path,
        field_mapping=fm,
        complex_account=ComplexAccountConfig(enabled=True, specifications_path=specs_path),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email": "a@wipro.com", "First": "A", "Last": "One", "Company": "Wipro", "CID": "119414",
         "Asset Title": "Fuel AI Innovation", "Asset URN": "WRONG_URN",
         "Form URL": "https://wrong.com", "Dell Asset URL": "https://wrong-dell.com"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    assert not at.exception

    fill_button = next(b for b in at.button if b.label == "Finalize (fill columns)")
    fill_button.click().run()
    assert not at.exception

    assert at.session_state["complex_corrections"][0]
    warning_text = "\n".join(w.value for w in at.warning)
    assert "corrected automatically" in warning_text
    assert "Asset URN" in warning_text

    confirm_button = next(b for b in at.button if b.label == "Confirm & Write")
    confirm_button.click().run()
    assert not at.exception

    wb_final = openpyxl.load_workbook(acc_path)
    row = next(wb_final["Accumulated"].iter_rows(min_row=2, max_row=2, values_only=True))
    headers = next(wb_final["Accumulated"].iter_rows(min_row=1, max_row=1, values_only=True))
    written = dict(zip(headers, row))
    assert written["Asset URN"] == "DT2503G0007_033"
    assert written["Dell Asset URL"] == "https://dell.com/x"
    assert written["Form URL"] == "https://a.com/india"


def test_completed_checks_status_shown_for_enabled_checks_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    assert not at.exception

    status_captions = [c.value for c in at.caption if "completed" in c.value]
    assert len(status_captions) == 1
    assert "Duplicate" in status_captions[0]
    assert "Leadcap" not in status_captions[0]  # not enabled for this client


def test_enabled_checks_caption_includes_lead_template_mapping(tmp_path, monkeypatch):
    # Regression test (Minor, final review): the pre-run "Enabled checks:
    # ..." caption (_enabled_checks, distinct from _stage_labels/
    # _completed_checks, which already included this) had no entry at all
    # for Lead Template Mapping, even when a mandatory rule is configured.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        lead_template_mapping=LeadTemplateMappingConfig(rules=[
            LeadTemplateColumnRule(template_column="Company Size", mandatory=True),
        ]),
    )
    save_profile(profile, get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception

    enabled_caption = next(c for c in at.caption if "Enabled checks" in c.value)
    assert "Lead Template Mapping" in enabled_caption.value


def test_complex_account_flags_asset_url_mismatch_for_review_check_does_not_mutate(tmp_path, monkeypatch):
    # Regression test: at Run Check time, a mismatch against the
    # specifications file must only be flagged for review, never silently
    # rewritten -- the actual correction happens later, in
    # apply_complex_account_rules, only for leads approved as valid.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    specs_path = str(tmp_path / "specs.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([
        "Asset Name\n[to be filled in by EssenceMediacom]", "URN \n[to be filled in by EssenceMediacom]",
        "Publisher Link [AU]_BHRS\n[to be filled in by Publisher]",
        "Publisher Link INDIA]_ECS\n[to be filled in by Publisher]", "Dell Link",
    ])
    ws.append([
        "Fuel AI Innovation", "DT2503G0007_033", "https://a.com/au", "https://a.com/india", "https://dell.com/x",
    ])
    wb.save(specs_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        complex_account=ComplexAccountConfig(enabled=True, specifications_path=specs_path),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "119414",
         "Asset Title": "Fuel AI Innovation", "Asset URN": "WRONG_URN",
         "Form URL": "https://a.com/india", "Dell Asset URL": "https://dell.com/x"},
    ])

    # This exercises the same functions pages/2_Run_Check.py's "Run Check"
    # button calls: load the specs file, run the Complex Account checks
    # alongside the normal pipeline, and merge the results together.
    from core.complex_account import (
        check_complex_account_conditions, merge_complex_account_review, load_asset_specifications,
    )

    accumulated_leads = pd.read_excel(acc_path, sheet_name="Accumulated")
    asset_specs = load_asset_specifications(specs_path)
    complex_review = check_complex_account_conditions(new_leads, asset_specs, fm)
    result = run_pipeline(new_leads, profile, accumulated_leads, {}, [])
    merge_complex_account_review(result, complex_review)

    assert 0 not in result.valid_indices
    assert 0 in result.review_reasons
    assert any("Asset URN" in str(d) for d in result.review_reasons[0])
    # The check step must never rewrite the leadfile's value itself.
    assert new_leads.loc[0, "Asset URN"] == "WRONG_URN"


def test_run_check_blocks_leadcap_clients_missing_the_purchased_report(tmp_path, monkeypatch):
    # AppTest can't drive a real file upload -- pre-seed the upload cache
    # (see core/upload_cache.py) exactly as resolve_upload() would after a
    # real New Leads upload, but leave the Purchased Lead Report slot
    # empty, simulating a leadcap client where only the leadfile was
    # selected.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    from core.models import LeadcapConfig
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        leadcap=LeadcapConfig(enabled=True, flat_cap=5, purchased_report_cid_column="CID",
                               purchased_report_email_column="Email_Address"),
    )
    save_profile(profile, get_clients_dir())

    leads_csv = b"Email_Address,First_Name,Last_Name,Company_Name,CID\nbob@new.com,Bob,Lee,Beta,1\n"
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_check_upload_cache"] = {
        "Test Client": {"new_leads": {"name": "leads.csv", "data": leads_csv}},
    }
    at.run()

    assert any("Using previously selected file" in c.value and "leads.csv" in c.value for c in at.caption)

    run_button = next(b for b in at.button if b.label == "Run Check")
    run_button.click().run()

    assert not at.exception
    assert any("upload the Purchased Lead Report" in e.value for e in at.error)
    assert "run_result" not in at.session_state


def test_run_check_uses_cached_files_for_both_leadcap_uploads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    from core.models import LeadcapConfig
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        leadcap=LeadcapConfig(enabled=True, flat_cap=5, purchased_report_cid_column="CID",
                               purchased_report_email_column="Email_Address"),
    )
    save_profile(profile, get_clients_dir())

    leads_csv = b"Email_Address,First_Name,Last_Name,Company_Name,CID\nbob@new.com,Bob,Lee,Beta,1\n"
    purchased_csv = b"CID,Email_Address\n1,bob@new.com\n"
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_check_upload_cache"] = {
        "Test Client": {
            "new_leads": {"name": "leads.csv", "data": leads_csv},
            "purchased_report": {"name": "purchased.csv", "data": purchased_csv},
        },
    }
    at.run()

    assert any("leads.csv" in c.value for c in at.caption)
    assert any("purchased.csv" in c.value for c in at.caption)

    run_button = next(b for b in at.button if b.label == "Run Check")
    run_button.click().run()

    assert not at.exception
    assert not at.error
    assert "run_result" in at.session_state


def test_switching_clients_does_not_reuse_the_other_clients_cached_file(tmp_path, monkeypatch):
    # The upload cache is keyed by client name -- selecting a client that
    # has never had a file uploaded in this session must start empty, even
    # if a *different* client already has one cached.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile_a = ClientProfile(name="Client A", accumulated_report_path=acc_path, field_mapping=fm)
    profile_b = ClientProfile(name="Client B", accumulated_report_path=acc_path, field_mapping=fm)
    save_profile(profile_a, get_clients_dir())
    save_profile(profile_b, get_clients_dir())

    leads_csv = b"Email_Address,First_Name,Last_Name,Company_Name,CID\nbob@new.com,Bob,Lee,Beta,1\n"
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_check_upload_cache"] = {
        "Client A": {"new_leads": {"name": "leads.csv", "data": leads_csv}},
    }
    at.run()
    at.selectbox[0].set_value("Client B").run()

    assert not at.exception
    assert not any("Using previously selected file" in c.value for c in at.caption)


def test_lead_template_mandatory_rule_with_no_resolvable_source_forces_needs_review(tmp_path, monkeypatch):
    # Confirms Task 4's mandatory-column check (already wired into
    # run_pipeline, committed separately) actually fires: a mandatory Lead
    # Template rule whose column has no match anywhere in the leadfile must
    # flag the lead for review instead of letting it go straight to a
    # normal Valid write. Calls run_pipeline() directly with the same
    # arguments pages/2_Run_Check.py's own "Run Check" button passes (minus
    # on_progress -- see the concern noted in the Task 6 report about why),
    # matching this file's own existing precedent for exercising pipeline
    # behavior "as the page would"
    # (test_complex_account_flags_asset_url_mismatch_for_review_check_does_not_mutate
    # above).
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        lead_template_mapping=LeadTemplateMappingConfig(rules=[
            LeadTemplateColumnRule(template_column="Opt-In Date", mandatory=True),
        ]),
    )
    save_profile(profile, get_clients_dir())

    # "Opt-In Date" has no match at all among the leadfile's columns below --
    # find_passthrough_lead_column can't resolve any source for it.
    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee",
         "Company_Name": "Beta", "CID": "1"},
    ])
    accumulated_leads = pd.read_excel(acc_path, sheet_name="Accumulated")

    result = run_pipeline(new_leads, profile, accumulated_leads, {}, [])

    assert 0 not in result.valid_indices
    assert 0 in result.review_reasons
    assert any("Opt-In Date" in str(d) for d in result.review_reasons[0])


def test_run_check_button_succeeds_for_client_with_mandatory_lead_template_rule(tmp_path, monkeypatch):
    # Regression test for the CROSS-TASK BUG documented in
    # .superpowers/sdd/2026-09-25-lead-template-column-mapping/progress.md:
    # run_pipeline (core/pipeline.py) reports a new "Checking Lead Template
    # Mandatory Columns" progress stage whenever the client has at least one
    # mandatory LeadTemplateColumnRule configured, but this page's
    # _stage_labels/_completed_checks didn't know about that label --
    # _advance_progress's _stage_labels.index(label) raised ValueError the
    # moment such a client clicked "Run Check", surfaced to the user as a
    # raw, undiagnosable error. Unlike the review-only test above (which
    # calls run_pipeline directly specifically to dodge this bug), this
    # drives the actual "Run Check" button through AppTest to prove the
    # whole page-level path works end to end for a client in this shape.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        lead_template_mapping=LeadTemplateMappingConfig(rules=[
            LeadTemplateColumnRule(template_column="Opt-In Date", mandatory=True),
        ]),
    )
    save_profile(profile, get_clients_dir())

    leads_csv = (
        b"Email_Address,First_Name,Last_Name,Company_Name,CID,Opt-In Date\n"
        b"bob@new.com,Bob,Lee,Beta,1,2026-03-05\n"
    )
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_check_upload_cache"] = {
        "Test Client": {"new_leads": {"name": "leads.csv", "data": leads_csv}},
    }
    at.run()
    assert not at.exception

    run_button = next(b for b in at.button if b.label == "Run Check")
    run_button.click().run()

    assert not at.exception
    assert "run_result" in at.session_state


def test_finalize_applies_lead_template_mapping_date_format_to_written_column(tmp_path, monkeypatch):
    # Proves lead_template_mapping actually reaches _finalize_write's
    # append_leads call (Task 6's own wiring) through the real page path: a
    # configured date_format rule must reformat the written Lead Template
    # cell into a real date value in that format, not leave the passthrough
    # value as unformatted raw text -- mirrors the single-tab `else` branch
    # (search anchor: `clear_existing=profile.lead_template_clear_existing`).
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    wb.active.title = "Sheet"
    wb.active.append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID", "Opt-In Date"])
    wb.save(template_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        client_mode="Lead QA", lead_template_path=template_path, lead_template_sheet_name="Sheet",
        lead_template_mapping=LeadTemplateMappingConfig(rules=[
            LeadTemplateColumnRule(template_column="Opt-In Date", date_format="MM/DD/YYYY"),
        ]),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta",
         "CID": "1", "Opt-In Date": "2026-03-05"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    finalize_button = next(b for b in at.button if b.label == "Finalize")
    finalize_button.click().run()
    assert not at.exception

    wb = openpyxl.load_workbook(template_path)
    ws = wb["Sheet"]
    headers = [cell.value for cell in ws[1]]
    col_idx = headers.index("Opt-In Date") + 1
    cell = ws.cell(row=2, column=col_idx)
    wb.close()

    assert isinstance(cell.value, datetime.datetime)
    assert cell.value == datetime.datetime(2026, 3, 5)
    assert cell.number_format == "mm\\/dd\\/yyyy"


def test_run_check_button_succeeds_for_client_with_mandatory_google_sheets_rule(tmp_path, monkeypatch):
    # Regression test for the SAME cross-task bug class as
    # test_run_check_button_succeeds_for_client_with_mandatory_lead_template_rule
    # above, but for the SECOND mandatory-column stage this task (Task 5)
    # adds: core/pipeline.py's "Checking Google Sheets Mandatory Columns",
    # reported whenever profile.google_sheets.mapping has at least one
    # mandatory rule. This task's own brief exists specifically to make
    # sure adding that new pipeline stage doesn't repeat the exact same
    # _stage_labels.index(label) ValueError for its own new label. A raw
    # `assert not at.exception` alone would pass identically whether the
    # bug is present or fixed -- render_error swallows the ValueError via
    # st.error() -- so "run_result" in at.session_state is the assertion
    # that actually discriminates.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        google_sheets=GoogleSheetsConfig(mapping=LeadTemplateMappingConfig(rules=[
            LeadTemplateColumnRule(template_column="X", mandatory=True),
        ])),
    )
    save_profile(profile, get_clients_dir())

    leads_csv = (
        b"Email_Address,First_Name,Last_Name,Company_Name,CID\n"
        b"bob@new.com,Bob,Lee,Beta,1\n"
    )
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_check_upload_cache"] = {
        "Test Client": {"new_leads": {"name": "leads.csv", "data": leads_csv}},
    }
    at.run()
    assert not at.exception

    run_button = next(b for b in at.button if b.label == "Run Check")
    run_button.click().run()

    assert not at.exception
    assert "run_result" in at.session_state


def test_finalize_writes_valid_leads_to_google_sheets_with_date_format_applied(tmp_path, monkeypatch):
    # Proves Step 15's write-path wiring: _finalize_write must call
    # core.google_sheets_client.append_rows once per matched CID, with rows
    # resolved through the exact same manual-override/target-role/synonym/
    # fuzzy-match chain append_leads itself uses (resolve_lead_template_rules
    # + _resolve_passthrough_columns), and with any configured
    # LeadTemplateColumnRule.date_format actually applied to that column's
    # value -- not left as the leadfile's raw, unformatted text (see
    # test_finalize_applies_lead_template_mapping_date_format_to_written_column
    # above for the equivalent proof on the Excel Lead Template side).
    # core.google_sheets_client.read_sheet_headers/append_rows are mocked
    # the same way tests/test_client_setup_page.py's Google Sheets tests
    # mock them (patching the origin module directly, not a page-qualified
    # path -- `from core import google_sheets_client` in the page means the
    # page's calls resolve through this same module object at call time).
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_google_sheets_key_path
    key_path = str(tmp_path / "key.json")
    save_google_sheets_key_path(key_path)

    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        google_sheets=GoogleSheetsConfig(
            enabled=True,
            tabs=[GoogleSheetTab(cid="1", sheet_id="sheet123", worksheet_name="Sheet1")],
            mapping=LeadTemplateMappingConfig(rules=[
                LeadTemplateColumnRule(template_column="Opt-In Date", date_format="MM/DD/YYYY"),
            ]),
        ),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta",
         "CID": "1", "Opt-In Date": "2026-03-05"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    with patch("core.google_sheets_client.read_sheet_headers", return_value=[
        "Email_Address", "First_Name", "Last_Name", "Company_Name", "CID", "Opt-In Date",
    ]), patch("core.google_sheets_client.append_rows") as mock_append_rows:
        finalize_button = next(b for b in at.button if b.label == "Finalize")
        finalize_button.click().run()
    assert not at.exception

    mock_append_rows.assert_called_once_with(
        key_path, "sheet123", "Sheet1",
        [{
            "Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee",
            "Company_Name": "Beta", "CID": "1", "Opt-In Date": "03/05/2026",
        }],
        clear_existing=False,
    )


def test_finalize_google_sheets_write_passes_clear_existing_from_profile(tmp_path, monkeypatch):
    # profile.google_sheets.clear_existing=True must reach append_rows as
    # clear_existing=True -- proves the Client Setup checkbox (gs_clear_existing)
    # actually controls write-time behavior, not just gets saved and ignored.
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_google_sheets_key_path
    key_path = str(tmp_path / "key.json")
    save_google_sheets_key_path(key_path)

    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        google_sheets=GoogleSheetsConfig(
            enabled=True,
            tabs=[GoogleSheetTab(cid="1", sheet_id="sheet123", worksheet_name="Sheet1")],
            clear_existing=True,
        ),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    with patch("core.google_sheets_client.read_sheet_headers", return_value=[
        "Email_Address", "First_Name", "Last_Name", "Company_Name", "CID",
    ]), patch("core.google_sheets_client.append_rows") as mock_append_rows:
        finalize_button = next(b for b in at.button if b.label == "Finalize")
        finalize_button.click().run()
    assert not at.exception

    assert mock_append_rows.call_args.kwargs["clear_existing"] is True


def test_finalize_google_sheets_clear_existing_only_clears_once_per_shared_sheet_target(tmp_path, monkeypatch):
    # Two different CIDs routed to the SAME sheet_id/worksheet_name (an
    # unusual but valid config) must not clear twice in one run -- a second
    # clear_existing=True call would wipe out the first CID's rows this
    # exact run just wrote, before Finalize even finishes. Mirrors the
    # multi-target-clear trap Box Tracker's own clear_existing already
    # guards against.
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_google_sheets_key_path
    key_path = str(tmp_path / "key.json")
    save_google_sheets_key_path(key_path)

    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        google_sheets=GoogleSheetsConfig(
            enabled=True,
            tabs=[
                GoogleSheetTab(cid="1", sheet_id="sheet123", worksheet_name="Sheet1"),
                GoogleSheetTab(cid="2", sheet_id="sheet123", worksheet_name="Sheet1"),
            ],
            clear_existing=True,
        ),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta", "CID": "1"},
        {"Email_Address": "amy@new.com", "First_Name": "Amy", "Last_Name": "Ng", "Company_Name": "Gamma", "CID": "2"},
    ])
    result = PipelineResult(valid_indices=[0, 1], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    with patch("core.google_sheets_client.read_sheet_headers", return_value=[
        "Email_Address", "First_Name", "Last_Name", "Company_Name", "CID",
    ]), patch("core.google_sheets_client.append_rows") as mock_append_rows:
        finalize_button = next(b for b in at.button if b.label == "Finalize")
        finalize_button.click().run()
    assert not at.exception

    assert mock_append_rows.call_count == 2
    clear_flags = [c.kwargs["clear_existing"] for c in mock_append_rows.call_args_list]
    assert clear_flags.count(True) == 1
    assert clear_flags.count(False) == 1


def test_finalize_skips_google_sheets_write_when_key_path_not_set(tmp_path, monkeypatch):
    # A client can have Google Sheets Lead Delivery enabled on a machine
    # where nobody has set up the shared service-account key path yet
    # (Settings page) -- this must not attempt a write (there's no key to
    # authenticate with) or crash, and must not stop the Accumulated
    # Report write from completing. Doesn't assert on the st.error(...)
    # message _finalize_write shows in this case -- like every other direct
    # st.info/st.warning call already inside _finalize_write (e.g. the
    # "Backed up Accumulated Report to ..." info above), it's wiped by the
    # Finalize button handler's own st.rerun() immediately afterward
    # (confirmed empirically: even that pre-existing, already-shipped info
    # message doesn't survive a `.click().run()` in this test harness) --
    # a pre-existing characteristic of this page's rerun design, not
    # something this task changes.
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)

    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    profile = ClientProfile(
        name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
        google_sheets=GoogleSheetsConfig(
            enabled=True,
            tabs=[GoogleSheetTab(cid="1", sheet_id="sheet123", worksheet_name="Sheet1")],
        ),
    )
    save_profile(profile, get_clients_dir())

    new_leads = pd.DataFrame([
        {"Email_Address": "bob@new.com", "First_Name": "Bob", "Last_Name": "Lee", "Company_Name": "Beta",
         "CID": "1"},
    ])
    result = PipelineResult(valid_indices=[0], refund_reasons={})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = new_leads
    at.session_state["run_result"] = result
    at.session_state["run_result_for"] = "Test Client"
    at.run()

    with patch("core.google_sheets_client.append_rows") as mock_append_rows:
        finalize_button = next(b for b in at.button if b.label == "Finalize")
        finalize_button.click().run()
    assert not at.exception

    mock_append_rows.assert_not_called()


def test_client_picker_groups_regional_profiles_on_run_check(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Autodesk APAC", accumulated_report_path="a.xlsx",
                                client_group="Autodesk"), get_clients_dir())
    save_profile(ClientProfile(name="Autodesk EMEA", accumulated_report_path="a.xlsx",
                                client_group="Autodesk"), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    group_box = next(s for s in at.selectbox if s.label == "Group")
    assert group_box.options == ["All groups", "Autodesk"]
    group_box.set_value("Autodesk").run()
    client_box = next(s for s in at.selectbox if s.label == "Client")
    assert client_box.options == ["Autodesk APAC", "Autodesk EMEA"]
    client_box.set_value("Autodesk EMEA").run()
    assert not at.exception
    assert next(s for s in at.selectbox if s.label == "Client").value == "Autodesk EMEA"


def test_switching_group_on_run_check_auto_selects_the_new_groups_first_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    for name, group in [("Alpha One", "Group A"), ("Alpha Two", "Group A"),
                        ("Beta One", "Group B"), ("Beta Two", "Group B")]:
        save_profile(ClientProfile(name=name, accumulated_report_path="a.xlsx", client_group=group),
                     get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.selectbox(key="run_check_group_filter").set_value("Group A").run()
    at.selectbox(key="run_check_client_profile").set_value("Alpha Two").run()
    at.selectbox(key="run_check_group_filter").set_value("Group B").run()
    assert not at.exception
    client_box = at.selectbox(key="run_check_client_profile")
    assert client_box.value == "Beta One"
    assert client_box.proto.set_value is True


def test_client_picker_still_selects_ungrouped_clients_by_exact_name_on_run_check(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Existing Client", accumulated_report_path="a.xlsx"), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    client_boxes = [s for s in at.selectbox if s.label == "Client"]
    assert len(client_boxes) == 1
    client_boxes[0].set_value("Existing Client").run()
    assert not at.exception


def _stepper(at):
    return next(m.value for m in at.markdown if "Review & Finalize" in m.value)


def test_stepper_shows_run_check_as_current_before_any_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    save_profile(ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm),
                 get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert _stepper(at) == (
        ":blue-badge[:material/arrow_circle_right: 1. Run Check]"
        " :material/chevron_right: "
        ":gray-badge[:material/radio_button_unchecked: 2. Review & Finalize]"
    )  # no Jira ticket key -> no "Post to Jira" step
    # The old emoji-in-columns indicator is gone.
    assert not any(m.value.startswith(("✅ 1.", "**➡️", "⚪")) for m in at.markdown)


def test_stepper_shows_review_as_current_with_a_result_and_jira_step_upcoming(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    save_profile(ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
                               jira_ticket_key="PROJ-1234"), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
    ])
    at.session_state["run_result"] = PipelineResult(valid_indices=[0], refund_reasons={})
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    assert not at.exception
    stepper = _stepper(at)
    assert ":green-badge[:material/check_circle: 1. Run Check]" in stepper
    assert ":blue-badge[:material/arrow_circle_right: 2. Review & Finalize]" in stepper
    assert ":gray-badge[:material/radio_button_unchecked: 3. Post to Jira]" in stepper


def test_stepper_shows_post_to_jira_as_current_after_finalize(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    save_profile(ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
                               jira_ticket_key="PROJ-1234"), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
    ])
    at.session_state["run_result"] = PipelineResult(valid_indices=[0], refund_reasons={})
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    next(b for b in at.button if b.label == "Finalize").click().run()
    assert not at.exception
    stepper = _stepper(at)
    assert ":green-badge[:material/check_circle: 1. Run Check]" in stepper
    assert ":green-badge[:material/check_circle: 2. Review & Finalize]" in stepper
    assert ":blue-badge[:material/arrow_circle_right: 3. Post to Jira]" in stepper


def test_summary_shows_four_bordered_metric_cards(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    save_profile(ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm),
                 get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
        {"Email_Address": "b@x.com", "First_Name": "B", "Last_Name": "Two", "Company_Name": "Y", "CID": "1"},
        {"Email_Address": "c@x.com", "First_Name": "C", "Last_Name": "Three", "Company_Name": "Z", "CID": "1"},
    ])
    at.session_state["run_result"] = PipelineResult(
        valid_indices=[0], refund_reasons={1: "Duplicate - exact email"},
        review_reasons={2: [ReviewDetail(check="Duplicate", message="reason c")]},
    )
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    assert not at.exception

    cards = [m for m in at.metric if m.label in {"Leads In", "Valid", "Refunded", "Needs Review"}]
    assert [m.label for m in cards] == ["Leads In", "Valid", "Refunded", "Needs Review"]
    assert [m.value for m in cards] == ["3", "1", "1", "1"]
    assert [m.proto.icon for m in cards] == [
        ":material/group:", ":material/check_circle:", ":material/undo:", ":material/flag:"]
    assert all(m.proto.show_border for m in cards)


def _two_review_leads_page(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    save_profile(ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm),
                 get_clients_dir())
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
        {"Email_Address": "b@x.com", "First_Name": "B", "Last_Name": "Two", "Company_Name": "Y", "CID": "1"},
    ])
    at.session_state["run_result"] = PipelineResult(valid_indices=[], refund_reasons={}, review_reasons={
        0: [ReviewDetail(check="Duplicate", message="reason a")],
        1: [ReviewDetail(check="Duplicate", message="reason b")],
    })
    at.session_state["run_result_for"] = "Test Client"
    return at, acc_path


def _review_only_editor(edited_review):
    # patch("streamlit.data_editor") replaces BOTH editors on the page. Hand
    # the canned table back only to the Needs Review editor (the only one
    # with a "Select" column) and pass every other table (e.g. the Refund
    # Reasons editor that appears after a lead is refunded) through unedited.
    def _editor(data, *args, **kwargs):
        return edited_review if "Select" in data.columns else data
    return _editor


def test_review_bulk_refund_selected_leads(tmp_path, monkeypatch):
    at, _ = _two_review_leads_page(tmp_path, monkeypatch)
    at.run()
    assert not at.exception
    edited = pd.DataFrame([
        {"Select": True, "Row": 2, "Email": "a@x.com", "Company": "X", "CID": "1", "Reasons": "Duplicate - reason a"},
        {"Select": False, "Row": 3, "Email": "b@x.com", "Company": "Y", "CID": "1", "Reasons": "Duplicate - reason b"},
    ])
    with patch("streamlit.data_editor", side_effect=_review_only_editor(edited)):
        next(b for b in at.button if b.key == "review_bulk_refund").click().run()
    assert not at.exception

    result = at.session_state["run_result"]
    assert result.refund_reasons == {0: "Duplicate - reason a"}
    assert list(result.review_reasons) == [1]
    assert result.valid_indices == []


def test_needs_review_table_offers_a_per_row_action_column(tmp_path, monkeypatch):
    at, _ = _two_review_leads_page(tmp_path, monkeypatch)
    calls = []

    def _spy(data, *args, **kwargs):
        calls.append((data, kwargs))
        return data

    with patch("streamlit.data_editor", side_effect=_spy):
        at.run()
    assert not at.exception

    review_data, review_kwargs = next((d, k) for d, k in calls if "Select" in d.columns)
    assert list(review_data.columns) == ["Select", "Row", "Email", "Company", "CID", "Reasons", "Action"]
    assert review_data["Action"].isna().all()  # blank by default
    assert "Action" not in review_kwargs["disabled"]
    assert review_kwargs["column_config"]["Action"]["type_config"] == {
        "type": "selectbox", "options": ["Approve as valid", "Mark as refund"]}

    apply_button = next(b for b in at.button if b.key == "review_apply_row_actions")
    assert apply_button.label == "Apply 0 row decision(s)"
    assert apply_button.disabled is True
    # The bulk select-and-act flow stays alongside it, untouched.
    assert {"review_select_all", "review_clear_all", "review_bulk_approve", "review_bulk_refund"} <= {
        b.key for b in at.button}


def test_row_decisions_approve_and_refund_in_one_click_then_finalize_writes_both(tmp_path, monkeypatch):
    at, acc_path = _two_review_leads_page(tmp_path, monkeypatch)
    at.run()
    edited = pd.DataFrame([
        {"Select": False, "Row": 2, "Email": "a@x.com", "Company": "X", "CID": "1",
         "Reasons": "Duplicate - reason a", "Action": "Approve as valid"},
        {"Select": False, "Row": 3, "Email": "b@x.com", "Company": "Y", "CID": "1",
         "Reasons": "Duplicate - reason b", "Action": "Mark as refund"},
    ])
    with patch("streamlit.data_editor", side_effect=_review_only_editor(edited)):
        next(b for b in at.button if b.key == "review_apply_row_actions").click().run()
    assert not at.exception

    result = at.session_state["run_result"]
    assert result.valid_indices == [0]
    assert result.refund_reasons == {1: "Duplicate - reason b"}
    assert result.review_reasons == {}

    # The existing write path is unchanged: Finalize sends each lead where
    # the row decision put it.
    next(b for b in at.button if b.label == "Finalize").click().run()
    assert not at.exception
    wb = openpyxl.load_workbook(acc_path)
    acc_emails = {r[0] for r in wb["Accumulated"].iter_rows(min_row=2, values_only=True) if r[0] is not None}
    refund_emails = {r[0] for r in wb["Refund"].iter_rows(min_row=2, values_only=True) if r[0] is not None}
    assert "a@x.com" in acc_emails
    assert refund_emails == {"b@x.com"}


def test_row_decisions_ignore_select_ticks_and_leave_undecided_rows_in_review(tmp_path, monkeypatch):
    at, _ = _two_review_leads_page(tmp_path, monkeypatch)
    at.run()
    edited = pd.DataFrame([
        {"Select": True, "Row": 2, "Email": "a@x.com", "Company": "X", "CID": "1",
         "Reasons": "Duplicate - reason a", "Action": None},
        {"Select": False, "Row": 3, "Email": "b@x.com", "Company": "Y", "CID": "1",
         "Reasons": "Duplicate - reason b", "Action": "Approve as valid"},
    ])
    with patch("streamlit.data_editor", side_effect=_review_only_editor(edited)):
        next(b for b in at.button if b.key == "review_apply_row_actions").click().run()
    assert not at.exception

    result = at.session_state["run_result"]
    assert result.valid_indices == [1]
    assert list(result.review_reasons) == [0]  # ticked but undecided -> still needs review
    assert result.refund_reasons == {}
