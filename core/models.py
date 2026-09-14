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
    # Blank means "use the client's shared Lead Template path" — set this
    # when this CID group's leads actually go to a completely different
    # workbook rather than another tab in the same one.
    file_path: str = ""
    # Blank means "use the client's shared Lead Template SharePoint link" —
    # set this when file_path points at a different workbook, since that
    # workbook lives at its own SharePoint location with its own share link.
    link: str = ""


@dataclass
class ComplexAccountConfig:
    # A "complex account" needs a batch of highly specific, largely
    # non-transferable enrichment rules (TAL account-ID mapping, per-CID
    # Installed Technologies/Predictive Buying Stage lookups, asset
    # metadata auto-correction, etc.) on top of the normal QA pipeline —
    # see core/complex_account.py for the actual rule implementations.
    enabled: bool = False
    tal_path: str = ""
    specifications_path: str = ""


@dataclass
class BoxTrackerConfig:
    # IBM APAC's process (and any future similar Complex Account client)
    # pastes picked leads into a client-facing Box-hosted tracker workbook
    # for approval, then logs accepted leads back into it after upload --
    # but this app has no Box API access, so it maintains a LOCAL mirror
    # workbook with the same tab/column shape instead, and the user
    # copy-pastes between the two by hand. See
    # docs/superpowers/plans/2026-09-07-ibm-apac-box-tracker-automation.md
    # for the full design.
    enabled: bool = False
    mirror_workbook_path: str = ""
    # {CID: Campaign name}, e.g. {"118741": "Bob"} -- used both to sort
    # picked leads into the right Pacing/Approval-Sheet bucket and to fill
    # Response Details' Campaign Name column.
    cid_campaign_map: dict[str, str] = field(default_factory=dict)
    # {CID: Lead Template file path} -- each live segment has its own
    # template file (filename identifies which segment it's for), so
    # writing cleared leads there is routed by the lead's own CID rather
    # than a single shared path like the normal Lead QA & Upload flow uses.
    cid_lead_template_path: dict[str, str] = field(default_factory=dict)
    # Campaign names (matching cid_campaign_map's values) to pick ALL
    # available blank-Status leads for -- ignoring the Pacing Diff target
    # entirely -- and to skip the Pacing Delivered-cell write for, both at
    # pick time and at reconciliation time. For a segment that's only just
    # gone live (e.g. CXO) with no established Pacing history yet, forcing
    # it through the diff-based cap (which would be 0 or undefined) isn't
    # right; the pacing numbers get turned back on for it later by simply
    # removing it from this list.
    pacing_skipped_campaigns: list[str] = field(default_factory=list)


@dataclass
class ConvertrCampaignMapping:
    # Each CID's leads upload to its own Convertr campaign/form -- see
    # core/convertr_client.py for the actual API calls these feed.
    cid: str
    campaign_id: str
    global_form_id: str
    # Optional per Convertr's own API: attributes which channel a lead
    # entered through / which publisher gets credited. Blank means "don't
    # send this parameter at all", not "send it blank".
    campaign_link_id: str = ""
    publisher_id: str = ""


@dataclass
class ConvertrConfig:
    # Uploads a client-verified leadfile straight to Convertr's Campaign
    # Webhook v2 API (https://{enterprise}.cvtr.io/webhook/campaign/...)
    # instead of a manual portal upload. Each campaign authenticates with
    # its own Campaign API Key -- deliberately NOT stored here, since this
    # profile JSON lives in the shared clients folder every teammate can
    # read; see core/convertr_secrets.py for where that actually lives.
    enabled: bool = False
    enterprise: str = ""
    campaigns: list[ConvertrCampaignMapping] = field(default_factory=list)
    # {leadfile column name: Convertr form field name (without the
    # "form[]" wrapper -- core/convertr_client.py adds that)}, e.g.
    # {"Email": "email", "First Name": "firstName"}.
    field_mapping: dict[str, str] = field(default_factory=dict)


@dataclass
class ClientProfile:
    name: str
    accumulated_report_path: str
    accumulated_tab_name: str = "Accumulated"
    refund_tab_name: str = "Refund"
    jira_ticket_key: str = ""
    jira_reporter_name: str = ""
    # SharePoint share links used in Jira comments instead of a file:// path
    # that only opens on the machine it was posted from.
    accumulated_report_link: str = ""
    lead_template_link: str = ""
    client_mode: str = "Lead QA"
    # Offers the "collate multiple files into one New Leads file" option on
    # Run Check for this client -- NOT forced on, since the same client can
    # arrive with an already-collated file on any given run (see
    # core/collation.py). Off by default for every client.
    collation_enabled: bool = False
    lead_template_path: str = ""
    lead_template_sheet_name: str = ""
    lead_template_multi_tab: bool = False
    lead_template_tabs: list[LeadTemplateTab] = field(default_factory=list)
    lead_template_clear_existing: bool = False
    field_mapping: Optional[FieldMapping] = None
    accumulated_field_mapping: Optional[FieldMapping] = None
    lead_template_field_mapping: Optional[FieldMapping] = None
    duplicate: DuplicateConfig = field(default_factory=DuplicateConfig)
    leadcap: LeadcapConfig = field(default_factory=LeadcapConfig)
    exclusion: ExclusionConfig = field(default_factory=ExclusionConfig)
    tal: TalConfig = field(default_factory=TalConfig)
    suppression: SuppressionConfig = field(default_factory=SuppressionConfig)
    dedupe_list: DedupeListConfig = field(default_factory=DedupeListConfig)
    complex_account: ComplexAccountConfig = field(default_factory=ComplexAccountConfig)
    box_tracker: BoxTrackerConfig = field(default_factory=BoxTrackerConfig)
    convertr: ConvertrConfig = field(default_factory=ConvertrConfig)
