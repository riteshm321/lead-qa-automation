import os
from unittest.mock import patch

import openpyxl
from streamlit.testing.v1 import AppTest

from core.models import GoogleSheetTab

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "1_Client_Setup.py")


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


def test_client_name_with_path_separator_is_rejected(tmp_path, monkeypatch):
    # Regression test: the client name becomes a bare "<name>.json" filename
    # under clients_dir with no sanitizing - a "/" silently created a
    # nested, orphaned profile file that the client dropdown's flat
    # directory scan could never show again, and ".." could escape
    # clients_dir onto an arbitrary path on disk.
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    next(t for t in at.text_input if t.label == "Client name").set_value("Acme/Corp").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()

    save_button = next(b for b in at.button if "Save Client Profile" in b.label)
    save_button.click().run()
    assert not at.exception

    assert any("can't contain" in e.value for e in at.error)
    from core.app_settings import get_clients_dir
    from core.profile_store import list_profile_names
    assert list_profile_names(get_clients_dir()) == []


def test_lead_template_mapping_reads_from_first_tabs_own_file_when_shared_path_is_blank(tmp_path, monkeypatch):
    # Regression test: with per-CID Lead Template routing, a client can have
    # every tab point at its own separate file and leave the shared "Lead
    # Template path" completely blank (no default needed). The column
    # mapping expander previously always read headers from that shared path
    # only, so it silently showed "enter a valid path" even though the
    # tab's own file was perfectly valid.
    monkeypatch.chdir(tmp_path)
    tab_file = str(tmp_path / "emea_only.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "EMEA"
    ws.append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID"])
    wb.save(tab_file)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    multi_tab_checkbox = next(c for c in at.checkbox if "Route different CIDs" in c.label)
    multi_tab_checkbox.set_value(True).run()
    assert not at.exception

    add_tab_button = next(b for b in at.button if b.key == "lead_template_tabs_add")
    add_tab_button.click().run()
    assert not at.exception

    tab_file_input = next(t for t in at.text_input if t.label.startswith("File for this tab"))
    tab_file_input.set_value(tab_file).run()
    assert not at.exception

    sheet_select = next(s for s in at.selectbox if s.label == "Tab (sheet) name")
    assert "EMEA" in sheet_select.options
    sheet_select.set_value("EMEA").run()
    assert not at.exception

    email_select = at.selectbox(key="tmpl_map_email")
    assert "Email_Address" in email_select.options


def test_saving_lead_template_mapping_persists_mandatory_and_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # Build a minimal real Lead Template workbook so _safe_read_template_headers
    # has something to read.
    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Company Size"])
    wb.save(template_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    next(t for t in at.text_input if t.label == "Client name").set_value("LTM Test Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="lead_template_path_input").set_value(template_path).run()
    at.selectbox(key="lead_template_sheet_select").set_value("Sheet1").run()

    at.checkbox(key="ltm_mandatory_Company Size").set_value(True).run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    saved = load_profile("LTM Test Client", get_clients_dir())
    rule = next(r for r in saved.lead_template_mapping.rules if r.template_column == "Company Size")
    assert rule.mandatory is True


def test_a_lead_template_column_left_at_every_default_is_not_saved_as_a_rule(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Company Size"])
    wb.save(template_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    next(t for t in at.text_input if t.label == "Client name").set_value("LTM Default Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="lead_template_path_input").set_value(template_path).run()
    at.selectbox(key="lead_template_sheet_select").set_value("Sheet1").run()

    # Deliberately do NOT touch the "Company Size" mandatory checkbox,
    # source override, or date format -- every Lead Template column left at
    # its default must not turn into a saved rule.

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    saved = load_profile("LTM Default Client", get_clients_dir())
    assert saved.lead_template_mapping.rules == []


def test_refund_reason_template_column_is_never_offered_as_a_configurable_row(tmp_path, monkeypatch):
    # Regression test: normalize_header_text strips ALL non-alphanumeric
    # characters INCLUDING SPACES, so normalize_header_text("Refund Reason")
    # == "refundreason", which never matches a literal "refund reason" (with
    # a space) in a hand-typed skip set. "Refund Reason" must still never be
    # offered as a configurable row here (it never comes from a leadfile
    # passthrough).
    monkeypatch.chdir(tmp_path)

    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Company Size", "Refund Reason"])
    wb.save(template_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    next(t for t in at.text_input if t.label == "Client name").set_value("LTM Refund Reason Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="lead_template_path_input").set_value(template_path).run()
    at.selectbox(key="lead_template_sheet_select").set_value("Sheet1").run()

    assert not any(c.key == "ltm_mandatory_Refund Reason" for c in at.checkbox)
    # A normal, non-skip-list column should still be offered.
    assert any(c.key == "ltm_mandatory_Company Size" for c in at.checkbox)


def test_formula_template_column_is_never_offered_as_a_configurable_row(tmp_path, monkeypatch):
    # Regression test: formula columns (their value is fully computed by
    # the template's own formula, never a leadfile passthrough) must be
    # excluded from the mapping UI the same way append_leads already
    # excludes them from passthrough resolution.
    monkeypatch.chdir(tmp_path)

    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Company Size", "Campaign Name"])
    ws.append(["a@x.com", 50, "=SUM(B2:B2)"])
    wb.save(template_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    next(t for t in at.text_input if t.label == "Client name").set_value("LTM Formula Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="lead_template_path_input").set_value(template_path).run()
    at.selectbox(key="lead_template_sheet_select").set_value("Sheet1").run()

    assert not any(c.key == "ltm_mandatory_Campaign Name" for c in at.checkbox)
    # A normal, non-formula column should still be offered.
    assert any(c.key == "ltm_mandatory_Company Size" for c in at.checkbox)


def test_saving_a_source_column_override_alone_persists_a_rule(tmp_path, monkeypatch):
    # Coverage gap: only the "mandatory alone" save branch was previously
    # tested. A source override set with no mandatory checkbox and no date
    # format must also save a rule for that column.
    monkeypatch.chdir(tmp_path)

    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Company Size"])
    wb.save(template_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    next(t for t in at.text_input if t.label == "Client name").set_value("LTM Source Override Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="lead_template_path_input").set_value(template_path).run()
    at.selectbox(key="lead_template_sheet_select").set_value("Sheet1").run()

    at.text_input(key="ltm_source_text_Company Size").set_value("Employee Count").run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    saved = load_profile("LTM Source Override Client", get_clients_dir())
    rule = next(r for r in saved.lead_template_mapping.rules if r.template_column == "Company Size")
    assert rule.source_column == "Employee Count"
    assert rule.mandatory is False
    assert rule.date_format == ""


def test_saving_a_date_format_alone_persists_a_rule(tmp_path, monkeypatch):
    # Coverage gap: a date format set with no mandatory checkbox and no
    # source override must also save a rule for that column.
    monkeypatch.chdir(tmp_path)

    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Capture Date"])
    wb.save(template_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    next(t for t in at.text_input if t.label == "Client name").set_value("LTM Date Format Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="lead_template_path_input").set_value(template_path).run()
    at.selectbox(key="lead_template_sheet_select").set_value("Sheet1").run()

    at.selectbox(key="ltm_fmt_Capture Date").set_value("MM/DD/YYYY").run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    saved = load_profile("LTM Date Format Client", get_clients_dir())
    rule = next(r for r in saved.lead_template_mapping.rules if r.template_column == "Capture Date")
    assert rule.date_format == "MM/DD/YYYY"
    assert rule.mandatory is False
    assert rule.source_column == ""


def test_date_format_selector_only_renders_for_date_columns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Company Size", "Capture Date", "Submission Timestamp"])
    wb.save(template_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(t for t in at.text_input if t.label == "Client name").set_value("LTM Date Only Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="lead_template_path_input").set_value(template_path).run()
    at.selectbox(key="lead_template_sheet_select").set_value("Sheet1").run()
    assert not at.exception

    fmt_keys = {s.key for s in at.selectbox if s.key and s.key.startswith("ltm_fmt_")}
    assert fmt_keys == {"ltm_fmt_Capture Date", "ltm_fmt_Submission Timestamp"}

    at.checkbox(key="ltm_mandatory_Company Size").check().run()
    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    saved = load_profile("LTM Date Only Client", get_clients_dir())
    rule = next(r for r in saved.lead_template_mapping.rules if r.template_column == "Company Size")
    assert rule.mandatory is True
    assert rule.date_format == ""


def test_saved_date_format_on_a_non_date_named_column_is_still_shown_and_kept(tmp_path, monkeypatch):
    # An existing config must never silently lose its date format just
    # because the column name doesn't look like a date.
    monkeypatch.chdir(tmp_path)

    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Company Size"])
    wb.save(template_path)

    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile, LeadTemplateColumnRule, LeadTemplateMappingConfig
    from core.profile_store import load_profile, save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(
        name="Legacy Format Client", accumulated_report_path=str(tmp_path / "accumulated.xlsx"),
        lead_template_path=template_path, lead_template_sheet_name="Sheet1",
        lead_template_mapping=LeadTemplateMappingConfig(rules=[
            LeadTemplateColumnRule(template_column="Company Size", date_format="MM/DD/YYYY")]),
    ), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at.selectbox if s.label == "Client").set_value("Legacy Format Client").run()
    assert not at.exception
    assert at.selectbox(key="ltm_fmt_Company Size").value == "MM/DD/YYYY"
    assert not any(s.key == "ltm_fmt_Email" for s in at.selectbox)

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception
    resaved = load_profile("Legacy Format Client", get_clients_dir())
    rule = next(r for r in resaved.lead_template_mapping.rules if r.template_column == "Company Size")
    assert rule.date_format == "MM/DD/YYYY"


def test_switching_client_clears_stale_ltm_widget_state_for_same_named_column(tmp_path, monkeypatch):
    # Regression test (Finding 2, final review): ltm_mandatory_*/ltm_source_*/
    # ltm_source_text_*/ltm_fmt_*/ltm_fmt_custom_* widget keys are dynamic
    # per Lead Template COLUMN NAME, not a fresh per-item uuid the way
    # lead_template_tabs'/reference-source rows are -- so switching to a
    # DIFFERENT client whose template happens to use the exact same column
    # name ("Company Size") used to keep showing the previous client's
    # checkbox value under that same key.
    monkeypatch.chdir(tmp_path)

    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Company Size"])
    wb.save(template_path)

    at1 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at1.run()
    next(t for t in at1.text_input if t.label == "Client name").set_value("LTM Switch Client One").run()
    at1.text_input(key="accumulated_path_input").set_value(str(tmp_path / "acc1.xlsx")).run()
    at1.text_input(key="lead_template_path_input").set_value(template_path).run()
    at1.selectbox(key="lead_template_sheet_select").set_value("Sheet1").run()
    at1.checkbox(key="ltm_mandatory_Company Size").set_value(True).run()
    next(b for b in at1.button if "Save Client Profile" in b.label).click().run()
    assert not at1.exception

    at2 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at2.run()
    next(t for t in at2.text_input if t.label == "Client name").set_value("LTM Switch Client Two").run()
    at2.text_input(key="accumulated_path_input").set_value(str(tmp_path / "acc2.xlsx")).run()
    at2.text_input(key="lead_template_path_input").set_value(template_path).run()
    at2.selectbox(key="lead_template_sheet_select").set_value("Sheet1").run()
    next(b for b in at2.button if "Save Client Profile" in b.label).click().run()
    assert not at2.exception

    at3 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at3.run()
    next(r for r in at3.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at3.selectbox if s.label == "Client").set_value("LTM Switch Client One").run()
    assert at3.checkbox(key="ltm_mandatory_Company Size").value is True

    next(s for s in at3.selectbox if s.label == "Client").set_value("LTM Switch Client Two").run()
    assert at3.checkbox(key="ltm_mandatory_Company Size").value is False


def test_a_custom_date_format_survives_a_reload_and_resave(tmp_path, monkeypatch):
    # Regression test (Finding 3, final review): the date-format selectbox's
    # index lookup fell through to index 0 ("(no special formatting)")
    # whenever the saved date_format wasn't one of the preset strings,
    # instead of selecting "Custom..." and pre-filling the custom text box
    # -- so re-saving after reopening a client silently dropped its custom
    # format.
    monkeypatch.chdir(tmp_path)

    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Capture Date"])
    wb.save(template_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(t for t in at.text_input if t.label == "Client name").set_value("LTM Custom Format Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="lead_template_path_input").set_value(template_path).run()
    at.selectbox(key="lead_template_sheet_select").set_value("Sheet1").run()

    at.selectbox(key="ltm_fmt_Capture Date").set_value("Custom...").run()
    at.text_input(key="ltm_fmt_custom_Capture Date").set_value("%d %b %Y").run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    saved = load_profile("LTM Custom Format Client", get_clients_dir())
    rule = next(r for r in saved.lead_template_mapping.rules if r.template_column == "Capture Date")
    assert rule.date_format == "%d %b %Y"

    # Reopen the SAME client in a fresh session -- the selectbox must land
    # on "Custom..." (not silently fall back to index 0) and the custom
    # text box must be pre-filled with the saved value.
    at2 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at2.run()
    next(r for r in at2.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at2.selectbox if s.label == "Client").set_value("LTM Custom Format Client").run()

    fmt_select = at2.selectbox(key="ltm_fmt_Capture Date")
    assert fmt_select.value == "Custom..."
    custom_input = next(t for t in at2.text_input if t.key == "ltm_fmt_custom_Capture Date")
    assert custom_input.value == "%d %b %Y"

    next(b for b in at2.button if "Save Client Profile" in b.label).click().run()
    assert not at2.exception

    resaved = load_profile("LTM Custom Format Client", get_clients_dir())
    rule2 = next(r for r in resaved.lead_template_mapping.rules if r.template_column == "Capture Date")
    assert rule2.date_format == "%d %b %Y"


def test_multi_tab_client_can_configure_and_save_lead_template_column_mapping(tmp_path, monkeypatch):
    # Regression test (Finding 4, final review): in multi-tab mode,
    # lead_template_sheet_name is always "" (each tab has its own sheet), so
    # the guard `if lead_template_path and lead_template_sheet_name:` around
    # reading template headers for this section never passed -- it always
    # rendered zero columns for a multi-tab client, and since
    # lead_template_mapping_rules starts as [] with nothing appended,
    # saving silently wiped any previously-saved rules.
    monkeypatch.chdir(tmp_path)

    tab_file = str(tmp_path / "tab.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "EMEA"
    ws.append(["Email", "Company Size"])
    wb.save(tab_file)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    next(t for t in at.text_input if t.label == "Client name").set_value("LTM Multi Tab Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()

    multi_tab_checkbox = next(c for c in at.checkbox if "Route different CIDs" in c.label)
    multi_tab_checkbox.set_value(True).run()

    add_tab_button = next(b for b in at.button if b.key == "lead_template_tabs_add")
    add_tab_button.click().run()

    tab_file_input = next(t for t in at.text_input if t.label.startswith("File for this tab"))
    tab_file_input.set_value(tab_file).run()

    sheet_select = next(s for s in at.selectbox if s.label == "Tab (sheet) name")
    sheet_select.set_value("EMEA").run()

    assert any(c.key == "ltm_mandatory_Company Size" for c in at.checkbox)
    at.checkbox(key="ltm_mandatory_Company Size").set_value(True).run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    saved = load_profile("LTM Multi Tab Client", get_clients_dir())
    rule = next(r for r in saved.lead_template_mapping.rules if r.template_column == "Company Size")
    assert rule.mandatory is True


def test_saving_when_template_is_unreadable_does_not_wipe_existing_rules(tmp_path, monkeypatch):
    # Regression test (Finding 5, final review): if the template can't be
    # read at all (missing file, un-synced OneDrive placeholder, renamed
    # sheet), this section renders zero columns -- saving for a completely
    # unrelated reason must not silently drop every previously-saved rule.
    monkeypatch.chdir(tmp_path)

    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Company Size"])
    wb.save(template_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(t for t in at.text_input if t.label == "Client name").set_value("LTM Unreadable Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="lead_template_path_input").set_value(template_path).run()
    at.selectbox(key="lead_template_sheet_select").set_value("Sheet1").run()
    at.checkbox(key="ltm_mandatory_Company Size").set_value(True).run()
    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    os.remove(template_path)

    at2 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at2.run()
    next(r for r in at2.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at2.selectbox if s.label == "Client").set_value("LTM Unreadable Client").run()

    next(b for b in at2.button if "Save Client Profile" in b.label).click().run()
    assert not at2.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    saved = load_profile("LTM Unreadable Client", get_clients_dir())
    rule = next(r for r in saved.lead_template_mapping.rules if r.template_column == "Company Size")
    assert rule.mandatory is True


def test_saving_with_no_lead_template_configured_does_not_raise_and_saves_no_rules(tmp_path, monkeypatch):
    # Regression test for a previously-fixed NameError risk:
    # lead_template_mapping_rules used to only be defined inside a
    # Client-Mode-gated block, so saving a client with no Lead Template
    # (then "Lead QA & Upload" mode, now just a blank Lead Template path)
    # could have raised NameError on Save.
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    next(t for t in at.text_input if t.label == "Client name").set_value("LTM Upload Mode Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    saved = load_profile("LTM Upload Mode Client", get_clients_dir())
    assert saved.lead_template_mapping.rules == []
    assert saved.lead_template_path == ""
    assert saved.lead_template_multi_tab is False
    assert saved.lead_template_tabs == []


def test_client_mode_radio_is_gone_and_lead_template_section_always_shows(tmp_path, monkeypatch):
    # Client Mode ("Lead QA" / "Lead QA & Upload") was removed -- the Lead
    # Template section is always offered and decides itself by whether a
    # path is filled in.
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert not any("Lead QA & Upload" in r.options for r in at.radio)
    assert [r.label for r in at.radio].count("Mode") == 1
    assert any(t.key == "lead_template_path_input" for t in at.text_input)


def test_accumulated_field_mapping_saves_as_none_when_every_dropdown_left_unset(tmp_path, monkeypatch):
    # Regression test for a real bug: this section is documented as
    # "(optional)" -- leaving every dropdown at "No mapping" (the default)
    # used to still save a FieldMapping with every field blank instead of
    # None. Since `saved_mapping or fallback`-style code elsewhere treats
    # any FieldMapping object as valid regardless of its field values,
    # that blank-but-present mapping silently won over the fallback it
    # was supposed to defer to -- confirmed in a real client's profile
    # (Company/CID came out blank everywhere it was consulted).
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Email_Address", "First_Name", "Last_Name", "Company_Name", "CID"])
    wb.save(acc_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(t for t in at.text_input if t.label == "Client name").set_value("Blank Mapping Test Client").run()
    at.text_input(key="accumulated_path_input").set_value(acc_path).run()

    # Explicitly set every dropdown to "no mapping" -- some header names
    # here are auto-guessable (a seeded UI default, not a user choice), so
    # this is the only way to reliably simulate "the user left this whole
    # optional section unmapped" regardless of what got guessed.
    _no_mapping = "(none - this file has no such column)"
    for key in ("acc_map_email", "acc_map_first", "acc_map_last", "acc_map_company", "acc_map_cid"):
        at.selectbox(key=key).set_value(_no_mapping).run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("Blank Mapping Test Client", get_clients_dir())
    assert loaded.accumulated_field_mapping is None


def test_exclusion_source_accepts_a_csv_file_and_reads_its_columns_and_saves(tmp_path, monkeypatch):
    # Reference sources (Exclusion, TAL, Suppression, Dedupe) were Excel-only
    # -- picking a .csv here used to either error or leave the sheet/column
    # pickers empty. A CSV has no real sheets, so the picker must fall back
    # to one fixed pseudo-sheet rather than breaking.
    monkeypatch.chdir(tmp_path)
    csv_path = str(tmp_path / "exclusion.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("Account Name,Domain\nExcluded Co,excluded.com\n")

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    next(t for t in at.text_input if t.label == "Client name").set_value("CSV Test Client").run()
    next(c for c in at.checkbox if c.label == "Enable Exclusion check").set_value(True).run()
    assert not at.exception

    add_button = next(b for b in at.button if b.label == "Add Exclusion Source")
    add_button.click().run()
    assert not at.exception

    next(t for t in at.text_input if t.label == "Name").set_value("Global").run()
    file_path_input = next(t for t in at.text_input if t.label == "File path")
    file_path_input.set_value(csv_path).run()
    assert not at.exception

    sheet_select = next(s for s in at.selectbox if s.label == "Sheet")
    assert sheet_select.options == ["(CSV file)"]

    domain_select = next(s for s in at.selectbox if s.label == "Domain column")
    assert "Domain" in domain_select.options
    assert "Account Name" in domain_select.options

    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    save_button = next(b for b in at.button if "Save Client Profile" in b.label)
    save_button.click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("CSV Test Client", get_clients_dir())
    assert loaded.exclusion.enabled is True
    assert loaded.exclusion.sources[0].file_path == csv_path
    assert loaded.exclusion.sources[0].sheet_name == "(CSV file)"


def test_collation_checkbox_saves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    collation_checkbox = next(c for c in at.checkbox if c.label == "Enable file collation for this client")
    assert collation_checkbox.value is False
    collation_checkbox.set_value(True).run()
    assert not at.exception

    next(t for t in at.text_input if t.label == "Client name").set_value("Amazon Business EMEA").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()

    save_button = next(b for b in at.button if "Save Client Profile" in b.label)
    save_button.click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("Amazon Business EMEA", get_clients_dir())
    assert loaded.collation_enabled is True


def test_complex_account_checkbox_reveals_file_path_fields_and_saves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not any(t.label == "TAL file path" for t in at.text_input)

    complex_checkbox = next(c for c in at.checkbox if c.label == "This is a complex account")
    complex_checkbox.set_value(True).run()
    assert not at.exception

    next(t for t in at.text_input if t.label == "Client name").set_value("Dell APAC").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="complex_account_tal_path_input").set_value(str(tmp_path / "TAL.csv")).run()
    at.text_input(key="complex_account_specs_path_input").set_value(str(tmp_path / "specs.xlsx")).run()

    save_button = next(b for b in at.button if "Save Client Profile" in b.label)
    save_button.click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("Dell APAC", get_clients_dir())
    assert loaded.complex_account.enabled is True
    assert loaded.complex_account.tal_path == str(tmp_path / "TAL.csv")
    assert loaded.complex_account.specifications_path == str(tmp_path / "specs.xlsx")


def test_box_tracker_checkbox_reveals_fields_and_saves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not any(t.label == "Local mirror workbook path" for t in at.text_input)

    box_tracker_checkbox = next(c for c in at.checkbox if c.label == "This client uses a Box Tracker")
    box_tracker_checkbox.set_value(True).run()
    assert not at.exception

    next(t for t in at.text_input if t.label == "Client name").set_value("IBM APAC").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="box_tracker_mirror_path_input").set_value(str(tmp_path / "mirror.xlsx")).run()
    at.text_area(key="box_tracker_cid_map_input").set_value("118741,Bob\n118742,CXO").run()

    save_button = next(b for b in at.button if "Save Client Profile" in b.label)
    save_button.click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("IBM APAC", get_clients_dir())
    assert loaded.box_tracker.enabled is True
    assert loaded.box_tracker.mirror_workbook_path == str(tmp_path / "mirror.xlsx")
    assert loaded.box_tracker.cid_campaign_map == {"118741": "Bob", "118742": "CXO"}


def test_convertr_checkbox_reveals_fields_and_saves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not any("Convertr enterprise subdomain" in t.label for t in at.text_input)

    convertr_checkbox = next(c for c in at.checkbox if c.label == "This client uploads to Convertr")
    convertr_checkbox.set_value(True).run()
    assert not at.exception

    next(t for t in at.text_input if t.label == "Client name").set_value("Amazon Business EMEA").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    next(t for t in at.text_input if "Convertr enterprise subdomain" in t.label).set_value("amazonbusiness").run()
    next(t for t in at.text_input if "Convertr Publisher ID" in t.label).set_value("11003").run()
    at.text_area(key="convertr_campaigns_input").set_value(
        "120022,44709\n120021,44709\n120028,44706,80").run()
    at.text_area(key="convertr_field_map_cols_input").set_value("Email\nFirst Name").run()
    at.text_area(key="convertr_field_map_targets_input").set_value("email\nfirstName").run()

    # No per-campaign API key inputs anymore -- the Publisher API uses the
    # one account login for every campaign, so only a single "Test
    # connection" button should appear per unique campaign_id.
    assert not any("campaign 44709" in t.label for t in at.text_input)
    assert sum(1 for b in at.button if "Test connection" in b.label) == 2
    at.text_input(key="convertr_account_username").set_value("me@x.com").run()
    at.text_input(key="convertr_account_password").set_value("hunter2").run()

    save_button = next(b for b in at.button if "Save Client Profile" in b.label)
    save_button.click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir, get_convertr_account_credentials
    from core.profile_store import load_profile

    loaded = load_profile("Amazon Business EMEA", get_clients_dir())
    assert loaded.convertr.enabled is True
    assert loaded.convertr.enterprise == "amazonbusiness"
    assert loaded.convertr.publisher_id == "11003"
    assert loaded.convertr.field_mapping == {"Email": "email", "First Name": "firstName"}
    campaigns_by_cid = {c.cid: c for c in loaded.convertr.campaigns}
    assert campaigns_by_cid["120022"].campaign_id == "44709"
    assert campaigns_by_cid["120028"].campaign_id == "44706"
    assert campaigns_by_cid["120028"].global_form_id == "80"

    # The account credentials must NOT be in the shared client profile
    # JSON, only in the local app_settings.json.
    with open(get_clients_dir() + "/Amazon Business EMEA.json", encoding="utf-8") as f:
        assert "hunter2" not in f.read()
    assert get_convertr_account_credentials("Amazon Business EMEA") == {
        "username": "me@x.com", "password": "hunter2"}


def test_convertr_leadfile_column_mapping_saves_independently_of_qa_field_mapping(tmp_path, monkeypatch):
    # This is what lets a client with no QA at all (e.g. Amazon) use
    # Convertr without ever visiting Run Check first -- the leadfile column
    # mapping lives right here on Convertr's own section.
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Convertr").set_value(True).run()

    next(t for t in at.text_input if t.label == "Client name").set_value("Amazon Business EMEA").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    next(t for t in at.text_input if "Convertr enterprise subdomain" in t.label).set_value("amazonbusiness").run()
    next(t for t in at.text_input if "Convertr Publisher ID" in t.label).set_value("11003").run()
    at.text_input(key="convertr_lf_email").set_value("Email").run()
    at.text_input(key="convertr_lf_first").set_value("First Name").run()
    at.text_input(key="convertr_lf_last").set_value("Last Name").run()
    at.text_input(key="convertr_lf_company").set_value("Company").run()
    at.text_input(key="convertr_lf_cid").set_value("CID").run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("Amazon Business EMEA", get_clients_dir())
    assert loaded.field_mapping is None  # no QA configured
    assert loaded.convertr.leadfile_field_mapping.email == "Email"
    assert loaded.convertr.leadfile_field_mapping.cid == "CID"


def test_enhancio_checkbox_reveals_fields_and_saves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not any(t.key == "enhancio_allocations_input" for t in at.text_area)

    enhancio_checkbox = next(c for c in at.checkbox if c.label == "This client uploads to Enhancio")
    enhancio_checkbox.set_value(True).run()
    assert not at.exception

    next(t for t in at.text_input if t.label == "Client name").set_value("Amazon Business EMEA").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_area(key="enhancio_allocations_input").set_value("120022,L-22256\n120028,L-22257").run()
    at.text_area(key="enhancio_field_map_cols_input").set_value("Email\nFirst Name").run()
    at.text_area(key="enhancio_field_map_targets_input").set_value("Email Address\nFirst Name").run()
    at.text_area(key="enhancio_fixed_values_input").set_value(
        "L-22256,Company Size,1M - 5M\nL-22256,Lead Source,Website").run()
    at.text_input(key="enhancio_lf_email").set_value("Email").run()
    at.text_input(key="enhancio_lf_cid").set_value("CID").run()

    save_button = next(b for b in at.button if "Save Client Profile" in b.label)
    save_button.click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("Amazon Business EMEA", get_clients_dir())
    assert loaded.enhancio.enabled is True
    assert loaded.enhancio.field_mapping == {"Email": "Email Address", "First Name": "First Name"}
    allocations_by_cid = {a.cid: a for a in loaded.enhancio.allocations}
    assert allocations_by_cid["120022"].allocation_uid == "L-22256"
    assert allocations_by_cid["120028"].allocation_uid == "L-22257"
    assert loaded.enhancio.fixed_field_values == {
        "L-22256": {"Company Size": "1M - 5M", "Lead Source": "Website"}}
    assert loaded.enhancio.leadfile_field_mapping.email == "Email"
    assert loaded.enhancio.leadfile_field_mapping.cid == "CID"


def test_enhancio_field_mapping_handles_a_column_containing_commas_or_any_punctuation(tmp_path, monkeypatch):
    # A real leadfile column is often a verbatim survey/consent question
    # ("I'd like to receive news..., and I agree to...") that can contain
    # commas, arrows, or any other punctuation a delimiter-based format
    # might pick as "the separator." The paired-list design (two plain
    # lists, matched by line position) has no delimiter to confuse at
    # all -- each line is taken verbatim, in either box.
    monkeypatch.chdir(tmp_path)
    consent_text = "I'd like to receive news, and I agree to the -> policy, for more details."

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Enhancio").set_value(True).run()
    next(t for t in at.text_input if t.label == "Client name").set_value("Comma Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_area(key="enhancio_field_map_cols_input").set_value(f"Email\n{consent_text}").run()
    at.text_area(key="enhancio_field_map_targets_input").set_value(f"Email Address\n{consent_text}").run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("Comma Client", get_clients_dir())
    assert loaded.enhancio.field_mapping == {"Email": "Email Address", consent_text: consent_text}


def test_enhancio_field_mapping_round_trips(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    consent_text = "I'd like to receive news, and I agree, for more details, read the policy."

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Enhancio").set_value(True).run()
    next(t for t in at.text_input if t.label == "Client name").set_value("Comma Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_area(key="enhancio_field_map_cols_input").set_value(consent_text).run()
    at.text_area(key="enhancio_field_map_targets_input").set_value(consent_text).run()
    next(b for b in at.button if "Save Client Profile" in b.label).click().run()

    at2 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at2.run()
    next(r for r in at2.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at2.selectbox if s.label == "Client").set_value("Comma Client").run()

    cols_area = next(t for t in at2.text_area if t.key == "enhancio_field_map_cols_input")
    targets_area = next(t for t in at2.text_area if t.key == "enhancio_field_map_targets_input")
    assert cols_area.value == consent_text
    assert targets_area.value == consent_text


def test_field_mapping_mismatched_line_counts_shows_error_and_keeps_existing_mapping(tmp_path, monkeypatch):
    # A typo (an extra/missing line in just one box) must be caught clearly
    # rather than silently zipping the wrong lines together -- and must not
    # destroy whatever mapping was already saved.
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Enhancio").set_value(True).run()
    next(t for t in at.text_input if t.label == "Client name").set_value("Mismatch Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_area(key="enhancio_field_map_cols_input").set_value("Email\nFirst Name").run()
    at.text_area(key="enhancio_field_map_targets_input").set_value("Email Address").run()

    assert any("don't have the same number of lines" in e.value for e in at.error)

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("Mismatch Client", get_clients_dir())
    assert loaded.enhancio.field_mapping == {}  # nothing was saved previously, so still empty


def test_convertr_field_mapping_handles_a_column_containing_a_comma(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Convertr").set_value(True).run()
    next(t for t in at.text_input if t.label == "Client name").set_value("Comma Client").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_area(key="convertr_field_map_cols_input").set_value(
        "I'd like to receive news, and I agree to the policy").run()
    at.text_area(key="convertr_field_map_targets_input").set_value("optIn").run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("Comma Client", get_clients_dir())
    assert loaded.convertr.field_mapping == {
        "I'd like to receive news, and I agree to the policy": "optIn"}


def test_enhancio_fetch_allocations_button_shows_client_id_prompt_when_unset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Enhancio").set_value(True).run()

    assert any("No Enhancio Client ID configured" in c.value for c in at.caption)
    assert not any("Fetch allocations from Enhancio" in b.label for b in at.button)


def test_enhancio_test_connection_flags_a_mandatory_field_with_no_mapping(tmp_path, monkeypatch):
    # This is the actual safeguard against the recurring "Missing mandatory
    # field(s)" failure at upload time: Test connection now cross-checks
    # Describe Fields' mandatory list against the field mapping above it,
    # so a gap is caught here -- before ever sending a single lead -- not
    # discovered later from Enhancio's own rejected-lead count.
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Enhancio").set_value(True).run()
    at.text_area(key="enhancio_allocations_input").set_value("120022,L-22256").run()
    at.text_area(key="enhancio_field_map_cols_input").set_value("Email").run()
    at.text_area(key="enhancio_field_map_targets_input").set_value("Email Address").run()

    from core.app_settings import save_enhancio_client_id
    save_enhancio_client_id("CID123")
    at.run()

    with patch("core.enhancio_client.get_access_token", return_value={"access_token": "tok"}), \
         patch("core.enhancio_client.describe_fields", return_value=[
             {"fieldLabel": "Email Address", "mandatory": "Y"},
             {"fieldLabel": "First Name", "mandatory": "Y"},
         ]):
        next(b for b in at.button if b.label == "Test connection - allocation L-22256").click().run()

    assert not at.exception
    assert any("First Name" in e.value and "NO mapping entry" in e.value for e in at.error)
    assert any("mapped from leadfile column \"Email\"" in s.value for s in at.success)


def test_enhancio_test_connection_shows_a_picklist_fields_allowed_values(tmp_path, monkeypatch):
    # A field constrained to a fixed picklist rejects anything outside it
    # as "Invalid field value" at upload time, with no indication of what
    # IS valid -- Test connection surfaces Describe Fields' own allowed
    # values list so a rejected-batch mismatch can be diagnosed here.
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Enhancio").set_value(True).run()
    at.text_area(key="enhancio_allocations_input").set_value("120022,L-22256").run()
    at.text_area(key="enhancio_field_map_cols_input").set_value("Email").run()
    at.text_area(key="enhancio_field_map_targets_input").set_value("Email Address").run()

    from core.app_settings import save_enhancio_client_id
    save_enhancio_client_id("CID123")
    at.run()

    with patch("core.enhancio_client.get_access_token", return_value={"access_token": "tok"}), \
         patch("core.enhancio_client.describe_fields", return_value=[
             {"fieldLabel": "Email Address", "mandatory": "Y"},
             {"fieldLabel": "Industry", "mandatory": "Y", "fieldValues": ["All"]},
         ]):
        next(b for b in at.button if b.label == "Test connection - allocation L-22256").click().run()

    assert not at.exception
    assert any("Allowed values: All" in c.value for c in at.caption)


def test_box_tracker_lead_template_map_and_pacing_skip_fields_save(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    box_tracker_checkbox = next(c for c in at.checkbox if c.label == "This client uses a Box Tracker")
    box_tracker_checkbox.set_value(True).run()

    next(t for t in at.text_input if t.label == "Client name").set_value("IBM APAC").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="box_tracker_mirror_path_input").set_value(str(tmp_path / "mirror.xlsx")).run()
    at.text_area(key="box_tracker_lead_template_map_input").set_value(
        f"118741,{tmp_path / 'bob_template.xlsx'}").run()
    at.text_area(key="box_tracker_pacing_skipped_input").set_value("CXO").run()

    save_button = next(b for b in at.button if "Save Client Profile" in b.label)
    save_button.click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("IBM APAC", get_clients_dir())
    assert loaded.box_tracker.cid_lead_template_path == {"118741": str(tmp_path / "bob_template.xlsx")}
    assert loaded.box_tracker.pacing_skipped_campaigns == ["CXO"]


def test_saving_integrate_section_persists_sid_and_field_mapping(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    next(c for c in at.checkbox if c.label == "This client uploads to Integrate").set_value(True).run()
    next(t for t in at.text_input if t.label == "Client name").set_value("Everpure EMEA").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="integrate_sid_input").set_value("d8a9deeb-7bb2-4832-b3d9-1df8a9fe5cab").run()
    at.text_area(key="integrate_field_map_cols_input").set_value("Email\nFirst Name").run()
    at.text_area(key="integrate_field_map_targets_input").set_value("email\nfirst_name").run()
    at.text_area(key="integrate_fixed_values_input").set_value("country,UK").run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("Everpure EMEA", get_clients_dir())
    assert loaded.integrate.enabled is True
    assert loaded.integrate.sid == "d8a9deeb-7bb2-4832-b3d9-1df8a9fe5cab"
    assert loaded.integrate.field_mapping == {"Email": "email", "First Name": "first_name"}
    assert loaded.integrate.fixed_field_values == {"country": "UK"}


def test_invalid_integrate_target_attribute_warns_but_still_saves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    next(c for c in at.checkbox if c.label == "This client uploads to Integrate").set_value(True).run()
    next(t for t in at.text_input if t.label == "Client name").set_value("Everpure EMEA").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
    at.text_input(key="integrate_sid_input").set_value("d8a9deeb-7bb2-4832-b3d9-1df8a9fe5cab").run()
    at.text_area(key="integrate_field_map_cols_input").set_value("Email").run()
    # "emial" is a typo -- not one of Integrate's 17 real attribute names.
    at.text_area(key="integrate_field_map_targets_input").set_value("emial").run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception
    assert any("emial" in w.value for w in at.warning)

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    loaded = load_profile("Everpure EMEA", get_clients_dir())
    assert loaded.integrate.field_mapping == {"Email": "emial"}


def test_saving_google_sheets_tabs_and_mandatory_column_persists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, save_google_sheets_key_path
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_google_sheets_key_path(str(tmp_path / "fake-key.json"))

    with patch("core.google_sheets_client.read_sheet_headers",
               return_value=["First Name", "Last Name", "Work Email"]):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(t for t in at.text_input if t.label == "Client name").set_value("China Webinar Client").run()
        at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "acc.xlsx")).run()

        at.checkbox(key="gs_enabled").set_value(True).run()
        at.text_area(key="gs_tabs_input").set_value(
            "119999,https://docs.google.com/spreadsheets/d/1o_v7oMh6Y5VcX0COIjWQ_y00IVKGbwbznCEzNGcyhpU/edit\n"
            "120000,https://docs.google.com/spreadsheets/d/1zU6rm9EvksfJUA91JrLIOPneWTNRgjK6jpm4Ukb2PPA/edit,Leads"
        ).run()
        at.checkbox(key="gs_mandatory_Work Email").set_value(True).run()

        next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile
    saved = load_profile("China Webinar Client", get_clients_dir())

    assert saved.google_sheets.enabled is True
    assert saved.google_sheets.tabs == [
        GoogleSheetTab(cid="119999", sheet_id="1o_v7oMh6Y5VcX0COIjWQ_y00IVKGbwbznCEzNGcyhpU"),
        GoogleSheetTab(cid="120000", sheet_id="1zU6rm9EvksfJUA91JrLIOPneWTNRgjK6jpm4Ukb2PPA", worksheet_name="Leads"),
    ]
    rule = next(r for r in saved.google_sheets.mapping.rules if r.template_column == "Work Email")
    assert rule.mandatory is True


def test_gs_date_format_selector_only_renders_for_date_columns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, save_google_sheets_key_path
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_google_sheets_key_path(str(tmp_path / "fake-key.json"))

    with patch("core.google_sheets_client.read_sheet_headers",
               return_value=["Work Email", "Company Size", "Lead Date", "Created Time"]):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(t for t in at.text_input if t.label == "Client name").set_value("GS Date Only Client").run()
        at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "acc.xlsx")).run()
        at.checkbox(key="gs_enabled").set_value(True).run()
        at.text_area(key="gs_tabs_input").set_value(
            "119999,https://docs.google.com/spreadsheets/d/1o_v7oMh6Y5VcX0COIjWQ_y00IVKGbwbznCEzNGcyhpU/edit"
        ).run()
        assert not at.exception
        fmt_keys = {s.key for s in at.selectbox if s.key and s.key.startswith("gs_fmt_")}
        assert fmt_keys == {"gs_fmt_Lead Date", "gs_fmt_Created Time"}


def test_switching_client_clears_stale_gs_widget_state_for_same_named_column(tmp_path, monkeypatch):
    # Regression test, matching the fix already applied to the sibling Lead
    # Template Column Mapping section (see
    # test_switching_client_clears_stale_ltm_widget_state_for_same_named_column
    # in this same file) for the same failure mode: gs_mandatory_*/gs_fmt_*
    # widget keys are dynamic per Google Sheets column name, not a fresh
    # per-item uuid -- switching to a different client whose Sheet happens
    # to use the same column name ("Work Email") could otherwise keep
    # showing the previous client's checkbox value under that same key.
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, save_google_sheets_key_path
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_google_sheets_key_path(str(tmp_path / "fake-key.json"))

    with patch("core.google_sheets_client.read_sheet_headers", return_value=["Work Email"]):
        at1 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at1.run()
        next(t for t in at1.text_input if t.label == "Client name").set_value("GS Switch Client One").run()
        at1.text_input(key="accumulated_path_input").set_value(str(tmp_path / "acc1.xlsx")).run()
        at1.checkbox(key="gs_enabled").set_value(True).run()
        at1.text_area(key="gs_tabs_input").set_value(
            "119999,https://docs.google.com/spreadsheets/d/1o_v7oMh6Y5VcX0COIjWQ_y00IVKGbwbznCEzNGcyhpU/edit"
        ).run()
        at1.checkbox(key="gs_mandatory_Work Email").set_value(True).run()
        next(b for b in at1.button if "Save Client Profile" in b.label).click().run()
        assert not at1.exception

        at2 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at2.run()
        next(t for t in at2.text_input if t.label == "Client name").set_value("GS Switch Client Two").run()
        at2.text_input(key="accumulated_path_input").set_value(str(tmp_path / "acc2.xlsx")).run()
        at2.checkbox(key="gs_enabled").set_value(True).run()
        at2.text_area(key="gs_tabs_input").set_value(
            "120000,https://docs.google.com/spreadsheets/d/1zU6rm9EvksfJUA91JrLIOPneWTNRgjK6jpm4Ukb2PPA/edit"
        ).run()
        next(b for b in at2.button if "Save Client Profile" in b.label).click().run()
        assert not at2.exception

        at3 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at3.run()
        next(r for r in at3.radio if r.label == "Mode").set_value("Edit existing client").run()
        next(s for s in at3.selectbox if s.label == "Client").set_value("GS Switch Client One").run()
        assert at3.checkbox(key="gs_mandatory_Work Email").value is True

        next(s for s in at3.selectbox if s.label == "Client").set_value("GS Switch Client Two").run()
        assert at3.checkbox(key="gs_mandatory_Work Email").value is False


def test_saving_when_google_sheet_is_unreadable_does_not_wipe_existing_rules(tmp_path, monkeypatch):
    # Regression test, matching the fix already applied to the sibling Lead
    # Template Column Mapping section (see
    # test_saving_when_template_is_unreadable_does_not_wipe_existing_rules
    # in this same file) for the same failure mode: if the Sheet can't be
    # read at all this run (key revoked, Sheet access removed, transient
    # API error), this section renders zero columns -- saving for a
    # completely unrelated reason must not silently drop every
    # previously-saved Google Sheets mapping rule.
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, save_google_sheets_key_path
    from core.google_sheets_client import GoogleSheetsError
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_google_sheets_key_path(str(tmp_path / "fake-key.json"))

    with patch("core.google_sheets_client.read_sheet_headers",
               return_value=["First Name", "Last Name", "Work Email"]):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(t for t in at.text_input if t.label == "Client name").set_value("GS Unreadable Client").run()
        at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "acc.xlsx")).run()
        at.checkbox(key="gs_enabled").set_value(True).run()
        at.text_area(key="gs_tabs_input").set_value(
            "119999,https://docs.google.com/spreadsheets/d/1o_v7oMh6Y5VcX0COIjWQ_y00IVKGbwbznCEzNGcyhpU/edit"
        ).run()
        at.checkbox(key="gs_mandatory_Work Email").set_value(True).run()
        next(b for b in at.button if "Save Client Profile" in b.label).click().run()
        assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile
    saved = load_profile("GS Unreadable Client", get_clients_dir())
    rule = next(r for r in saved.google_sheets.mapping.rules if r.template_column == "Work Email")
    assert rule.mandatory is True

    with patch("core.google_sheets_client.read_sheet_headers",
               side_effect=GoogleSheetsError("Sheet access revoked")):
        at2 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at2.run()
        next(r for r in at2.radio if r.label == "Mode").set_value("Edit existing client").run()
        next(s for s in at2.selectbox if s.label == "Client").set_value("GS Unreadable Client").run()
        next(b for b in at2.button if "Save Client Profile" in b.label).click().run()
        assert not at2.exception

    resaved = load_profile("GS Unreadable Client", get_clients_dir())
    rule2 = next(r for r in resaved.google_sheets.mapping.rules if r.template_column == "Work Email")
    assert rule2.mandatory is True


def test_a_custom_gs_date_format_survives_a_reload_and_resave(tmp_path, monkeypatch):
    # Regression test, matching the fix already applied to the sibling Lead
    # Template Column Mapping section (see
    # test_a_custom_date_format_survives_a_reload_and_resave in this same
    # file): the "Custom..." entry in _GS_DATE_FORMAT_OPTIONS previously had
    # no free-text input behind it at all, so selecting it saved the
    # literal string "Custom..." as date_format instead of a real strftime
    # format -- and even once fixed, the date-format selectbox's index
    # lookup on reload must land on "Custom..." (not silently fall back to
    # index 0) with the custom text box pre-filled, or a saved custom
    # format would be silently dropped on the very next save.
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, save_google_sheets_key_path
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_google_sheets_key_path(str(tmp_path / "fake-key.json"))

    with patch("core.google_sheets_client.read_sheet_headers", return_value=["Capture Date"]):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(t for t in at.text_input if t.label == "Client name").set_value("GS Custom Format Client").run()
        at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()
        at.checkbox(key="gs_enabled").set_value(True).run()
        at.text_area(key="gs_tabs_input").set_value(
            "119999,https://docs.google.com/spreadsheets/d/1o_v7oMh6Y5VcX0COIjWQ_y00IVKGbwbznCEzNGcyhpU/edit"
        ).run()

        at.selectbox(key="gs_fmt_Capture Date").set_value("Custom...").run()
        at.text_input(key="gs_fmt_custom_Capture Date").set_value("%d %b %Y").run()

        next(b for b in at.button if "Save Client Profile" in b.label).click().run()
        assert not at.exception

        from core.app_settings import get_clients_dir
        from core.profile_store import load_profile

        saved = load_profile("GS Custom Format Client", get_clients_dir())
        rule = next(r for r in saved.google_sheets.mapping.rules if r.template_column == "Capture Date")
        assert rule.date_format == "%d %b %Y"

        # Reopen the SAME client in a fresh session -- the selectbox must
        # land on "Custom..." (not silently fall back to index 0) and the
        # custom text box must be pre-filled with the saved value.
        at2 = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at2.run()
        next(r for r in at2.radio if r.label == "Mode").set_value("Edit existing client").run()
        next(s for s in at2.selectbox if s.label == "Client").set_value("GS Custom Format Client").run()

        fmt_select = at2.selectbox(key="gs_fmt_Capture Date")
        assert fmt_select.value == "Custom..."
        custom_input = next(t for t in at2.text_input if t.key == "gs_fmt_custom_Capture Date")
        assert custom_input.value == "%d %b %Y"

        next(b for b in at2.button if "Save Client Profile" in b.label).click().run()
        assert not at2.exception

    resaved = load_profile("GS Custom Format Client", get_clients_dir())
    rule2 = next(r for r in resaved.google_sheets.mapping.rules if r.template_column == "Capture Date")
    assert rule2.date_format == "%d %b %Y"


def test_saving_a_client_group_persists_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(t for t in at.text_input if t.label == "Client name").set_value("Autodesk APAC").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "acc.xlsx")).run()
    from core.client_picker import NEW_GROUP_SENTINEL
    at.selectbox(key="client_group_select").set_value(NEW_GROUP_SENTINEL).run()
    at.text_input(key="client_group_new").set_value("  Autodesk ").run()
    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.profile_store import load_profile
    saved = load_profile("Autodesk APAC", get_clients_dir())
    assert saved.client_group == "Autodesk"


def test_edit_existing_client_picker_still_selects_by_exact_name_when_ungrouped(tmp_path, monkeypatch):
    # The load-bearing backward-compat guarantee from this plan's Global
    # Constraints: an ungrouped client (every profile that existed before
    # this task) must still be selectable through one plain selectbox
    # labeled "Client", by its own exact name, with no second step.
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Existing Client", accumulated_report_path="a.xlsx"), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    client_boxes = [s for s in at.selectbox if s.label == "Client"]
    assert len(client_boxes) == 1
    client_boxes[0].set_value("Existing Client").run()
    assert not at.exception


def test_switching_clients_resets_the_client_group_field(tmp_path, monkeypatch):
    # Regression test: the client group dropdown is a keyed widget (like
    # accumulated_path_input), so it must be re-seeded in the profile-switch
    # reset block below -- otherwise switching from a grouped profile to an
    # ungrouped one would leave the previous profile's group name showing,
    # and saving would silently put the new profile into the wrong group.
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Autodesk APAC", accumulated_report_path="a.xlsx",
                                client_group="Autodesk"), get_clients_dir())
    save_profile(ClientProfile(name="Autodesk EMEA", accumulated_report_path="a.xlsx",
                                client_group="Autodesk"), get_clients_dir())
    save_profile(ClientProfile(name="Ungrouped Client", accumulated_report_path="b.xlsx"), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    group_box = next(s for s in at.selectbox if s.label == "Group")
    assert group_box.options == ["All groups", "Autodesk", "Ungrouped"]
    group_box.set_value("Autodesk").run()
    client_box = next(s for s in at.selectbox if s.label == "Client")
    assert client_box.options == ["Autodesk APAC", "Autodesk EMEA"]
    client_box.set_value("Autodesk EMEA").run()
    assert not at.exception
    assert next(t for t in at.text_input if t.label == "Client name").value == "Autodesk EMEA"
    assert at.selectbox(key="client_group_select").value == "Autodesk"
    assert at.selectbox(key="client_group_select").label == "Assign to group"

    next(s for s in at.selectbox if s.label == "Group").set_value("Ungrouped").run()
    assert next(s for s in at.selectbox if s.label == "Client").value == "Ungrouped Client"
    assert at.selectbox(key="client_group_select").value == ""
    assert at.selectbox(key="client_group_select").format_func("") == "No group"


def test_switching_group_auto_selects_first_client_and_loads_its_profile(tmp_path, monkeypatch):
    # Changing Group must show AND load the new group's first client with no
    # manual Client pick, and the profile-switch reset (_loaded_sources_for)
    # must fire for it so no field is carried over from the previous client.
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    for name, path, group in [("Alpha One", "alpha1.xlsx", "Group A"), ("Alpha Two", "alpha2.xlsx", "Group A"),
                              ("Beta One", "beta1.xlsx", "Group B"), ("Beta Two", "beta2.xlsx", "Group B")]:
        save_profile(ClientProfile(name=name, accumulated_report_path=path, client_group=group), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    at.selectbox(key="client_setup_group_filter").set_value("Group A").run()
    at.selectbox(key="client_setup_client_profile").set_value("Alpha Two").run()
    assert at.text_input(key="accumulated_path_input").value == "alpha2.xlsx"

    at.selectbox(key="client_setup_group_filter").set_value("Group B").run()
    assert not at.exception
    client_box = at.selectbox(key="client_setup_client_profile")
    assert client_box.value == "Beta One"
    assert client_box.proto.set_value is True
    assert at.session_state["_loaded_sources_for"].endswith("::Beta One")
    assert next(t for t in at.text_input if t.label == "Client name").value == "Beta One"
    assert at.text_input(key="accumulated_path_input").value == "beta1.xlsx"
    assert at.selectbox(key="client_group_select").value == "Group B"


def test_create_mode_assign_to_group_lists_all_existing_groups(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Autodesk APAC", accumulated_report_path="a.xlsx",
                                client_group="Autodesk"), get_clients_dir())
    save_profile(ClientProfile(name="Bee", accumulated_report_path="a.xlsx", client_group="Bravo"),
                 get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert not [s for s in at.selectbox if s.label == "Group"]
    box = at.selectbox(key="client_group_select")
    assert box.label == "Assign to group"
    assert box.options == [
        "No group", "Autodesk (1 client)", "Bravo (1 client)", "+ Create new group…"]

def _tab(at, suffix):
    return next(t for t in at.tabs if t.label.endswith(suffix))


def test_client_setup_has_basics_delivery_checks_tabs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    labels = {t.label for t in at.tabs}
    assert {":material/badge: Basics", ":material/send: Delivery", ":material/checklist: Checks"} <= labels
    for check in ("Leadcap", "Exclusion", "TAL", "Suppression", "Dedupe", "Complex Account", "Duplicate"):
        assert any(label.startswith(check) for label in labels), check


def test_sections_live_in_their_new_tabs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    basics, delivery, checks = _tab(at, "Basics"), _tab(at, "Delivery"), _tab(at, "Checks")

    assert any(t.label == "Client name" for t in basics.text_input)
    assert any(t.label == "Jira ticket key or link (optional)" for t in basics.text_input)
    assert any(c.label == "Enable file collation for this client" for c in basics.checkbox)

    assert not any(r.label == "Mode" for r in delivery.radio)
    assert any(t.key == "lead_template_path_input" for t in delivery.text_input)
    delivery_boxes = {c.label for c in delivery.checkbox}
    assert "This client delivers leads to Google Sheets" in delivery_boxes
    assert "This client uploads to Convertr" in delivery_boxes
    assert "This client uses a Box Tracker" in delivery_boxes

    check_boxes = {c.label for c in checks.checkbox}
    assert "Enable Duplicate check" in check_boxes
    assert "This is a complex account" in check_boxes
    assert "This client uploads to Convertr" not in check_boxes


def test_new_edit_mode_radio_stays_above_the_tabs(tmp_path, monkeypatch):
    # Nine existing tests pick the FIRST radio labeled "Mode" to mean the
    # New/Edit radio (the old Client Mode radio used to share that label).
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    first_mode = next(r for r in at.radio if r.label == "Mode")
    assert "Edit existing client" in first_mode.options


def test_summary_strip_reflects_live_checkbox_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    strip = next(m for m in at.markdown if "badge[Leadcap" in m.value)
    assert ":gray-badge[Duplicate :material/radio_button_unchecked: Off]" in strip.value

    next(c for c in at.checkbox if c.label == "Enable Duplicate check").check().run()
    next(c for c in at.checkbox if c.label == "Enable Exclusion check").check().run()
    strip = next(m for m in at.markdown if "badge[Leadcap" in m.value)
    assert ":green-badge[Duplicate :material/check_circle: On]" in strip.value
    assert ":orange-badge[Exclusion :material/warning: Needs setup]" in strip.value  # enabled, no sources


def test_check_tab_label_shows_configured_chip_for_saved_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile, DuplicateConfig
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Dup Client", accumulated_report_path="a.xlsx",
                               duplicate=DuplicateConfig(enabled=True)), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at.selectbox if s.label == "Client").set_value("Dup Client").run()
    assert not at.exception
    labels = [t.label for t in at.tabs]
    assert "Duplicate :blue-badge[:material/task_alt: Configured]" in labels
    assert "Leadcap" in labels  # off in the saved profile -> no chip


def test_blank_client_name_error_carries_a_suggestion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    err = next(e for e in at.error if "Client name is required." in e.value)
    assert "**Suggested fix:**" in err.value and "Basics" in err.value


def test_enabled_check_with_no_sources_warns_with_a_next_step(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "Enable TAL check").check().run()
    warn = next(w for w in at.warning if "TAL is enabled but no sources are configured" in w.value)
    assert "Add TAL Source" in warn.value
    assert any(c.value.startswith(":material/inbox: No TAL sources configured yet") for c in at.caption)


def test_disabled_check_shows_an_empty_state_pointing_at_its_toggle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert any(c.value.startswith(":material/toggle_off: Exclusion check is off.")
               and "Enable Exclusion check" in c.value for c in at.caption)


def test_field_mapping_line_count_error_uses_the_shared_problem_helper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Enhancio").set_value(True).run()
    at.text_area(key="enhancio_field_map_cols_input").set_value("Email\nFirst Name").run()
    at.text_area(key="enhancio_field_map_targets_input").set_value("Email Address").run()
    err = next(e for e in at.error if "don't have the same number of lines" in e.value)
    assert err.icon == ":material/error:"
    assert "**Suggested fix:**" in err.value


def test_enhancio_connection_failure_keeps_the_error_text_via_the_shared_helper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_enhancio_client_id
    from core.enhancio_client import EnhancioError
    save_enhancio_client_id("CID123")

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Enhancio").set_value(True).run()
    with patch("core.enhancio_client.get_access_token",
               side_effect=EnhancioError("Enhancio returned 401: bad client id")):
        next(b for b in at.button if b.label == "Fetch allocations from Enhancio").click().run()
    assert not at.exception
    err = next(e for e in at.error if "Enhancio returned 401: bad client id" in e.value)
    assert not err.value.startswith("❌")
    assert err.icon == ":material/error:"
    assert "**Suggested fix:**" in err.value


def test_convertr_test_connection_failure_keeps_the_error_text_via_the_shared_helper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.convertr_client import ConvertrError

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Convertr").set_value(True).run()
    next(t for t in at.text_input if t.label.startswith("Convertr enterprise subdomain")).set_value(
        "amazonbusiness").run()
    at.text_area(key="convertr_campaigns_input").set_value("120022,44709").run()
    at.text_input(key="convertr_account_username").set_value("me@x.com").run()
    at.text_input(key="convertr_account_password").set_value("hunter2").run()
    with patch("core.convertr_client.login", side_effect=ConvertrError("Convertr returned 401: bad login")):
        at.button(key="convertr_test_44709").click().run()
    assert not at.exception
    err = next(e for e in at.error if "Convertr returned 401: bad login" in e.value)
    assert not err.value.startswith("❌")
    assert err.icon == ":material/error:"


def test_disabled_delivery_destinations_show_empty_states_pointing_at_their_toggle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    captions = [c.value for c in at.caption]
    for message, toggle in [
        ("Google Sheets delivery is disabled for this client.", "This client delivers leads to Google Sheets"),
        ("Box Tracker is disabled for this client.", "This client uses a Box Tracker"),
        ("Convertr upload is disabled for this client.", "This client uploads to Convertr"),
        ("Enhancio upload is disabled for this client.", "This client uploads to Enhancio"),
        ("Integrate upload is disabled for this client.", "This client uploads to Integrate"),
    ]:
        assert any(c.startswith(f":material/toggle_off: {message}") and toggle in c for c in captions), message
    assert not any("⚙️" in c for c in captions)  # stale pre-Phase-1 nav-icon references are gone

    next(c for c in at.checkbox if c.label == "This client uploads to Enhancio").set_value(True).run()
    assert any(c.value.startswith(":material/key_off: No Enhancio Client ID configured yet.") for c in at.caption)


def _new_client(at, tmp_path, name):
    at.run()
    next(t for t in at.text_input if t.label == "Client name").set_value(name).run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "acc.xlsx")).run()


def _save(at):
    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception


def _seed_groups(tmp_path):
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Autodesk APAC", accumulated_report_path="a.xlsx",
                               client_group="Autodesk"), get_clients_dir())
    save_profile(ClientProfile(name="Solo One", accumulated_report_path="a.xlsx",
                               client_group="Solo"), get_clients_dir())
    save_profile(ClientProfile(name="Plain", accumulated_report_path="a.xlsx"), get_clients_dir())
    return get_clients_dir()


def test_client_group_dropdown_lists_existing_groups_and_saves_picked_one(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clients_dir = _seed_groups(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    _new_client(at, tmp_path, "Autodesk EMEA")
    box = at.selectbox(key="client_group_select")
    assert box.options == ["No group", "Autodesk (1 client)", "Solo (1 client)", "+ Create new group…"]
    assert box.value == ""
    box.set_value("Autodesk").run()
    assert not any(t.key == "client_group_new" for t in at.text_input)
    _save(at)
    from core.profile_store import load_profile
    assert load_profile("Autodesk EMEA", clients_dir).client_group == "Autodesk"


def test_client_group_dropdown_no_group_saves_blank(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clients_dir = _seed_groups(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    _new_client(at, tmp_path, "Fresh")
    at.selectbox(key="client_group_select").set_value("Solo").run()
    at.selectbox(key="client_group_select").set_value("").run()
    _save(at)
    from core.profile_store import load_profile
    assert load_profile("Fresh", clients_dir).client_group == ""


def test_client_group_create_new_with_blank_name_saves_no_group(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clients_dir = _seed_groups(tmp_path)
    from core.client_picker import NEW_GROUP_SENTINEL
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    _new_client(at, tmp_path, "Fresh")
    at.selectbox(key="client_group_select").set_value(NEW_GROUP_SENTINEL).run()
    at.text_input(key="client_group_new").set_value("   ").run()
    _save(at)
    from core.profile_store import load_profile
    assert load_profile("Fresh", clients_dir).client_group == ""


def test_edit_mode_preselects_current_group_and_resaves_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clients_dir = _seed_groups(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at.selectbox if s.label == "Client").set_value("Solo One").run()
    assert at.selectbox(key="client_group_select").value == "Solo"
    next(s for s in at.selectbox if s.label == "Client").set_value("Plain").run()
    assert at.selectbox(key="client_group_select").value == ""
    at.selectbox(key="client_group_select").set_value("Autodesk").run()
    _save(at)
    from core.profile_store import load_profile
    assert load_profile("Plain", clients_dir).client_group == "Autodesk"


def _save_two_delivery_profiles():
    from core.app_settings import get_clients_dir, save_convertr_account_credentials
    from core.models import (BoxTrackerConfig, ClientProfile, ComplexAccountConfig, ConvertrCampaignMapping,
                             ConvertrConfig, EnhancioAllocationMapping, EnhancioConfig, FieldMapping,
                             IntegrateConfig)
    from core.profile_store import save_profile

    def _make(tag: str) -> ClientProfile:
        lf = FieldMapping(email=f"{tag} Email", first_name=f"{tag} First", last_name=f"{tag} Last",
                          company=f"{tag} Co", cid=f"{tag} CID")
        return ClientProfile(
            name=f"Switch {tag}", accumulated_report_path=f"{tag}_acc.xlsx",
            complex_account=ComplexAccountConfig(enabled=True, tal_path=f"{tag}_tal.xlsx",
                                                 specifications_path=f"{tag}_specs.xlsx"),
            box_tracker=BoxTrackerConfig(enabled=True, mirror_workbook_path=f"{tag}_mirror.xlsx",
                                         cid_campaign_map={f"{tag}1": f"{tag} Camp"},
                                         cid_lead_template_path={f"{tag}1": f"{tag}_tmpl.xlsx"},
                                         pacing_skipped_campaigns=[f"{tag} Skip"]),
            convertr=ConvertrConfig(enabled=True, enterprise=f"{tag.lower()}ent", publisher_id=f"{tag}pub",
                                    campaigns=[ConvertrCampaignMapping(cid=f"{tag}1", campaign_id=f"{tag}C",
                                                                       global_form_id="")],
                                    field_mapping={f"{tag} Col": f"{tag} Target"}, leadfile_field_mapping=lf),
            enhancio=EnhancioConfig(enabled=True,
                                    allocations=[EnhancioAllocationMapping(cid=f"{tag}1",
                                                                           allocation_uid=f"{tag}uid")],
                                    field_mapping={f"{tag} ECol": f"{tag} ETarget"},
                                    fixed_field_values={f"{tag}uid": {"Lead Source": f"{tag} Src"}},
                                    leadfile_field_mapping=lf),
            integrate=IntegrateConfig(enabled=True, sid=f"{tag}-sid", callback_url=f"https://{tag}.example",
                                      field_mapping={f"{tag} ICol": "email"},
                                      fixed_field_values={"country": f"{tag}land"}, leadfile_field_mapping=lf),
        )

    for tag in ("A", "B"):
        save_profile(_make(tag), get_clients_dir())
        save_convertr_account_credentials(f"Switch {tag}", f"{tag}-user", f"{tag}-pass")


_PER_CLIENT_TEXT_KEYS = {
    "complex_account_tal_path_input": "{t}_tal.xlsx",
    "complex_account_specs_path_input": "{t}_specs.xlsx",
    "box_tracker_mirror_path_input": "{t}_mirror.xlsx",
    "convertr_account_username": "{t}-user",
    "convertr_account_password": "{t}-pass",
    "convertr_lf_email": "{t} Email",
    "convertr_lf_cid": "{t} CID",
    "enhancio_lf_email": "{t} Email",
    "enhancio_lf_first": "{t} First",
    "enhancio_lf_cid": "{t} CID",
    "integrate_lf_company": "{t} Co",
    "integrate_sid_input": "{t}-sid",
    "integrate_callback_url_input": "https://{t}.example",
}
_PER_CLIENT_AREA_KEYS = {
    "box_tracker_cid_map_input": "{t}1,{t} Camp",
    "box_tracker_lead_template_map_input": "{t}1,{t}_tmpl.xlsx",
    "box_tracker_pacing_skipped_input": "{t} Skip",
    "convertr_campaigns_input": "{t}1,{t}C",
    "convertr_field_map_cols_input": "{t} Col",
    "convertr_field_map_targets_input": "{t} Target",
    "enhancio_allocations_input": "{t}1,{t}uid",
    "enhancio_field_map_cols_input": "{t} ECol",
    "enhancio_field_map_targets_input": "{t} ETarget",
    "enhancio_fixed_values_input": "{t}uid,Lead Source,{t} Src",
    "integrate_field_map_cols_input": "{t} ICol",
    "integrate_fixed_values_input": "country,{t}land",
}


def _assert_shows(at, tag):
    for key, expected in _PER_CLIENT_TEXT_KEYS.items():
        assert at.text_input(key=key).value == expected.format(t=tag), key
    for key, expected in _PER_CLIENT_AREA_KEYS.items():
        assert at.text_area(key=key).value == expected.format(t=tag), key


def test_switching_edited_client_shows_new_clients_delivery_config_and_save_keeps_it(tmp_path, monkeypatch):
    # Regression: keyed widgets with a per-profile value= kept client A's
    # value after switching to client B (Streamlit ignores value= once the
    # key exists), so clicking Save wrote A's Enhancio/Convertr/Integrate
    # config into B.
    monkeypatch.chdir(tmp_path)
    _save_two_delivery_profiles()

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at.selectbox if s.label == "Client").set_value("Switch A").run()
    _assert_shows(at, "A")

    next(s for s in at.selectbox if s.label == "Client").set_value("Switch B").run()
    assert not at.exception
    _assert_shows(at, "B")

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir, get_convertr_account_credentials
    from core.profile_store import load_profile

    saved = load_profile("Switch B", get_clients_dir())
    assert [(a.cid, a.allocation_uid) for a in saved.enhancio.allocations] == [("B1", "Buid")]
    assert saved.enhancio.field_mapping == {"B ECol": "B ETarget"}
    assert saved.enhancio.fixed_field_values == {"Buid": {"Lead Source": "B Src"}}
    assert saved.enhancio.leadfile_field_mapping.email == "B Email"
    assert [(c.cid, c.campaign_id) for c in saved.convertr.campaigns] == [("B1", "BC")]
    assert saved.convertr.field_mapping == {"B Col": "B Target"}
    assert saved.convertr.leadfile_field_mapping.cid == "B CID"
    assert saved.integrate.sid == "B-sid"
    assert saved.integrate.callback_url == "https://B.example"
    assert saved.integrate.field_mapping == {"B ICol": "email"}
    assert saved.integrate.fixed_field_values == {"country": "Bland"}
    assert saved.box_tracker.cid_campaign_map == {"B1": "B Camp"}
    assert saved.box_tracker.mirror_workbook_path == "B_mirror.xlsx"
    assert saved.complex_account.tal_path == "B_tal.xlsx"
    assert get_convertr_account_credentials("Switch B") == {"username": "B-user", "password": "B-pass"}


def test_switching_from_edited_client_to_create_new_shows_blank_delivery_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save_two_delivery_profiles()

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at.selectbox if s.label == "Client").set_value("Switch A").run()
    _assert_shows(at, "A")
    assert at.checkbox(key="integrate_enabled").value is True

    next(r for r in at.radio if r.label == "Mode").set_value("Create new client").run()
    assert not at.exception
    assert at.checkbox(key="integrate_enabled").value is False
    for label in ("This client uploads to Convertr", "This client uploads to Enhancio",
                  "This client uses a Box Tracker"):
        next(c for c in at.checkbox if c.label == label).set_value(True).run()
    at.checkbox(key="integrate_enabled").set_value(True).run()
    for key in list(_PER_CLIENT_TEXT_KEYS) + list(_PER_CLIENT_AREA_KEYS):
        if key.startswith("complex_account_"):
            continue
        widget = at.text_area(key=key) if key in _PER_CLIENT_AREA_KEYS else at.text_input(key=key)
        assert widget.value == "", key


# --- Custom Questions --------------------------------------------------------

_CQ_HEADER = "1. Which widget features matter most to you?"


def _start_new_client(at, tmp_path, name: str) -> None:
    next(t for t in at.text_input if t.label == "Client name").set_value(name).run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "accumulated.xlsx")).run()


def test_custom_questions_rule_configured_in_client_setup_persists_on_save(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    _start_new_client(at, tmp_path, "CQ Save Client")

    at.checkbox(key="cq_enabled").set_value(True).run()
    at.button(key="cq_rules_add").click().run()
    assert not at.exception
    next(t for t in at.text_input if t.label == "Question column header").set_value(_CQ_HEADER).run()
    next(t for t in at.text_area if t.label == "Allowed answers (one per line)").set_value(
        "a) Speed, reliability & uptime\nb) Security / compliance").run()
    next(s for s in at.selectbox if s.label == "Count rule").set_value("at_most").run()
    next(n for n in at.number_input if n.label == "Count").set_value(2).run()
    next(t for t in at.text_input if t.label == "Separator").set_value(";").run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.models import CustomQuestionRule
    from core.profile_store import load_profile

    saved = load_profile("CQ Save Client", get_clients_dir())
    assert saved.custom_questions.enabled is True
    assert saved.custom_questions.rules == [CustomQuestionRule(
        format="header", column=_CQ_HEADER, question_text=_CQ_HEADER, mode="full",
        allowed_answers=["a) Speed, reliability & uptime", "b) Security / compliance"],
        count_rule="at_most", count=2, separator=";",
    )]


def test_custom_questions_detect_from_leadfile_prefills_rules(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sample = str(tmp_path / "sample_leads.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Email", _CQ_HEADER, "Company"])
    ws.append(["x@example.com", "a) Speed, reliability & uptime, b) Security / compliance", "Acme"])
    ws.append(["y@example.com", "c) Price", "Beta"])
    wb.save(sample)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    _start_new_client(at, tmp_path, "CQ Detect Client")
    at.checkbox(key="cq_enabled").set_value(True).run()
    at.text_input(key="cq_sample_path").set_value(sample).run()
    at.button(key="cq_detect").click().run()
    assert not at.exception
    assert next(t for t in at.text_input if t.label == "Question column header").value == _CQ_HEADER

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    rule = load_profile("CQ Detect Client", get_clients_dir()).custom_questions.rules[0]
    assert rule.column == _CQ_HEADER
    assert rule.allowed_answers == [
        "a) Speed, reliability & uptime", "b) Security / compliance", "c) Price"]
    assert (rule.count_rule, rule.count) == ("at_most", 2)


def test_switching_client_resets_custom_questions_widgets(tmp_path, monkeypatch):
    # Same data-corruption class as the delivery-config switch test above:
    # a keyed widget keeps the previous client's value after a profile
    # switch unless the reset block clears it, and Save then writes it into
    # the newly selected client.
    monkeypatch.chdir(tmp_path)
    from core.app_settings import get_clients_dir
    from core.models import ClientProfile, CustomQuestionRule, CustomQuestionsConfig
    from core.profile_store import load_profile, save_profile

    save_profile(ClientProfile(
        name="CQ A", accumulated_report_path="A_acc.xlsx",
        custom_questions=CustomQuestionsConfig(enabled=True, rules=[
            CustomQuestionRule(column="A question?", question_text="A question?", allowed_answers=["Yes"]),
        ]),
    ), get_clients_dir())
    save_profile(ClientProfile(name="CQ B", accumulated_report_path="B_acc.xlsx"), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at.selectbox if s.label == "Client").set_value("CQ A").run()
    assert at.checkbox(key="cq_enabled").value is True
    assert [t.value for t in at.text_input if t.label == "Question column header"] == ["A question?"]

    next(s for s in at.selectbox if s.label == "Client").set_value("CQ B").run()
    assert not at.exception
    assert at.checkbox(key="cq_enabled").value is False
    at.checkbox(key="cq_enabled").set_value(True).run()
    assert [t for t in at.text_input if t.label == "Question column header"] == []

    at.checkbox(key="cq_enabled").set_value(False).run()
    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception
    saved_b = load_profile("CQ B", get_clients_dir())
    assert saved_b.custom_questions.enabled is False
    assert saved_b.custom_questions.rules == []

    next(r for r in at.radio if r.label == "Mode").set_value("Create new client").run()
    assert at.checkbox(key="cq_enabled").value is False


def test_custom_questions_combined_cell_settings_persist_on_save(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    _start_new_client(at, tmp_path, "CQ Combined Client")

    at.checkbox(key="cq_enabled").set_value(True).run()
    at.text_input(key="cq_combined_cell_column").set_value("Custom").run()
    at.checkbox(key="cq_require_consent").set_value(True).run()
    at.text_area(key="cq_consent_keys").set_value(
        "I agree to receive updates from Acme\n\nI accept the privacy policy\n").run()
    assert not at.exception

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    saved = load_profile("CQ Combined Client", get_clients_dir()).custom_questions
    assert saved.enabled is True and saved.rules == []
    assert saved.combined_cell_column == "Custom"
    assert saved.require_consent_true is True
    assert saved.consent_keys == ["I agree to receive updates from Acme", "I accept the privacy policy"]


def test_switching_client_resets_custom_questions_combined_cell_widgets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import get_clients_dir
    from core.models import ClientProfile, CustomQuestionsConfig
    from core.profile_store import load_profile, save_profile

    save_profile(ClientProfile(
        name="CC A", accumulated_report_path="A_acc.xlsx",
        custom_questions=CustomQuestionsConfig(enabled=True, combined_cell_column="Custom",
                                               require_consent_true=True, consent_keys=["I agree"]),
    ), get_clients_dir())
    save_profile(ClientProfile(name="CC B", accumulated_report_path="B_acc.xlsx",
                               custom_questions=CustomQuestionsConfig(enabled=True)), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at.selectbox if s.label == "Client").set_value("CC A").run()
    assert at.text_input(key="cq_combined_cell_column").value == "Custom"
    assert at.checkbox(key="cq_require_consent").value is True

    next(s for s in at.selectbox if s.label == "Client").set_value("CC B").run()
    assert not at.exception
    assert at.text_input(key="cq_combined_cell_column").value == ""
    assert at.checkbox(key="cq_require_consent").value is False

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception
    saved_b = load_profile("CC B", get_clients_dir()).custom_questions
    assert (saved_b.combined_cell_column, saved_b.require_consent_true, saved_b.consent_keys) == ("", False, [])


# --- Lead Notes --------------------------------------------------------------

def _ln_row_widgets(at, label: str):
    return [w for w in at.selectbox if w.label == label]


def test_lead_notes_config_persists_on_save(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    _start_new_client(at, tmp_path, "Notes Save Client")

    at.checkbox(key="ln_enabled").set_value(True).run()
    at.text_input(key="ln_notes_column").set_value("Signal Notes").run()
    at.button(key="ln_fields_add").click().run()
    at.button(key="ln_fields_add").click().run()
    assert not at.exception

    kinds = _ln_row_widgets(at, "Field")
    assert len(kinds) == 2
    kinds[1].set_value("value").run()
    columns = [t for t in at.text_input if t.label == "Lead column"]
    columns[0].set_value("Email").run()
    columns[1].set_value("Budget").run()
    next(t for t in at.text_input if t.label == "Name in reasons").set_value("Budget range").run()
    [c for c in at.checkbox if c.label == "Required"][0].set_value(True).run()
    _ln_row_widgets(at, "If it doesn't match")[0].set_value("refund").run()
    assert not at.exception

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.models import LeadNotesConfig, LeadNotesField
    from core.profile_store import load_profile

    saved = load_profile("Notes Save Client", get_clients_dir())
    assert saved.lead_notes == LeadNotesConfig(enabled=True, notes_column="Signal Notes", fields=[
        LeadNotesField(kind="email", column="Email", required=True, action="refund"),
        LeadNotesField(kind="value", column="Budget", label="Budget range", required=False, action="review"),
    ])


def test_lead_notes_save_is_blocked_without_a_notes_column(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    _start_new_client(at, tmp_path, "Notes Blocked Client")
    at.checkbox(key="ln_enabled").set_value(True).run()
    at.button(key="ln_fields_add").click().run()
    next(t for t in at.text_input if t.label == "Lead column").set_value("Email").run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception
    assert any("Lead Notes" in e.value for e in at.error)
    assert not (tmp_path / "clients" / "Notes Blocked Client.json").exists()


def test_switching_client_resets_lead_notes_widgets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import get_clients_dir
    from core.models import ClientProfile, LeadNotesConfig, LeadNotesField
    from core.profile_store import load_profile, save_profile

    save_profile(ClientProfile(
        name="LN A", accumulated_report_path="A_acc.xlsx",
        lead_notes=LeadNotesConfig(enabled=True, notes_column="Signal Notes", fields=[
            LeadNotesField(kind="phone", column="Phone", required=True, action="refund")]),
    ), get_clients_dir())
    save_profile(ClientProfile(name="LN B", accumulated_report_path="B_acc.xlsx"), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at.selectbox if s.label == "Client").set_value("LN A").run()
    assert at.checkbox(key="ln_enabled").value is True
    assert at.text_input(key="ln_notes_column").value == "Signal Notes"
    assert [t.value for t in at.text_input if t.label == "Lead column"] == ["Phone"]

    next(s for s in at.selectbox if s.label == "Client").set_value("LN B").run()
    assert not at.exception
    assert at.checkbox(key="ln_enabled").value is False
    at.checkbox(key="ln_enabled").set_value(True).run()
    assert at.text_input(key="ln_notes_column").value == ""
    assert [t for t in at.text_input if t.label == "Lead column"] == []

    at.checkbox(key="ln_enabled").set_value(False).run()
    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception
    saved_b = load_profile("LN B", get_clients_dir())
    assert saved_b.lead_notes == LeadNotesConfig()

    next(r for r in at.radio if r.label == "Mode").set_value("Create new client").run()
    assert at.checkbox(key="ln_enabled").value is False


def test_lead_notes_add_standard_fields_prefills_from_the_field_mapping(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import get_clients_dir
    from core.models import ClientProfile, FieldMapping
    from core.profile_store import save_profile

    save_profile(ClientProfile(
        name="LN Std", accumulated_report_path="acc.xlsx",
        field_mapping=FieldMapping(email="Work Email", first_name="First", last_name="Last",
                                   company="Company Name", cid="CID"),
    ), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at.selectbox if s.label == "Client").set_value("LN Std").run()
    at.checkbox(key="ln_enabled").set_value(True).run()
    at.button(key="ln_fields_add_standard").click().run()
    assert not at.exception

    assert [s.value for s in at.selectbox if s.label == "Field"] == [
        "email", "phone", "first_name", "last_name", "company", "job_title"]
    assert [t.value for t in at.text_input if t.label == "Lead column"] == [
        "Work Email", "", "First", "Last", "Company Name", ""]

    at.button(key="ln_fields_add_standard").click().run()
    assert len([s for s in at.selectbox if s.label == "Field"]) == 6


def test_saving_a_group_change_keeps_the_same_client_and_its_checks_selected(tmp_path, monkeypatch):
    # Regression test: after saving a new group for the selected client, the
    # next rerun saw it was no longer in the Group filter's old group and
    # swapped to that group's first client - whose checks were off, so it
    # looked like the just-enabled check had been reset.
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    for name, group in [("A1", "G1"), ("A2", "G1"), ("B1", "G2")]:
        save_profile(ClientProfile(name=name, accumulated_report_path="a.xlsx", client_group=group),
                     get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=30)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at.selectbox if s.label == "Group").set_value("G1").run()
    next(s for s in at.selectbox if s.label == "Client").set_value("A2").run()
    at.checkbox(key="cq_enabled").check().run()
    at.selectbox(key="client_group_select").set_value("G2").run()
    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    at.run()

    assert not at.exception
    assert next(s for s in at.selectbox if s.label == "Group").value == "G2"
    assert next(s for s in at.selectbox if s.label == "Client").value == "A2"
    assert at.checkbox(key="cq_enabled").value is True
