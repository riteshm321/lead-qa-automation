import uuid

import streamlit as st

from core.excel_io import list_sheet_names, read_sheet_as_dataframe, detect_cids_from_pacing_overview
from core.file_browser import browse_for_file
from core.models import (
    ClientProfile, DuplicateConfig, LeadcapConfig, LeadcapSegment,
    ExclusionConfig, TalConfig, ReferenceSource, SuppressionConfig, DedupeListConfig,
)
from core.profile_store import save_profile, load_profile, list_profile_names

st.title("Client Setup")


def _path_input_with_browse(label: str, session_key: str, current_value: str) -> str:
    col1, col2 = st.columns([5, 1])
    with col2:
        st.write("")
        if st.button("Browse...", key=f"{session_key}_browse"):
            chosen = browse_for_file()
            if chosen:
                st.session_state[session_key] = chosen
                st.rerun()
    with col1:
        return st.text_input(label, value=current_value, key=session_key)


def _sources_to_state(sources: list[ReferenceSource]) -> list[dict]:
    return [
        {"id": str(uuid.uuid4()), "name": s.name, "file_path": s.file_path, "sheet_name": s.sheet_name,
         "cids": ",".join(s.cids), "domain_column": s.domain_column,
         "company_column": s.company_column, "email_column": s.email_column}
        for s in sources
    ]


def _render_sources_section(
    section_key: str,
    label: str,
    check_domain: bool,
    check_company: bool,
    check_email: bool,
) -> list[ReferenceSource]:
    result: list[ReferenceSource] = []
    if st.button(f"Add {label} Source", key=f"{section_key}_add"):
        st.session_state[section_key].append({
            "id": str(uuid.uuid4()), "name": "", "file_path": "", "sheet_name": "", "cids": "",
            "domain_column": "Domain", "company_column": "Account Name", "email_column": "Email",
        })

    remove_id = None
    for src in st.session_state[section_key]:
        row_id = src["id"]
        st.markdown(f"**{label} Source: {src['name'] or '(unnamed)'}**")

        path_key = f"{section_key}_path_{row_id}"
        if st.button("Browse...", key=f"{section_key}_browse_{row_id}"):
            chosen = browse_for_file()
            if chosen:
                st.session_state[path_key] = chosen
                st.rerun()

        src["name"] = st.text_input("Name", value=src["name"], key=f"{section_key}_name_{row_id}")
        src["file_path"] = st.text_input("File path", value=src["file_path"], key=path_key)

        sheet_options: list[str] = []
        if src["file_path"]:
            try:
                sheet_options = list_sheet_names(src["file_path"])
            except Exception as exc:
                st.error(f"Could not read sheets from '{src['file_path']}': {exc}")
        if sheet_options:
            sheet_idx = sheet_options.index(src["sheet_name"]) if src["sheet_name"] in sheet_options else 0
            src["sheet_name"] = st.selectbox("Sheet", sheet_options, index=sheet_idx,
                                              key=f"{section_key}_sheet_{row_id}")
        else:
            src["sheet_name"] = st.text_input("Sheet name (enter a valid file path above to pick from a list)",
                                               value=src["sheet_name"], key=f"{section_key}_sheet_text_{row_id}")

        header_options: list[str] = []
        if src["file_path"] and src["sheet_name"]:
            try:
                header_options = list(read_sheet_as_dataframe(src["file_path"], src["sheet_name"]).columns)
            except Exception:
                header_options = []

        def _column_picker(field_label: str, field_key: str, default: str) -> str:
            current = src.get(field_key, default)
            if header_options:
                idx = header_options.index(current) if current in header_options else 0
                return st.selectbox(field_label, header_options, index=idx,
                                     key=f"{section_key}_{field_key}_{row_id}")
            return st.text_input(f"{field_label} name", value=current,
                                  key=f"{section_key}_{field_key}_text_{row_id}")

        if check_domain:
            src["domain_column"] = _column_picker("Domain column", "domain_column", "Domain")
        if check_company:
            src["company_column"] = _column_picker("Company column", "company_column", "Account Name")
        if check_email:
            src["email_column"] = _column_picker("Email column", "email_column", "Email")

        src["cids"] = st.text_input("CIDs this source applies to (comma-separated, blank = applies to all leads)",
                                     value=src["cids"], key=f"{section_key}_cids_{row_id}")

        if st.button("Remove this source", key=f"{section_key}_remove_{row_id}"):
            remove_id = row_id

        result.append(ReferenceSource(
            name=src["name"], file_path=src["file_path"], sheet_name=src["sheet_name"],
            cids=[c.strip() for c in src["cids"].split(",") if c.strip()],
            domain_column=src.get("domain_column", "Domain"),
            company_column=src.get("company_column", "Account Name"),
            email_column=src.get("email_column", "Email"),
        ))

    if remove_id is not None:
        st.session_state[section_key] = [s for s in st.session_state[section_key] if s["id"] != remove_id]
        st.rerun()

    return result


def _find_source_name_problems(sources: list[ReferenceSource]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for src in sources:
        if not src.name.strip():
            problems.append("a source has a blank name")
        elif src.name in seen:
            problems.append(f"duplicate source name '{src.name}'")
        else:
            seen.add(src.name)
    return problems


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
accumulated_path = _path_input_with_browse(
    "Accumulated Report path", "accumulated_path_input",
    profile.accumulated_report_path if profile else "")
accumulated_tab_name = st.text_input("Accumulated tab name",
                                      value=profile.accumulated_tab_name if profile else "Accumulated")
refund_tab_name = st.text_input("Refund tab name",
                                 value=profile.refund_tab_name if profile else "Refund")

st.header("Checks")

duplicate_enabled = st.checkbox("Enable Duplicate check", value=profile.duplicate.enabled if profile else False)

st.subheader("Leadcap")
leadcap_enabled = st.checkbox("Enable Leadcap check", value=profile.leadcap.enabled if profile else False)
leadcap_check_company = st.checkbox("Also check Leadcap by company name",
                                     value=profile.leadcap.check_company_name if profile else False)
leadcap_segmented = st.checkbox("Leadcap is segmented by CID", value=profile.leadcap.segmented if profile else False)
leadcap_flat_cap = None
leadcap_segments: list[LeadcapSegment] = []
if leadcap_enabled and not leadcap_segmented:
    leadcap_flat_cap = st.number_input("Flat lead cap", min_value=0, step=1,
                                        value=profile.leadcap.flat_cap if profile and profile.leadcap.flat_cap else 0)
if leadcap_enabled and leadcap_segmented:
    if accumulated_path and st.button("Detect CIDs from Accumulated Report"):
        try:
            detected = detect_cids_from_pacing_overview(accumulated_path)
            st.session_state["leadcap_segments_text"] = "\n".join(f"{name}|{cid}|" for cid, name in detected)
        except Exception as exc:
            st.error(f"Could not detect CIDs from '{accumulated_path}': {exc}")
    st.caption("Define segments as: name | comma-separated CIDs | cap, one per line. "
               "Merge two rows' CIDs together (comma-separated) to share one cap across them.")
    default_text = "\n".join(f"{s.name}|{','.join(s.cids)}|{s.cap}" for s in (profile.leadcap.segments if profile else []))
    segment_text = st.text_area("Leadcap segments", value=default_text, key="leadcap_segments_text")
    for line in segment_text.splitlines():
        if not line.strip():
            continue
        name, cids_str, cap_str = [p.strip() for p in line.split("|")]
        leadcap_segments.append(LeadcapSegment(name=name, cids=[c.strip() for c in cids_str.split(",")],
                                                 cap=int(cap_str) if cap_str else 0))

_profile_identity = f"{mode}::{selected_name or ''}"
if st.session_state.get("_loaded_sources_for") != _profile_identity:
    st.session_state["_loaded_sources_for"] = _profile_identity
    st.session_state["exclusion_sources"] = _sources_to_state(profile.exclusion.sources) if profile else []
    st.session_state["tal_sources"] = _sources_to_state(profile.tal.sources) if profile else []
    st.session_state["suppression_sources"] = _sources_to_state(profile.suppression.sources) if profile else []
    st.session_state["dedupe_sources"] = _sources_to_state(profile.dedupe_list.sources) if profile else []

st.subheader("Exclusion")
exclusion_enabled = st.checkbox("Enable Exclusion check", value=profile.exclusion.enabled if profile else False)
exclusion_check_company = st.checkbox("Also check Exclusion by company name",
                                       value=profile.exclusion.check_company_name if profile else False)
exclusion_sources_result: list[ReferenceSource] = []
if exclusion_enabled:
    exclusion_sources_result = _render_sources_section(
        "exclusion_sources", "Exclusion", check_domain=True, check_company=exclusion_check_company, check_email=False)
if exclusion_enabled and not exclusion_sources_result:
    st.warning("Exclusion is enabled but no sources are configured — this check will do nothing.")

st.subheader("TAL")
tal_enabled = st.checkbox("Enable TAL check", value=profile.tal.enabled if profile else False)
tal_check_company = st.checkbox("Also check TAL by company name", value=profile.tal.check_company_name if profile else False)
tal_sources_result: list[ReferenceSource] = []
if tal_enabled:
    tal_sources_result = _render_sources_section(
        "tal_sources", "TAL", check_domain=True, check_company=tal_check_company, check_email=False)
if tal_enabled and not tal_sources_result:
    st.warning("TAL is enabled but no sources are configured — this check will do nothing.")

st.subheader("Suppression")
suppression_enabled = st.checkbox("Enable Suppression check", value=profile.suppression.enabled if profile else False)
suppression_check_domain = st.checkbox("Check Suppression by domain",
                                        value=profile.suppression.check_domain if profile else True)
suppression_check_company = st.checkbox("Check Suppression by company name",
                                         value=profile.suppression.check_company_name if profile else False)
suppression_check_email = st.checkbox("Check Suppression by email",
                                       value=profile.suppression.check_email if profile else False)
suppression_sources_result: list[ReferenceSource] = []
if suppression_enabled:
    suppression_sources_result = _render_sources_section(
        "suppression_sources", "Suppression", check_domain=suppression_check_domain,
        check_company=suppression_check_company, check_email=suppression_check_email)
if suppression_enabled and not suppression_sources_result:
    st.warning("Suppression is enabled but no sources are configured — this check will do nothing.")

st.subheader("Dedupe list")
dedupe_enabled = st.checkbox("Enable Dedupe list check", value=profile.dedupe_list.enabled if profile else False)
dedupe_sources_result: list[ReferenceSource] = []
if dedupe_enabled:
    dedupe_sources_result = _render_sources_section(
        "dedupe_sources", "Dedupe List", check_domain=False, check_company=False, check_email=True)
if dedupe_enabled and not dedupe_sources_result:
    st.warning("Dedupe list is enabled but no sources are configured — this check will do nothing.")

if st.button("Save Client Profile"):
    _checks_to_validate = [
        ("Exclusion", exclusion_enabled, exclusion_sources_result),
        ("TAL", tal_enabled, tal_sources_result),
        ("Suppression", suppression_enabled, suppression_sources_result),
        ("Dedupe list", dedupe_enabled, dedupe_sources_result),
    ]
    _name_error = None
    for _label, _enabled, _sources in _checks_to_validate:
        _problems = _find_source_name_problems(_sources) if _enabled else []
        if _problems:
            _name_error = f"{_label} sources have naming problems: " + "; ".join(_problems) + \
                          ". Each source needs a non-empty, unique name."
            break

    if not client_name:
        st.error("Client name is required.")
    elif _name_error:
        st.error(_name_error)
    else:
        new_profile = ClientProfile(
            name=client_name,
            accumulated_report_path=accumulated_path,
            accumulated_tab_name=accumulated_tab_name or "Accumulated",
            refund_tab_name=refund_tab_name or "Refund",
            field_mapping=profile.field_mapping if profile else None,
            duplicate=DuplicateConfig(enabled=duplicate_enabled),
            leadcap=LeadcapConfig(enabled=leadcap_enabled, segmented=leadcap_segmented,
                                   flat_cap=int(leadcap_flat_cap) if leadcap_flat_cap else None,
                                   segments=leadcap_segments, check_company_name=leadcap_check_company),
            exclusion=ExclusionConfig(enabled=exclusion_enabled, check_company_name=exclusion_check_company,
                                       sources=exclusion_sources_result),
            tal=TalConfig(enabled=tal_enabled, check_company_name=tal_check_company,
                          sources=tal_sources_result),
            suppression=SuppressionConfig(enabled=suppression_enabled, check_domain=suppression_check_domain,
                                           check_company_name=suppression_check_company,
                                           check_email=suppression_check_email,
                                           sources=suppression_sources_result),
            dedupe_list=DedupeListConfig(enabled=dedupe_enabled, sources=dedupe_sources_result),
        )
        saved_path = save_profile(new_profile)
        st.success(f"Saved profile to {saved_path}")
