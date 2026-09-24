from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FieldMapping:
    email: str
    first_name: str
    last_name: str
    company: str
    cid: str

    def is_blank(self) -> bool:
        """True if every field is empty -- a saved-but-never-filled-in
        mapping, distinct from None (never configured at all). A plain
        `some_field_mapping or fallback` treats ANY FieldMapping instance
        as truthy regardless of its field values, so a blank one (which a
        Client Setup form used to be able to save, since "optional"
        column-mapping sections returned FieldMapping(...) unconditionally
        instead of None when every dropdown was left as "No mapping")
        silently wins over the fallback instead of being treated as
        equivalent to unset. Use resolve_field_mapping() instead of `or`
        wherever a FieldMapping might come from one of those sections.
        """
        return not any([self.email, self.first_name, self.last_name, self.company, self.cid])


def resolve_field_mapping(preferred: "FieldMapping | None", fallback: "FieldMapping") -> "FieldMapping":
    """preferred if it's configured (not None and not blank), else
    fallback -- the correct replacement for `preferred or fallback`
    wherever preferred is an Optional[FieldMapping] that a Client Setup
    form can save as an all-blank (but non-None) FieldMapping instead of
    None. See FieldMapping.is_blank for why the plain `or` is unsafe.
    """
    return fallback if preferred is None or preferred.is_blank() else preferred


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
    # entered through. Blank means "don't send this parameter at all",
    # not "send it blank".
    campaign_link_id: str = ""


@dataclass
class ConvertrConfig:
    # Uploads a client-verified leadfile straight to Convertr's Publisher
    # API (https://{enterprise}.cvtr.io/api/v2.4/publisher/...) instead of
    # a manual portal upload -- every Publisher account has access to this
    # by default, unlike the Campaign Webhook v2's per-campaign, Admin-only
    # API key. Authenticates with the same account username/password used
    # to read back accepted/rejected leads -- deliberately NOT stored here,
    # since this profile JSON lives in the shared clients folder every
    # teammate can read; see core/app_settings.py for where that actually
    # lives.
    enabled: bool = False
    enterprise: str = ""
    # The account's own Convertr Publisher ID (from Tracking -> API
    # Credentials on any campaign) -- one fixed value for the whole
    # account, required in the Publisher API's URL path for every request.
    publisher_id: str = ""
    campaigns: list[ConvertrCampaignMapping] = field(default_factory=list)
    # {leadfile column name: Convertr form field name (without the
    # "form[]" wrapper -- core/convertr_client.py adds that)}, e.g.
    # {"Email": "email", "First Name": "firstName"}.
    field_mapping: dict[str, str] = field(default_factory=dict)
    # Which of the UPLOADED leadfile's own columns hold email/name/company/
    # CID -- set here so the Convertr page never depends on the client's QA
    # field_mapping (ClientProfile.field_mapping) being configured. Falls
    # back to that QA mapping when left blank, so an already-working client
    # doesn't need to re-enter it, but a client with no QA at all (e.g.
    # Amazon, uploaded straight to Convertr) doesn't need to visit Run
    # Check just to unlock this page.
    leadfile_field_mapping: Optional[FieldMapping] = None


@dataclass
class EnhancioAllocationMapping:
    # Each CID's leads upload to its own Enhancio allocation -- see
    # core/enhancio_client.py for the actual API calls this feeds.
    cid: str
    allocation_uid: str


@dataclass
class EnhancioConfig:
    # Uploads a client-verified leadfile straight to Enhancio's Lead Import
    # API (https://api-pubnet.enhancio.com/lead-api/v1/import). Unlike
    # Convertr, auth is ONE shared org-wide Connected App (Client ID only,
    # Enhancio-managed OAuth2) rather than a per-client login -- see
    # get_enhancio_client_id in core/app_settings.py -- so this config only
    # needs to know how to route each CID to its own allocation.
    enabled: bool = False
    allocations: list[EnhancioAllocationMapping] = field(default_factory=list)
    # {leadfile column name: Enhancio field label}, e.g. {"Email": "Email
    # Address", "First Name": "First Name"} -- keyed by the exact fieldLabel
    # the Describe Fields API reports for the allocation, not a fixed code.
    field_mapping: dict[str, str] = field(default_factory=dict)
    # {allocationUid: {Enhancio field label: fixed value}} -- fields that
    # Enhancio requires but which take the SAME value for every lead sent to
    # that allocation (e.g. Company Size, Lead Source), rather than varying
    # per row like field_mapping. Confirmed once here at Client Setup time;
    # every future upload to that allocation applies them automatically, no
    # re-confirmation at upload time.
    fixed_field_values: dict[str, dict[str, str]] = field(default_factory=dict)
    # Same purpose and fallback behavior as ConvertrConfig.leadfile_field_mapping.
    leadfile_field_mapping: Optional[FieldMapping] = None


@dataclass
class IntegrateConfig:
    # Uploads a client-verified leadfile straight to Integrate.com's Lead
    # API (https://api.integrate.com/api/v1/contracts/{sid}/leads) --
    # confirmed live from the account's own Import -> API tab. Unlike
    # Convertr/Enhancio, ONE SID per client (not per-CID), since a client
    # maps to exactly one Integrate Source for this rollout.
    enabled: bool = False
    sid: str = ""
    # Optional -- Integrate's own docs show this as an unrequired query
    # param. This app has no public endpoint to receive it, so it's sent
    # only when explicitly configured, never a made-up placeholder value.
    callback_url: str = ""
    # {leadfile column name: Integrate attribute name}, e.g.
    # {"Email": "email", "First Name": "first_name"}.
    field_mapping: dict[str, str] = field(default_factory=dict)
    # {Integrate attribute name: fixed value} -- for an attribute that's
    # the SAME for every lead this client sends (e.g. "country": "UK"),
    # not read from the leadfile row at all. Same purpose as
    # EnhancioConfig.fixed_field_values, but flat (not per-allocation)
    # since there's only one SID here.
    fixed_field_values: dict[str, str] = field(default_factory=dict)
    # Same purpose/fallback behavior as ConvertrConfig.leadfile_field_mapping.
    leadfile_field_mapping: Optional[FieldMapping] = None


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
    enhancio: EnhancioConfig = field(default_factory=EnhancioConfig)
    integrate: IntegrateConfig = field(default_factory=IntegrateConfig)
