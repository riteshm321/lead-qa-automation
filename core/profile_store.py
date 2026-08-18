import dataclasses
import json
import os

from core.atomic_io import atomic_write_json
from core.models import (
    ClientProfile, FieldMapping, LeadcapConfig, LeadcapSegment,
    TalConfig, ExclusionConfig, SuppressionConfig,
    DuplicateConfig, DedupeListConfig, ReferenceSource, LeadTemplateTab,
)


def _profile_path(name: str, clients_dir: str) -> str:
    return os.path.join(clients_dir, f"{name}.json")


def save_profile(profile: ClientProfile, clients_dir: str = "clients") -> str:
    path = _profile_path(profile.name, clients_dir)
    atomic_write_json(path, dataclasses.asdict(profile))
    return path


def load_profile(name: str, clients_dir: str = "clients") -> ClientProfile:
    path = _profile_path(name, clients_dir)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    fm = data.get("field_mapping")
    field_mapping = FieldMapping(**fm) if fm else None

    acc_fm = data.get("accumulated_field_mapping")
    accumulated_field_mapping = FieldMapping(**acc_fm) if acc_fm else None

    tmpl_fm = data.get("lead_template_field_mapping")
    lead_template_field_mapping = FieldMapping(**tmpl_fm) if tmpl_fm else None

    leadcap = data.get("leadcap") or {}
    leadcap["segments"] = [LeadcapSegment(**s) for s in leadcap.get("segments", [])]

    exclusion = data.get("exclusion") or {}
    exclusion["sources"] = [ReferenceSource(**s) for s in exclusion.get("sources", [])]

    tal = data.get("tal") or {}
    tal["sources"] = [ReferenceSource(**s) for s in tal.get("sources", [])]

    suppression = data.get("suppression") or {}
    suppression["sources"] = [ReferenceSource(**s) for s in suppression.get("sources", [])]

    dedupe_list = data.get("dedupe_list") or {}
    dedupe_list["sources"] = [ReferenceSource(**s) for s in dedupe_list.get("sources", [])]

    lead_template_tabs = [LeadTemplateTab(**t) for t in data.get("lead_template_tabs", [])]

    return ClientProfile(
        name=data["name"],
        accumulated_report_path=data["accumulated_report_path"],
        accumulated_tab_name=data.get("accumulated_tab_name", "Accumulated"),
        refund_tab_name=data.get("refund_tab_name", "Refund"),
        jira_ticket_key=data.get("jira_ticket_key", ""),
        jira_reporter_name=data.get("jira_reporter_name", ""),
        client_mode=data.get("client_mode", "Lead QA"),
        lead_template_path=data.get("lead_template_path", ""),
        lead_template_sheet_name=data.get("lead_template_sheet_name", ""),
        lead_template_multi_tab=data.get("lead_template_multi_tab", False),
        lead_template_tabs=lead_template_tabs,
        field_mapping=field_mapping,
        accumulated_field_mapping=accumulated_field_mapping,
        lead_template_field_mapping=lead_template_field_mapping,
        duplicate=DuplicateConfig(**(data.get("duplicate") or {})),
        leadcap=LeadcapConfig(**leadcap),
        exclusion=ExclusionConfig(**exclusion),
        tal=TalConfig(**tal),
        suppression=SuppressionConfig(**suppression),
        dedupe_list=DedupeListConfig(**dedupe_list),
    )


def _looks_like_profile(path: str) -> bool:
    # A shared clients_dir can accumulate .json files that aren't client
    # profiles at all — e.g. OneDrive conflict copies, or (before aliases
    # moved to their own subfolder) the aliases file itself. Requiring the
    # shape of an actual profile avoids treating those as fake clients.
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and "accumulated_report_path" in data


def list_profile_names(clients_dir: str = "clients") -> list[str]:
    if not os.path.isdir(clients_dir):
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(clients_dir)
        if f.endswith(".json") and _looks_like_profile(os.path.join(clients_dir, f))
    )
