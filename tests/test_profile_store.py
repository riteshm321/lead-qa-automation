import json
import os

from core.models import (
    ClientProfile, FieldMapping, LeadcapConfig, LeadcapSegment,
    TalConfig, ExclusionConfig, ReferenceSource, SuppressionConfig, DedupeListConfig, LeadTemplateTab,
    ComplexAccountConfig, BoxTrackerConfig, ConvertrConfig, ConvertrCampaignMapping,
    EnhancioConfig, EnhancioAllocationMapping,
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


def test_list_profile_names_ignores_non_utf8_json_in_same_folder(tmp_path):
    # A stray .json file that isn't even valid UTF-8 (e.g. a corrupted
    # OneDrive conflict copy) must be skipped like any other non-profile
    # file, not crash the whole listing with an unhandled UnicodeDecodeError.
    clients_dir = str(tmp_path / "clients")
    save_profile(_sample_profile(), clients_dir=clients_dir)
    with open(os.path.join(clients_dir, "corrupted.json"), "wb") as f:
        f.write(b"\xff\xfe\x00\x01not valid utf-8 \xbf")

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


def test_convertr_config_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()
    profile.convertr = ConvertrConfig(
        enabled=True, enterprise="amazonbusiness", publisher_id="11003",
        campaigns=[
            ConvertrCampaignMapping(cid="118741", campaign_id="44400", global_form_id="75"),
            ConvertrCampaignMapping(cid="118742", campaign_id="44401", global_form_id="76",
                                     campaign_link_id="135"),
        ],
        field_mapping={"Email": "email", "First Name": "firstName"},
    )

    save_profile(profile, clients_dir=clients_dir)
    loaded = load_profile("Basware", clients_dir=clients_dir)
    assert loaded == profile


def test_convertr_leadfile_field_mapping_round_trips_independently_of_qa_field_mapping(tmp_path):
    # Amazon-style client: no QA field_mapping at all, but Convertr still
    # needs to know which of the UPLOADED leadfile's own columns are
    # email/CID/etc -- this is what lets Convertr work without ever routing
    # through Run Check first.
    clients_dir = str(tmp_path / "clients")
    profile = ClientProfile(
        name="Amazon Business EMEA", accumulated_report_path="sample_data/x.xlsx",
        convertr=ConvertrConfig(
            enabled=True, enterprise="amazonbusiness", publisher_id="11003",
            leadfile_field_mapping=FieldMapping(
                email="Email", first_name="First Name", last_name="Last Name", company="Company", cid="CID"),
        ),
    )

    save_profile(profile, clients_dir=clients_dir)
    loaded = load_profile("Amazon Business EMEA", clients_dir=clients_dir)

    assert loaded.field_mapping is None
    assert loaded.convertr.leadfile_field_mapping == profile.convertr.leadfile_field_mapping


def test_enhancio_config_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()
    profile.enhancio = EnhancioConfig(
        enabled=True,
        allocations=[
            EnhancioAllocationMapping(cid="118741", allocation_uid="L-22256"),
            EnhancioAllocationMapping(cid="118742", allocation_uid="L-22257"),
        ],
        field_mapping={"Email": "Email Address", "First Name": "First Name"},
        leadfile_field_mapping=FieldMapping(
            email="Email", first_name="First Name", last_name="Last Name", company="Company", cid="CID"),
    )

    save_profile(profile, clients_dir=clients_dir)
    loaded = load_profile("Basware", clients_dir=clients_dir)
    assert loaded == profile


def test_load_profile_defaults_enhancio_disabled_for_old_schema_json(tmp_path):
    clients_dir = str(tmp_path / "clients")
    os.makedirs(clients_dir, exist_ok=True)
    with open(os.path.join(clients_dir, "OldClient.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": "OldClient",
            "accumulated_report_path": "sample_data/x.xlsx",
        }, f)

    loaded = load_profile("OldClient", clients_dir=clients_dir)
    assert loaded.enhancio.enabled is False
    assert loaded.enhancio.allocations == []


def test_load_profile_defaults_convertr_disabled_for_old_schema_json(tmp_path):
    clients_dir = str(tmp_path / "clients")
    os.makedirs(clients_dir, exist_ok=True)
    with open(os.path.join(clients_dir, "OldClient.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": "OldClient",
            "accumulated_report_path": "sample_data/x.xlsx",
        }, f)

    loaded = load_profile("OldClient", clients_dir=clients_dir)
    assert loaded.convertr.enabled is False
    assert loaded.convertr.campaigns == []


def test_load_profile_drops_legacy_per_campaign_publisher_id(tmp_path):
    # publisher_id used to live on each campaign mapping before it moved
    # up to ConvertrConfig as one fixed account-level value -- a profile
    # saved by the old schema still has it there and must still load.
    clients_dir = str(tmp_path / "clients")
    os.makedirs(clients_dir, exist_ok=True)
    with open(os.path.join(clients_dir, "OldConvertrClient.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": "OldConvertrClient",
            "accumulated_report_path": "sample_data/x.xlsx",
            "convertr": {
                "enabled": True,
                "enterprise": "amazonbusiness",
                "campaigns": [
                    {"cid": "120022", "campaign_id": "44709", "global_form_id": "75",
                     "campaign_link_id": "", "publisher_id": "11003"},
                ],
                "field_mapping": {},
            },
        }, f)

    loaded = load_profile("OldConvertrClient", clients_dir=clients_dir)
    assert loaded.convertr.campaigns[0].cid == "120022"
    assert loaded.convertr.publisher_id == ""


def test_collation_enabled_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()
    profile.collation_enabled = True

    save_profile(profile, clients_dir=clients_dir)
    loaded = load_profile("Basware", clients_dir=clients_dir)
    assert loaded == profile


def test_load_profile_defaults_collation_enabled_false_for_old_schema_json(tmp_path):
    clients_dir = str(tmp_path / "clients")
    os.makedirs(clients_dir, exist_ok=True)
    with open(os.path.join(clients_dir, "OldClient.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": "OldClient",
            "accumulated_report_path": "sample_data/x.xlsx",
        }, f)

    loaded = load_profile("OldClient", clients_dir=clients_dir)
    assert loaded.collation_enabled is False


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


def test_box_tracker_config_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()
    profile.box_tracker = BoxTrackerConfig(
        enabled=True, mirror_workbook_path="sample_data/box_mirror.xlsx",
        cid_campaign_map={"118741": "Bob", "118742": "CXO"},
    )

    save_profile(profile, clients_dir=clients_dir)
    loaded = load_profile("Basware", clients_dir=clients_dir)

    assert loaded.box_tracker.enabled is True
    assert loaded.box_tracker.mirror_workbook_path == "sample_data/box_mirror.xlsx"
    assert loaded.box_tracker.cid_campaign_map == {"118741": "Bob", "118742": "CXO"}


def test_load_profile_defaults_box_tracker_for_old_schema_json(tmp_path):
    clients_dir = str(tmp_path / "clients")
    os.makedirs(clients_dir, exist_ok=True)
    with open(os.path.join(clients_dir, "OldClient7.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "OldClient7", "accumulated_report_path": "sample_data/x.xlsx"}, f)

    loaded = load_profile("OldClient7", clients_dir=clients_dir)
    assert loaded.box_tracker.enabled is False
    assert loaded.box_tracker.cid_campaign_map == {}


def test_box_tracker_lead_template_map_and_pacing_skip_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()
    profile.box_tracker = BoxTrackerConfig(
        enabled=True,
        cid_lead_template_path={"118741": "sample_data/bob_template.xlsx"},
        pacing_skipped_campaigns=["CXO"],
    )

    save_profile(profile, clients_dir=clients_dir)
    loaded = load_profile("Basware", clients_dir=clients_dir)

    assert loaded.box_tracker.cid_lead_template_path == {"118741": "sample_data/bob_template.xlsx"}
    assert loaded.box_tracker.pacing_skipped_campaigns == ["CXO"]


def test_load_profile_defaults_lead_template_map_and_pacing_skip_for_old_schema_json(tmp_path):
    clients_dir = str(tmp_path / "clients")
    os.makedirs(clients_dir, exist_ok=True)
    with open(os.path.join(clients_dir, "OldClient8.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "OldClient8", "accumulated_report_path": "sample_data/x.xlsx"}, f)

    loaded = load_profile("OldClient8", clients_dir=clients_dir)
    assert loaded.box_tracker.cid_lead_template_path == {}
    assert loaded.box_tracker.pacing_skipped_campaigns == []
