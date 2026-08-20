import json
import os

from core.models import (
    ClientProfile, FieldMapping, LeadcapConfig, LeadcapSegment,
    TalConfig, ExclusionConfig, ReferenceSource, SuppressionConfig, DedupeListConfig, LeadTemplateTab,
    ComplexAccountConfig,
)
from core.profile_store import save_profile, load_profile, list_profile_names


def _sample_profile() -> ClientProfile:
    return ClientProfile(
        name="Basware",
        accumulated_report_path="sample_data/Basware APAC – Accumulated Report.xlsx",
        field_mapping=FieldMapping(email="emailaddress", first_name="firstname",
                                    last_name="lastname", company="company", cid="CID"),
        leadcap=LeadcapConfig(enabled=True, segmented=True, check_company_name=True, segments=[
            LeadcapSegment(name="AU Geo", cids=["114578"], cap=8),
            LeadcapSegment(name="IN Geo", cids=["114568"], cap=5),
        ]),
        tal=TalConfig(enabled=True, sources=[
            ReferenceSource(name="Global TAL", file_path="sample_data/tal.xlsx", sheet_name="Sheet1"),
        ]),
        exclusion=ExclusionConfig(enabled=True, sources=[
            ReferenceSource(name="Global Exclusion", file_path="sample_data/Basware -Exclusion List.xlsx",
                             sheet_name="Exclusion"),
            ReferenceSource(name="EMEA Exclusion", file_path="sample_data/emea_exclusion.xlsx",
                             sheet_name="Sheet1", cids=["114578", "114579"],
                             domain_column="Website", company_column="Company"),
        ]),
        suppression=SuppressionConfig(enabled=True, check_domain=True, sources=[
            ReferenceSource(name="Global Suppression", file_path="sample_data/suppression.xlsx", sheet_name="Sheet1"),
        ]),
        dedupe_list=DedupeListConfig(enabled=True, sources=[
            ReferenceSource(name="Global Dedupe", file_path="sample_data/dedupe.xlsx", sheet_name="Sheet1"),
        ]),
    )


def test_save_and_load_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()

    saved_path = save_profile(profile, clients_dir=clients_dir)
    assert saved_path.endswith("Basware.json")

    loaded = load_profile("Basware", clients_dir=clients_dir)
    assert loaded == profile


def test_list_profile_names(tmp_path):
    clients_dir = str(tmp_path / "clients")
    save_profile(_sample_profile(), clients_dir=clients_dir)
    assert list_profile_names(clients_dir=clients_dir) == ["Basware"]


def test_list_profile_names_ignores_non_profile_json_in_same_folder(tmp_path):
    # Regression test: a shared clients_dir (per the "Client storage
    # location" setting) can end up with non-profile .json files sitting
    # right next to real profiles — this reproduces the exact crash where
    # company_aliases.json (a plain list) landed in the clients folder and
    # list_profile_names/load_profile treated it as a client.
    clients_dir = str(tmp_path / "clients")
    save_profile(_sample_profile(), clients_dir=clients_dir)
    with open(os.path.join(clients_dir, "company_aliases.json"), "w", encoding="utf-8") as f:
        json.dump([["acme", "acme corp"]], f)
    with open(os.path.join(clients_dir, "not_a_profile_either.json"), "w", encoding="utf-8") as f:
        json.dump({"some": "unrelated dict"}, f)

    assert list_profile_names(clients_dir=clients_dir) == ["Basware"]


def test_client_mode_and_lead_template_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()
    profile.client_mode = "Lead QA"
    profile.lead_template_path = "sample_data/template.xlsx"
    profile.lead_template_sheet_name = "Sheet1"

    save_profile(profile, clients_dir=clients_dir)
    loaded = load_profile("Basware", clients_dir=clients_dir)
    assert loaded == profile


def test_load_profile_defaults_client_mode_for_old_schema_json(tmp_path):
    clients_dir = str(tmp_path / "clients")
    os.makedirs(clients_dir, exist_ok=True)
    with open(os.path.join(clients_dir, "OldClient.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": "OldClient",
            "accumulated_report_path": "sample_data/x.xlsx",
        }, f)

    loaded = load_profile("OldClient", clients_dir=clients_dir)
    assert loaded.client_mode == "Lead QA"
    assert loaded.lead_template_path == ""
    assert loaded.lead_template_sheet_name == ""
    assert loaded.accumulated_field_mapping is None
    assert loaded.lead_template_field_mapping is None


def test_accumulated_and_lead_template_field_mapping_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()
    profile.accumulated_field_mapping = FieldMapping(
        email="Email Add.", first_name="Given Name", last_name="Surname", company="Org", cid="Campaign ID")
    profile.lead_template_field_mapping = FieldMapping(
        email="emailaddress", first_name="firstname", last_name="lastname", company="company", cid="CID")

    save_profile(profile, clients_dir=clients_dir)
    loaded = load_profile("Basware", clients_dir=clients_dir)
    assert loaded == profile


def test_lead_template_multi_tab_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()
    profile.lead_template_path = "sample_data/template.xlsx"
    profile.lead_template_multi_tab = True
    profile.lead_template_tabs = [
        LeadTemplateTab(sheet_name="APAC", cids=["119336", "119337"]),
        LeadTemplateTab(sheet_name="EMEA", cids=["119338"]),
    ]

    save_profile(profile, clients_dir=clients_dir)
    loaded = load_profile("Basware", clients_dir=clients_dir)
    assert loaded == profile


def test_load_profile_defaults_lead_template_tabs_for_old_schema_json(tmp_path):
    clients_dir = str(tmp_path / "clients")
    os.makedirs(clients_dir, exist_ok=True)
    with open(os.path.join(clients_dir, "OldClient2.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": "OldClient2",
            "accumulated_report_path": "sample_data/x.xlsx",
        }, f)

    loaded = load_profile("OldClient2", clients_dir=clients_dir)
    assert loaded.lead_template_multi_tab is False
    assert loaded.lead_template_tabs == []


def test_jira_ticket_key_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()
    profile.jira_ticket_key = "PROJ-1234"

    save_profile(profile, clients_dir=clients_dir)
    loaded = load_profile("Basware", clients_dir=clients_dir)
    assert loaded.jira_ticket_key == "PROJ-1234"


def test_load_profile_defaults_jira_ticket_key_for_old_schema_json(tmp_path):
    clients_dir = str(tmp_path / "clients")
    os.makedirs(clients_dir, exist_ok=True)
    with open(os.path.join(clients_dir, "OldClient3.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": "OldClient3",
            "accumulated_report_path": "sample_data/x.xlsx",
        }, f)

    loaded = load_profile("OldClient3", clients_dir=clients_dir)
    assert loaded.jira_ticket_key == ""


def test_lead_template_tab_file_path_and_clear_existing_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()
    profile.lead_template_path = "sample_data/shared_template.xlsx"
    profile.lead_template_multi_tab = True
    profile.lead_template_tabs = [
        LeadTemplateTab(sheet_name="APAC", cids=["119336"]),  # blank file_path -> shared path
        LeadTemplateTab(sheet_name="EMEA", cids=["119338"], file_path="sample_data/emea_only.xlsx"),
    ]
    profile.lead_template_clear_existing = True

    save_profile(profile, clients_dir=clients_dir)
    loaded = load_profile("Basware", clients_dir=clients_dir)

    assert loaded.lead_template_clear_existing is True
    assert loaded.lead_template_tabs[0].file_path == ""
    assert loaded.lead_template_tabs[1].file_path == "sample_data/emea_only.xlsx"


def test_sharepoint_links_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()
    profile.accumulated_report_link = "https://madlog.sharepoint.com/:x:/s/Team/AccumulatedLink"
    profile.lead_template_path = "sample_data/shared_template.xlsx"
    profile.lead_template_link = "https://madlog.sharepoint.com/:x:/s/Team/SharedTemplateLink"
    profile.lead_template_multi_tab = True
    profile.lead_template_tabs = [
        LeadTemplateTab(sheet_name="APAC", cids=["119336"]),  # blank link -> shared link
        LeadTemplateTab(sheet_name="EMEA", cids=["119338"], file_path="sample_data/emea_only.xlsx",
                         link="https://madlog.sharepoint.com/:x:/s/Team/EmeaLink"),
    ]

    save_profile(profile, clients_dir=clients_dir)
    loaded = load_profile("Basware", clients_dir=clients_dir)

    assert loaded.accumulated_report_link == "https://madlog.sharepoint.com/:x:/s/Team/AccumulatedLink"
    assert loaded.lead_template_link == "https://madlog.sharepoint.com/:x:/s/Team/SharedTemplateLink"
    assert loaded.lead_template_tabs[0].link == ""
    assert loaded.lead_template_tabs[1].link == "https://madlog.sharepoint.com/:x:/s/Team/EmeaLink"


def test_load_profile_defaults_sharepoint_links_for_old_schema_json(tmp_path):
    clients_dir = str(tmp_path / "clients")
    os.makedirs(clients_dir, exist_ok=True)
    with open(os.path.join(clients_dir, "OldClient5.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": "OldClient5",
            "accumulated_report_path": "sample_data/x.xlsx",
            "lead_template_tabs": [{"sheet_name": "APAC", "cids": ["1"]}],  # no "link" key at all
        }, f)

    loaded = load_profile("OldClient5", clients_dir=clients_dir)
    assert loaded.accumulated_report_link == ""
    assert loaded.lead_template_link == ""
    assert loaded.lead_template_tabs[0].link == ""


def test_load_profile_defaults_tab_file_path_and_clear_existing_for_old_schema_json(tmp_path):
    clients_dir = str(tmp_path / "clients")
    os.makedirs(clients_dir, exist_ok=True)
    with open(os.path.join(clients_dir, "OldClient4.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": "OldClient4",
            "accumulated_report_path": "sample_data/x.xlsx",
            "lead_template_tabs": [{"sheet_name": "APAC", "cids": ["1"]}],  # no file_path key at all
        }, f)

    loaded = load_profile("OldClient4", clients_dir=clients_dir)
    assert loaded.lead_template_clear_existing is False
    assert loaded.lead_template_tabs[0].file_path == ""


def test_complex_account_config_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()
    profile.complex_account = ComplexAccountConfig(
        enabled=True, tal_path="sample_data/TAL.csv",
        specifications_path="sample_data/Specifications Campaigns - BANT NTQ & EHS.xlsx",
    )

    save_profile(profile, clients_dir=clients_dir)
    loaded = load_profile("Basware", clients_dir=clients_dir)

    assert loaded.complex_account.enabled is True
    assert loaded.complex_account.tal_path == "sample_data/TAL.csv"
    assert loaded.complex_account.specifications_path == \
        "sample_data/Specifications Campaigns - BANT NTQ & EHS.xlsx"


def test_load_profile_defaults_complex_account_for_old_schema_json(tmp_path):
    clients_dir = str(tmp_path / "clients")
    os.makedirs(clients_dir, exist_ok=True)
    with open(os.path.join(clients_dir, "OldClient6.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "OldClient6", "accumulated_report_path": "sample_data/x.xlsx"}, f)

    loaded = load_profile("OldClient6", clients_dir=clients_dir)
    assert loaded.complex_account.enabled is False
    assert loaded.complex_account.tal_path == ""
