import streamlit as st

from core.aliases_path import ALIASES_PATH
from core.excel_io import list_sheet_names
from core.models import (
    ClientProfile, FieldMapping, DuplicateConfig, LeadcapConfig, LeadcapSegment,
    ExclusionConfig, TalConfig, TalSegment, SuppressionConfig, DedupeListConfig,
)
from core.profile_store import save_profile, load_profile, list_profile_names

st.title("Client Setup")

existing = list_profile_names()
mode = st.radio("Mode", ["Create new client", "Edit existing client"])

if mode == "Edit existing client" and existing:
    selected_name = st.selectbox("Client", existing)
    profile = load_profile(selected_name)
else:
    selected_name = None
    profile = None

client_name = st.text_input("Client name", value=profile.name if profile else "")

st.header("Reference Files")
accumulated_path = st.text_input("Accumulated Report path",
                                  value=profile.accumulated_report_path if profile else "")
accumulated_tab_name = st.text_input("Accumulated tab name",
                                      value=profile.accumulated_tab_name if profile else "Accumulated")
refund_tab_name = st.text_input("Refund tab name",
                                 value=profile.refund_tab_name if profile else "Refund")
tal_path = st.text_input("TAL file path", value=(profile.tal_path if profile else "") or "")
exclusion_path = st.text_input("Exclusion List path", value=(profile.exclusion_path if profile else "") or "")
suppression_path = st.text_input("Suppression List path", value=(profile.suppression_path if profile else "") or "")
dedupe_list_path = st.text_input("Dedupe List path (optional)", value=(profile.dedupe_list_path if profile else "") or "")

st.header("Field Mapping (from a sample New Leads file)")
sample_leads_path = st.text_input("Path to a sample New Leads file, to read its column headers")
lead_headers: list[str] = []
if sample_leads_path:
    try:
        from core.excel_io import read_sheet_as_dataframe
        sheet = list_sheet_names(sample_leads_path)[0]
        lead_headers = list(read_sheet_as_dataframe(sample_leads_path, sheet).columns)
    except Exception as exc:
        st.error(f"Could not read headers from '{sample_leads_path}': {exc}")

if lead_headers:
    _fm_default = profile.field_mapping if profile else None

    def _idx(value: str | None) -> int:
        return lead_headers.index(value) if value and value in lead_headers else 0

    fm_email = st.selectbox("Email column", lead_headers, index=_idx(_fm_default.email if _fm_default else None))
    fm_first = st.selectbox("First Name column", lead_headers, index=_idx(_fm_default.first_name if _fm_default else None))
    fm_last = st.selectbox("Last Name column", lead_headers, index=_idx(_fm_default.last_name if _fm_default else None))
    fm_company = st.selectbox("Company column", lead_headers, index=_idx(_fm_default.company if _fm_default else None))
    fm_cid = st.selectbox("CID column", lead_headers, index=_idx(_fm_default.cid if _fm_default else None))
else:
    if profile and profile.field_mapping:
        st.info("Using the field mapping already saved on this profile. "
                 "Enter a sample New Leads file path above only if you need to change it.")
    else:
        st.info("Enter a sample New Leads file path above to map its columns.")
    fm_email = fm_first = fm_last = fm_company = fm_cid = ""

st.header("Checks")

duplicate_enabled = st.checkbox("Enable Duplicate check", value=profile.duplicate.enabled if profile else False)

st.subheader("Leadcap")
leadcap_enabled = st.checkbox("Enable Leadcap check", value=profile.leadcap.enabled if profile else False)
leadcap_segmented = st.checkbox("Leadcap is segmented by CID", value=profile.leadcap.segmented if profile else False)
leadcap_flat_cap = None
leadcap_segments: list[LeadcapSegment] = []
if leadcap_enabled and not leadcap_segmented:
    leadcap_flat_cap = st.number_input("Flat lead cap", min_value=0, step=1,
                                        value=profile.leadcap.flat_cap if profile and profile.leadcap.flat_cap else 0)
if leadcap_enabled and leadcap_segmented:
    st.caption("Define segments as: name | comma-separated CIDs | cap, one per line")
    default_text = "\n".join(f"{s.name}|{','.join(s.cids)}|{s.cap}" for s in (profile.leadcap.segments if profile else []))
    segment_text = st.text_area("Leadcap segments", value=default_text, key="leadcap_segments_text")
    for line in segment_text.splitlines():
        if not line.strip():
            continue
        name, cids_str, cap_str = [p.strip() for p in line.split("|")]
        leadcap_segments.append(LeadcapSegment(name=name, cids=[c.strip() for c in cids_str.split(",")], cap=int(cap_str)))

st.subheader("Exclusion")
exclusion_enabled = st.checkbox("Enable Exclusion check", value=profile.exclusion.enabled if profile else False)
exclusion_check_company = st.checkbox("Also check Exclusion by company name",
                                       value=profile.exclusion.check_company_name if profile else False)
exclusion_sheet = None
if exclusion_enabled and exclusion_path:
    try:
        sheets = list_sheet_names(exclusion_path)
        _exclusion_idx = (sheets.index(profile.exclusion.sheet_name)
                          if profile and profile.exclusion.sheet_name in sheets else 0)
        exclusion_sheet = st.selectbox("Which sheet holds the exclusion data?", sheets, index=_exclusion_idx)
    except Exception as exc:
        st.error(f"Could not read sheets from '{exclusion_path}': {exc}")

st.subheader("TAL")
tal_enabled = st.checkbox("Enable TAL check", value=profile.tal.enabled if profile else False)
tal_check_company = st.checkbox("Also check TAL by company name", value=profile.tal.check_company_name if profile else False)
tal_segmented = st.checkbox("TAL is segmented by CID (different tabs per segment)",
                             value=profile.tal.segmented if profile else False)
tal_flat_sheet = None
tal_segments: list[TalSegment] = []
if tal_enabled and tal_path:
    try:
        tal_sheets = list_sheet_names(tal_path)
    except Exception as exc:
        st.error(f"Could not read sheets from '{tal_path}': {exc}")
        tal_sheets = []
    if tal_enabled and not tal_segmented and tal_sheets:
        _tal_flat_idx = (tal_sheets.index(profile.tal.flat_sheet_name)
                         if profile and profile.tal.flat_sheet_name in tal_sheets else 0)
        tal_flat_sheet = st.selectbox("TAL sheet", tal_sheets, index=_tal_flat_idx)
    if tal_enabled and tal_segmented and tal_sheets:
        st.caption("Define segments as: name | comma-separated CIDs | sheet name, one per line")
        default_text = "\n".join(f"{s.name}|{','.join(s.cids)}|{s.sheet_name}" for s in (profile.tal.segments if profile else []))
        tal_segment_text = st.text_area("TAL segments", value=default_text, key="tal_segments_text")
        for line in tal_segment_text.splitlines():
            if not line.strip():
                continue
            name, cids_str, sheet_name = [p.strip() for p in line.split("|")]
            tal_segments.append(TalSegment(name=name, cids=[c.strip() for c in cids_str.split(",")], sheet_name=sheet_name))

st.subheader("Suppression")
suppression_enabled = st.checkbox("Enable Suppression check", value=profile.suppression.enabled if profile else False)
suppression_check_domain = st.checkbox("Check Suppression by domain", value=profile.suppression.check_domain if profile else True)
suppression_check_company = st.checkbox("Check Suppression by company name", value=profile.suppression.check_company_name if profile else False)
suppression_check_email = st.checkbox("Check Suppression by email", value=profile.suppression.check_email if profile else False)
suppression_sheet = None
if suppression_enabled and suppression_path:
    try:
        sheets = list_sheet_names(suppression_path)
        _suppression_idx = (sheets.index(profile.suppression.sheet_name)
                            if profile and profile.suppression.sheet_name in sheets else 0)
        suppression_sheet = st.selectbox("Which sheet holds the suppression data?", sheets,
                                          index=_suppression_idx, key="suppression_sheet")
    except Exception as exc:
        st.error(f"Could not read sheets from '{suppression_path}': {exc}")

st.subheader("Dedupe list")
dedupe_enabled = st.checkbox("Enable Dedupe list check", value=profile.dedupe_list.enabled if profile else False)
dedupe_sheet = None
if dedupe_enabled and dedupe_list_path:
    try:
        sheets = list_sheet_names(dedupe_list_path)
        _dedupe_idx = (sheets.index(profile.dedupe_list.sheet_name)
                       if profile and profile.dedupe_list.sheet_name in sheets else 0)
        dedupe_sheet = st.selectbox("Which sheet holds the dedupe list data?", sheets,
                                     index=_dedupe_idx, key="dedupe_sheet")
    except Exception as exc:
        st.error(f"Could not read sheets from '{dedupe_list_path}': {exc}")

if st.button("Save Client Profile"):
    if not client_name:
        st.error("Client name is required.")
    else:
        if fm_email:
            new_field_mapping = FieldMapping(email=fm_email, first_name=fm_first, last_name=fm_last,
                                              company=fm_company, cid=fm_cid)
        else:
            # No new sample file was read this session (or it failed to read) — preserve the
            # existing field mapping rather than silently wiping it out on Save.
            new_field_mapping = profile.field_mapping if profile else None

        new_profile = ClientProfile(
            name=client_name,
            accumulated_report_path=accumulated_path,
            accumulated_tab_name=accumulated_tab_name or "Accumulated",
            refund_tab_name=refund_tab_name or "Refund",
            tal_path=tal_path or None,
            exclusion_path=exclusion_path or None,
            suppression_path=suppression_path or None,
            dedupe_list_path=dedupe_list_path or None,
            field_mapping=new_field_mapping,
            duplicate=DuplicateConfig(enabled=duplicate_enabled),
            leadcap=LeadcapConfig(enabled=leadcap_enabled, segmented=leadcap_segmented,
                                   flat_cap=int(leadcap_flat_cap) if leadcap_flat_cap else None,
                                   segments=leadcap_segments),
            exclusion=ExclusionConfig(enabled=exclusion_enabled, check_company_name=exclusion_check_company,
                                       sheet_name=exclusion_sheet or "Exclusion"),
            tal=TalConfig(enabled=tal_enabled, check_company_name=tal_check_company, segmented=tal_segmented,
                          flat_sheet_name=tal_flat_sheet, segments=tal_segments),
            suppression=SuppressionConfig(enabled=suppression_enabled, check_domain=suppression_check_domain,
                                           check_company_name=suppression_check_company,
                                           check_email=suppression_check_email,
                                           sheet_name=suppression_sheet or "Sheet1"),
            dedupe_list=DedupeListConfig(enabled=dedupe_enabled, sheet_name=dedupe_sheet or "Sheet1"),
        )
        saved_path = save_profile(new_profile)
        st.success(f"Saved profile to {saved_path}")
