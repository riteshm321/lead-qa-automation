from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FieldMapping:
    email: str
    first_name: str
    last_name: str
    company: str
    cid: str


@dataclass
class LeadcapSegment:
    name: str
    cids: list[str]
    cap: int


@dataclass
class LeadcapConfig:
    enabled: bool = False
    segmented: bool = False
    flat_cap: Optional[int] = None
    segments: list[LeadcapSegment] = field(default_factory=list)
    check_company_name: bool = False
    purchased_report_cid_column: str = "Campaign ID"
    purchased_report_email_column: str = "Email"
    purchased_report_company_column: str = "Company"


@dataclass
class ReferenceSource:
    name: str
    file_path: str
    sheet_name: str
    cids: list[str] = field(default_factory=list)
    domain_column: str = "Domain"
    company_column: str = "Account Name"
    email_column: str = "Email"


@dataclass
class TalConfig:
    enabled: bool = False
    check_company_name: bool = False
    sources: list[ReferenceSource] = field(default_factory=list)


@dataclass
class ExclusionConfig:
    enabled: bool = False
    check_company_name: bool = False
    sources: list[ReferenceSource] = field(default_factory=list)


@dataclass
class SuppressionConfig:
    enabled: bool = False
    check_domain: bool = False
    check_company_name: bool = False
    check_email: bool = False
    sources: list[ReferenceSource] = field(default_factory=list)


@dataclass
class DuplicateConfig:
    enabled: bool = False


@dataclass
class DedupeListConfig:
    enabled: bool = False
    sources: list[ReferenceSource] = field(default_factory=list)


@dataclass
class LeadTemplateTab:
    sheet_name: str
    cids: list[str] = field(default_factory=list)


@dataclass
class ClientProfile:
    name: str
    accumulated_report_path: str
    accumulated_tab_name: str = "Accumulated"
    refund_tab_name: str = "Refund"
    jira_ticket_key: str = ""
    client_mode: str = "Lead QA"
    lead_template_path: str = ""
    lead_template_sheet_name: str = ""
    lead_template_multi_tab: bool = False
    lead_template_tabs: list[LeadTemplateTab] = field(default_factory=list)
    field_mapping: Optional[FieldMapping] = None
    accumulated_field_mapping: Optional[FieldMapping] = None
    lead_template_field_mapping: Optional[FieldMapping] = None
    duplicate: DuplicateConfig = field(default_factory=DuplicateConfig)
    leadcap: LeadcapConfig = field(default_factory=LeadcapConfig)
    exclusion: ExclusionConfig = field(default_factory=ExclusionConfig)
    tal: TalConfig = field(default_factory=TalConfig)
    suppression: SuppressionConfig = field(default_factory=SuppressionConfig)
    dedupe_list: DedupeListConfig = field(default_factory=DedupeListConfig)
