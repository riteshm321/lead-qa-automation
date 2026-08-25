import os
from unittest.mock import patch

import openpyxl
from streamlit.testing.v1 import AppTest

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
    # under clients_dir with no sanitizing — a "/" silently created a
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

    add_button = next(b for b in at.button if b.label == "➕ Add Exclusion Source")
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
