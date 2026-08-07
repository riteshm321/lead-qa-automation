import dataclasses
import json
import os

from core.models import (
    ClientProfile, FieldMapping, LeadcapConfig, LeadcapSegment,
    TalConfig, TalSegment, ExclusionConfig, SuppressionConfig,
    DuplicateConfig, DedupeListConfig,
)


def _profile_path(name: str, clients_dir: str) -> str:
    return os.path.join(clients_dir, f"{name}.json")


def save_profile(profile: ClientProfile, clients_dir: str = "clients") -> str:
    os.makedirs(clients_dir, exist_ok=True)
    path = _profile_path(profile.name, clients_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dataclasses.asdict(profile), f, indent=2)
    return path


def load_profile(name: str, clients_dir: str = "clients") -> ClientProfile:
    path = _profile_path(name, clients_dir)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    fm = data.get("field_mapping")
    field_mapping = FieldMapping(**fm) if fm else None

    leadcap = data.get("leadcap") or {}
    leadcap["segments"] = [LeadcapSegment(**s) for s in leadcap.get("segments", [])]

    tal = data.get("tal") or {}
    tal["segments"] = [TalSegment(**s) for s in tal.get("segments", [])]

    return ClientProfile(
        name=data["name"],
        accumulated_report_path=data["accumulated_report_path"],
        tal_path=data.get("tal_path"),
        exclusion_path=data.get("exclusion_path"),
        suppression_path=data.get("suppression_path"),
        dedupe_list_path=data.get("dedupe_list_path"),
        field_mapping=field_mapping,
        duplicate=DuplicateConfig(**(data.get("duplicate") or {})),
        leadcap=LeadcapConfig(**leadcap),
        exclusion=ExclusionConfig(**(data.get("exclusion") or {})),
        tal=TalConfig(**tal),
        suppression=SuppressionConfig(**(data.get("suppression") or {})),
        dedupe_list=DedupeListConfig(**(data.get("dedupe_list") or {})),
    )


def list_profile_names(clients_dir: str = "clients") -> list[str]:
    if not os.path.isdir(clients_dir):
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(clients_dir)
        if f.endswith(".json")
    )
