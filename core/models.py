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
    purchased_report_cid_column: str = "Campaign ID"
    purchased_report_email_column: str = "Email"


@dataclass
class TalSegment:
    name: str
    cids: list[str]
    sheet_name: str


@dataclass
class TalConfig:
    enabled: bool = False
    check_company_name: bool = False
    segmented: bool = False
    flat_sheet_name: Optional[str] = None
    segments: list[TalSegment] = field(default_factory=list)
    domain_column: str = "Domain"
    company_column: str = "Account Name"


@dataclass
class ExclusionConfig:
    enabled: bool = False
    check_company_name: bool = False
    sheet_name: str = "Exclusion"
    domain_column: str = "Domain"
    company_column: str = "Account Name"


@dataclass
class SuppressionConfig:
    enabled: bool = False
    check_domain: bool = False
    check_company_name: bool = False
    check_email: bool = False
    sheet_name: str = "Sheet1"
    domain_column: str = "Domain"
    company_column: str = "Account Name"
    email_column: str = "Email"


@dataclass
class DuplicateConfig:
    enabled: bool = False


@dataclass
class DedupeListConfig:
    enabled: bool = False
    sheet_name: str = "Sheet1"
    email_column: str = "Email"


@dataclass
class ClientProfile:
    name: str
    accumulated_report_path: str
    accumulated_tab_name: str = "Accumulated"
    refund_tab_name: str = "Refund"
    tal_path: Optional[str] = None
    exclusion_path: Optional[str] = None
    suppression_path: Optional[str] = None
    dedupe_list_path: Optional[str] = None
    field_mapping: Optional[FieldMapping] = None
    duplicate: DuplicateConfig = field(default_factory=DuplicateConfig)
    leadcap: LeadcapConfig = field(default_factory=LeadcapConfig)
    exclusion: ExclusionConfig = field(default_factory=ExclusionConfig)
    tal: TalConfig = field(default_factory=TalConfig)
    suppression: SuppressionConfig = field(default_factory=SuppressionConfig)
    dedupe_list: DedupeListConfig = field(default_factory=DedupeListConfig)
