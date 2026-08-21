# pages/2_Run_Check.py
import datetime
import os
import shutil

import pandas as pd
import streamlit as st

from core.app_settings import get_aliases_path, get_clients_dir, get_jira_settings
from core.branding import configure_page
from core.checks.leadcap import validate_purchased_report_cids
from core.errors import render_error
from core.excel_io import (
    read_sheet_as_dataframe, append_leads, backup_file, require_columns, find_header_row, route_leads_by_cid,
    read_leadfile, read_pacing_overview_table,
)
from core.excel_recalc import recalculate_workbook
from core.complex_account import (
    load_tal_index, load_asset_specifications, load_domain_value_map,
    apply_complex_account_rules, merge_complex_account_review, check_complex_account_conditions,
    ACCOUNT_ID_COLUMN, COMPANY_COLUMN, TOP_TOPICS_COLUMN, INSTALLED_TECH_COLUMN, PBS_COLUMN,
    CAPTURE_DATE_COLUMN, EMAIL_OPTIN_COLUMN, PHONE_COLUMN,
)
from core import jira_client
from core.jira_client import JiraError
from core.matching import load_alias_groups, add_alias_pair
from core.models import FieldMapping
from core.pipeline import run_pipeline, apply_refund_overrides
from core.profile_store import list_profile_names, load_profile, save_profile
import requests

configure_page("Run Check")
st.title("▶️ Run Check")


@st.cache_data(show_spinner="Loading TAL reference file (large file, first load can take ~15s)...")
def _cached_tal_index(path: str, mtime: float):
    # mtime must NOT be underscore-prefixed — Streamlit excludes any
    # parameter named with a leading underscore from the cache key hash,
    # which would silently defeat the whole point of passing it in (to
    # invalidate the cache when the file changes on disk mid-session).
    return load_tal_index(path)


@st.cache_data(show_spinner="Loading asset specifications...")
def _cached_asset_specs(path: str, mtime: float):
    # See _cached_tal_index above — same reasoning for the mtime param name.
    return load_asset_specifications(path)


profile_names = list_profile_names(get_clients_dir())
if not profile_names:
    st.warning("No client profiles found. Create one on the Client Setup page first.")
    st.stop()

col_client, col_clear = st.columns([5, 1], vertical_alignment="bottom")
with col_client:
    client_name = st.selectbox("Client", profile_names)
with col_clear:
    if st.button("🔄 Clear", use_container_width=True,
                 help="Clear the uploaded files and any displayed results, and start a fresh run."):
        for key in ("run_result", "run_new_leads", "run_result_for", "last_finalized_summary"):
            st.session_state.pop(key, None)
        st.session_state["upload_reset_counter"] = st.session_state.get("upload_reset_counter", 0) + 1
        st.rerun()

try:
    profile = load_profile(client_name, get_clients_dir())
except TypeError as exc:
    st.error(f"Could not load the profile for '{client_name}' — it may be in an older format. "
             f"Delete and re-create it in Client Setup. (Technical detail: {exc})")
    st.stop()

# A stale result from a previous client/file is more confusing than useful —
# drop it automatically the moment the client or uploaded file changes.
_run_identity = client_name
if st.session_state.get("run_result_for") not in (None, _run_identity) and "run_result" in st.session_state:
    for key in ("run_result", "run_new_leads", "run_result_for"):
        st.session_state.pop(key, None)

_upload_key_suffix = st.session_state.get("upload_reset_counter", 0)

_enabled_checks = ", ".join(
    label for label, on in [
        ("Duplicate", profile.duplicate.enabled), ("Leadcap", profile.leadcap.enabled),
        ("Exclusion", profile.exclusion.enabled), ("TAL", profile.tal.enabled),
        ("Suppression", profile.suppression.enabled), ("Dedupe list", profile.dedupe_list.enabled),
    ] if on
) or "None"
st.caption(f"Mode: **{profile.client_mode}** · Enabled checks: {_enabled_checks}")
st.divider()

new_leads_file = st.file_uploader("New Leads file", type=["xlsx", "csv"], key=f"new_leads_upload_{_upload_key_suffix}")

new_leads_df = None
new_leads_headers: list[str] = []
if new_leads_file:
    try:
        new_leads_df = read_leadfile(new_leads_file)
        new_leads_headers = list(new_leads_df.columns)
    except Exception as exc:
        render_error(exc)
        st.stop()

field_mapping = profile.field_mapping
mapping_valid = (
    field_mapping is not None
    and all(col in new_leads_headers for col in
            [field_mapping.email, field_mapping.first_name, field_mapping.last_name,
             field_mapping.company, field_mapping.cid])
)

if new_leads_file and not mapping_valid:
    st.subheader("Map New Leads columns")
    st.caption("This client's saved mapping doesn't match this file's columns (or none is saved yet) — "
               "map them once, and it'll be remembered for future runs.")

    def _idx(value: str | None) -> int:
        return new_leads_headers.index(value) if value and value in new_leads_headers else 0

    fm_email = st.selectbox("Email column", new_leads_headers, index=_idx(field_mapping.email if field_mapping else None))
    fm_first = st.selectbox("First Name column", new_leads_headers, index=_idx(field_mapping.first_name if field_mapping else None))
    fm_last = st.selectbox("Last Name column", new_leads_headers, index=_idx(field_mapping.last_name if field_mapping else None))
    fm_company = st.selectbox("Company column", new_leads_headers, index=_idx(field_mapping.company if field_mapping else None))
    fm_cid = st.selectbox("CID column", new_leads_headers, index=_idx(field_mapping.cid if field_mapping else None))

    if st.button("Save column mapping for this client"):
        profile.field_mapping = FieldMapping(email=fm_email, first_name=fm_first, last_name=fm_last,
                                              company=fm_company, cid=fm_cid)
        save_profile(profile, get_clients_dir())
        st.success("Column mapping saved for this client.")
        st.rerun()

purchased_reports: dict[str, pd.DataFrame] = {}
if profile.leadcap.enabled:
    st.subheader("Leadcap: Purchased Lead Report")
    leadcap_required_cols = [profile.leadcap.purchased_report_cid_column, profile.leadcap.purchased_report_email_column]
    if profile.leadcap.check_company_name:
        leadcap_required_cols.append(profile.leadcap.purchased_report_company_column)

    if profile.leadcap.segmented:
        all_cids = [cid for segment in profile.leadcap.segments for cid in segment.cids]
        st.caption(f"Upload a single Purchased Lead Report covering all CIDs ({', '.join(all_cids)}) — "
                   "each segment's cap is checked against its own CIDs from this one file.")

    uploaded = st.file_uploader("Purchased Lead Report", type=["csv"], key=f"purchased_report_{_upload_key_suffix}")
    if uploaded:
        df = pd.read_csv(uploaded)
        try:
            require_columns(df, leadcap_required_cols, "Purchased Lead Report")
            if profile.leadcap.segmented:
                all_cids = [cid for segment in profile.leadcap.segments for cid in segment.cids]
                unexpected = validate_purchased_report_cids(df, all_cids, profile.leadcap.purchased_report_cid_column)
                if unexpected:
                    st.warning(f"Purchased Lead Report contains unexpected CIDs {unexpected} — double check this is the right file.")
                for segment in profile.leadcap.segments:
                    purchased_reports[segment.name] = df
            else:
                purchased_reports["_flat_"] = df
        except ValueError as exc:
            render_error(exc)

complex_it_files = []
complex_pbs_files = []
# Keyed by position, not filename — the uploader allows two files with the
# identical name (e.g. the same export downloaded twice for different
# CIDs), which would otherwise collide on both the widget key and the dict.
complex_it_file_cids: dict[int, str] = {}
complex_pbs_file_cids: dict[int, str] = {}
if profile.complex_account.enabled:
    st.subheader("Complex Account: Installed Technologies & Predictive Buying Stage")
    st.caption("Upload this run's per-CID reference files, then pick which CID each one is for — "
               "the filename doesn't reliably identify the CID, so it's not auto-detected.")

    _leadfile_cids = []
    if mapping_valid:
        _leadfile_cids = sorted(set(new_leads_df[field_mapping.cid].dropna().astype(str).str.strip()) - {""})
    _cid_options = _leadfile_cids or ["(upload a New Leads file first to see its CIDs)"]

    complex_it_files = st.file_uploader(
        "Installed Technologies files", type=["csv"], accept_multiple_files=True,
        key=f"complex_it_files_{_upload_key_suffix}") or []
    for _i, _f in enumerate(complex_it_files):
        complex_it_file_cids[_i] = st.selectbox(
            f"CID for \"{_f.name}\"", _cid_options, key=f"complex_it_cid_{_upload_key_suffix}_{_i}")

    complex_pbs_files = st.file_uploader(
        "Predictive Buying Stage files", type=["csv"], accept_multiple_files=True,
        key=f"complex_pbs_files_{_upload_key_suffix}") or []
    for _i, _f in enumerate(complex_pbs_files):
        complex_pbs_file_cids[_i] = st.selectbox(
            f"CID for \"{_f.name}\"", _cid_options, key=f"complex_pbs_cid_{_upload_key_suffix}_{_i}")

if st.button("Run Check") and new_leads_file:
    if not mapping_valid:
        st.error("Map the New Leads columns above before running the check.")
        st.stop()
    try:
        with st.spinner("Running checks..."):
            new_leads = new_leads_df
            accumulated_leads = read_sheet_as_dataframe(profile.accumulated_report_path, profile.accumulated_tab_name)

            complex_review = {}
            if profile.complex_account.enabled:
                # Only the conditions that can actually flag a lead (bad
                # Capture Date, ambiguous Email Opt-in, an already-filled Asset
                # URN/Form URL/Dell Asset URL that doesn't match the
                # specifications file) run here, so they go through the same
                # Refund/Needs Review flow as every other check. The
                # column-filling rules (TAL mapping, Installed Technologies/
                # Predictive Buying Stage, phone/date formatting) run later,
                # only on whichever leads end up valid — see the "Finalize
                # (fill columns)" step below.
                _check_asset_specs = None
                if profile.complex_account.specifications_path:
                    _check_asset_specs = _cached_asset_specs(
                        profile.complex_account.specifications_path,
                        os.path.getmtime(profile.complex_account.specifications_path))
                complex_review = check_complex_account_conditions(new_leads, _check_asset_specs)

            reference_data: dict = {"purchased_reports": purchased_reports}
            if profile.exclusion.enabled:
                exclusion_sources_data: dict[str, pd.DataFrame] = {}
                for source in profile.exclusion.sources:
                    df = read_sheet_as_dataframe(source.file_path, source.sheet_name)
                    required_cols = [source.domain_column]
                    if profile.exclusion.check_company_name:
                        required_cols.append(source.company_column)
                    require_columns(df, required_cols, f"{source.file_path} [{source.sheet_name}]")
                    exclusion_sources_data[source.name] = df
                reference_data["exclusion_sources"] = exclusion_sources_data
            if profile.tal.enabled:
                tal_sources_data: dict[str, pd.DataFrame] = {}
                for source in profile.tal.sources:
                    df = read_sheet_as_dataframe(source.file_path, source.sheet_name)
                    required_cols = [source.domain_column]
                    if profile.tal.check_company_name:
                        required_cols.append(source.company_column)
                    require_columns(df, required_cols, f"{source.file_path} [{source.sheet_name}]")
                    tal_sources_data[source.name] = df
                reference_data["tal_sources"] = tal_sources_data
            if profile.suppression.enabled:
                suppression_sources_data: dict[str, pd.DataFrame] = {}
                for source in profile.suppression.sources:
                    df = read_sheet_as_dataframe(source.file_path, source.sheet_name)
                    required_cols = []
                    if profile.suppression.check_domain:
                        required_cols.append(source.domain_column)
                    if profile.suppression.check_company_name:
                        required_cols.append(source.company_column)
                    if profile.suppression.check_email:
                        required_cols.append(source.email_column)
                    if required_cols:
                        require_columns(df, required_cols, f"{source.file_path} [{source.sheet_name}]")
                    suppression_sources_data[source.name] = df
                reference_data["suppression_sources"] = suppression_sources_data
            if profile.dedupe_list.enabled:
                dedupe_sources_data: dict[str, pd.DataFrame] = {}
                for source in profile.dedupe_list.sources:
                    df = read_sheet_as_dataframe(source.file_path, source.sheet_name)
                    require_columns(df, [source.email_column], f"{source.file_path} [{source.sheet_name}]")
                    dedupe_sources_data[source.name] = df
                reference_data["dedupe_sources"] = dedupe_sources_data

            alias_groups = load_alias_groups(get_aliases_path())
            result = run_pipeline(new_leads, profile, accumulated_leads, reference_data, alias_groups)
            if complex_review:
                merge_complex_account_review(result, complex_review)

            st.session_state["run_new_leads"] = new_leads
            st.session_state["run_result"] = result
            st.session_state["run_result_for"] = _run_identity
    except Exception as exc:
        render_error(exc)

if "run_result" in st.session_state:
    new_leads = st.session_state["run_new_leads"]
    result = st.session_state["run_result"]

    st.subheader("Summary")
    st.write(f"{len(new_leads)} in → {len(result.valid_indices)} valid, "
             f"{len(result.refund_reasons)} refunded, {len(result.review_reasons)} needs review")

    _completed_checks = [
        label for label, on in [
            ("Duplicate", profile.duplicate.enabled), ("Leadcap", profile.leadcap.enabled),
            ("Exclusion", profile.exclusion.enabled), ("TAL", profile.tal.enabled),
            ("Suppression", profile.suppression.enabled), ("Dedupe list", profile.dedupe_list.enabled),
        ] if on
    ]
    if profile.complex_account.enabled:
        _completed_checks += ["Complex Account: Capture Date", "Complex Account: Email Opt-in"]
        if profile.complex_account.specifications_path:
            _completed_checks.append("Complex Account: Asset URL match")
    if _completed_checks:
        st.caption("✅ " + "  ·  ✅ ".join(_completed_checks) + " — all completed")

    approved_refund_indices: list[int] = []
    if result.refund_reasons:
        st.subheader("Refund Reasons")
        st.caption("Auto-flagged for refund. Tick any that should actually be treated as valid — "
                   "those move to the Accumulated Report and Lead Template alongside the leads "
                   "already recognized as valid. Anything left unticked stays refund-only.")
        fm = profile.field_mapping
        refund_indices = list(result.refund_reasons.keys())

        # Streamlit forbids writing a data_editor's own widget key via
        # session_state directly, and once a key's per-cell edits exist it
        # ignores a fresh default passed through `data=` — so "select all"
        # instead bumps a nonce to force a brand-new, never-before-seen
        # widget key, which Streamlit hydrates fresh from refund_table
        # (built with the sticky "all approved" default below).
        st.session_state.setdefault("refund_editor_nonce", 0)
        st.session_state.setdefault("refund_all_approved_default", False)
        if st.button("Select all as valid", key="refund_select_all"):
            st.session_state["refund_all_approved_default"] = True
            st.session_state["refund_editor_nonce"] += 1
            st.rerun()

        refund_table = pd.DataFrame([
            {
                "Approve as valid": st.session_state["refund_all_approved_default"],
                "Row": idx + 2,
                "Email": new_leads.loc[idx].get(fm.email, ""),
                "Company": new_leads.loc[idx].get(fm.company, ""),
                "CID": new_leads.loc[idx].get(fm.cid, ""),
                "Reason": result.refund_reasons[idx],
            }
            for idx in refund_indices
        ])
        edited_refund_table = st.data_editor(
            refund_table,
            key=f"refund_editor_{st.session_state['refund_editor_nonce']}",
            hide_index=True,
            use_container_width=True,
            disabled=["Row", "Email", "Company", "CID", "Reason"],
            column_config={"Approve as valid": st.column_config.CheckboxColumn(required=True)},
        )
        approved_refund_indices = [
            idx for idx, approved in zip(refund_indices, edited_refund_table["Approve as valid"]) if approved
        ]

    if result.review_reasons:
        st.subheader("Needs Review")
        fm = profile.field_mapping
        for idx, details in list(result.review_reasons.items()):
            lead = new_leads.loc[idx]
            name = f"{lead.get(fm.first_name, '')} {lead.get(fm.last_name, '')}".strip()
            email = lead.get(fm.email, "")
            company = lead.get(fm.company, "")
            cid = lead.get(fm.cid, "")
            with st.expander(
                f"Excel row {idx + 2}: {name or '(no name)'} · {email or '(no email)'} "
                f"· {company or '(no company)'} · CID {cid or '?'}"
            ):
                st.caption(f"📧 {email}  |  🏢 {company}  |  🆔 CID {cid}")
                for detail in details:
                    st.markdown(f"**{detail}**" + (f" — {detail.score:.0f}% similar" if detail.score is not None else ""))
                    if detail.lead_value or detail.candidate_value:
                        comp1, comp2 = st.columns(2)
                        comp1.text_input("This lead's value", detail.lead_value, disabled=True, key=f"lead_val_{idx}_{detail.check}")
                        comp2.text_input(
                            f"Compared against ({detail.candidate_context})" if detail.candidate_context else "Compared against",
                            detail.candidate_value, disabled=True, key=f"cand_val_{idx}_{detail.check}",
                        )
                col1, col2 = st.columns(2)
                if col1.button("Approve as valid", key=f"approve_{idx}", use_container_width=True):
                    result.valid_indices.append(idx)
                    del result.review_reasons[idx]
                    st.rerun()
                if col2.button("Mark as refund", key=f"refund_{idx}", use_container_width=True):
                    result.refund_reasons[idx] = "; ".join(str(d) for d in details)
                    del result.review_reasons[idx]
                    st.rerun()

    final_valid_indices, final_refund_reasons = apply_refund_overrides(result, approved_refund_indices)
    final_refund_indices = list(final_refund_reasons.keys())

    # A shared default Lead Template path isn't required when every tab
    # routes to its own separate file — gating on lead_template_path alone
    # would wrongly skip the whole Lead Template step (and its Jira link)
    # for a client whose CID groups each go to a completely different file.
    lead_template_configured = profile.client_mode == "Lead QA" and (
        (profile.lead_template_multi_tab and profile.lead_template_tabs)
        or (not profile.lead_template_multi_tab and profile.lead_template_path)
    )

    if (result.refund_reasons or result.valid_indices) and not result.review_reasons:
        st.caption(f"On Finalize: {len(final_valid_indices)} lead(s) → Accumulated Report"
                   + (" + Lead Template" if lead_template_configured else "")
                   + f", {len(final_refund_indices)} lead(s) → Refund tab only."
                   + (" Complex Account: column filling runs first and shows a preview — nothing is "
                      "written until you click Confirm & Write." if profile.complex_account.enabled else ""))

    def _finalize_write(valid_leads_df, refund_leads_df, refund_reasons):
        """Backs up, writes valid_leads_df/refund_leads_df to the Accumulated
        Report (and valid_leads_df to the Lead Template(s) if configured),
        and returns (unmatched_headers, lead_template_links_used). Shared by
        both the normal single-step Finalize and the Complex Account
        fill-then-write flow — the two differ only in which DataFrame they
        pass in as valid_leads_df (raw vs. column-filled)."""
        backup_path = backup_file(profile.accumulated_report_path)
        st.info(f"Backed up Accumulated Report to {backup_path}")

        # A real date, not text — so Excel stores/filters it as a date. The
        # dd-mmm-yy display comes from the cell's number format (set in
        # append_leads), not from pre-formatting this into a string.
        run_date = datetime.date.today()
        unmatched_headers: set[str] = set()
        if not valid_leads_df.empty:
            unmatched_headers.update(append_leads(
                profile.accumulated_report_path, profile.accumulated_tab_name,
                valid_leads_df, profile.field_mapping, run_date,
                target_field_mapping=profile.accumulated_field_mapping))
        if not refund_leads_df.empty:
            unmatched_headers.update(append_leads(
                profile.accumulated_report_path, profile.refund_tab_name,
                refund_leads_df, profile.field_mapping, run_date,
                reasons=refund_reasons, target_field_mapping=profile.accumulated_field_mapping))

        # file_path -> SharePoint link for every Lead Template file this run actually
        # wrote to — a multi-tab client can route different CIDs to entirely different
        # workbooks, each with its own link, so this can't be a single value.
        lead_template_links_used: dict[str, str] = {}
        if lead_template_configured and not valid_leads_df.empty:
            _tmpl_fm = profile.lead_template_field_mapping
            _tmpl_expected = [v for v in [
                _tmpl_fm.email, _tmpl_fm.first_name, _tmpl_fm.last_name, _tmpl_fm.company, _tmpl_fm.cid,
            ] if v] if _tmpl_fm else None
            # Highlight this run's newly added rows in the Lead Report — only
            # for plain Lead QA clients, never Complex Account, per design.
            _tmpl_highlight = (
                "C6E0B4" if profile.client_mode == "Lead QA" and not profile.complex_account.enabled else None
            )

            if profile.lead_template_multi_tab:
                groups, unmatched = route_leads_by_cid(
                    valid_leads_df, profile.field_mapping.cid, profile.lead_template_tabs,
                    default_file_path=profile.lead_template_path)
                _tab_link_by_file = {
                    (tab.file_path or profile.lead_template_path): (tab.link or profile.lead_template_link)
                    for tab in profile.lead_template_tabs
                }
                _tmpl_files_used = set()
                for (_tmpl_file_path, sheet_name), tab_leads in groups.items():
                    _tmpl_header_row = find_header_row(_tmpl_file_path, sheet_name, _tmpl_expected)
                    unmatched_headers.update(append_leads(
                        _tmpl_file_path, sheet_name,
                        tab_leads, profile.field_mapping, run_date,
                        target_field_mapping=_tmpl_fm, header_row=_tmpl_header_row,
                        clear_existing=profile.lead_template_clear_existing,
                        highlight_fill=_tmpl_highlight))
                    _tmpl_files_used.add(_tmpl_file_path)
                    lead_template_links_used[_tmpl_file_path] = _tab_link_by_file.get(
                        _tmpl_file_path, profile.lead_template_link)
                if not unmatched.empty:
                    unmatched_cids = sorted(set(unmatched[profile.field_mapping.cid].astype(str).str.strip()))
                    st.warning(f"⚠️ {len(unmatched)} valid lead(s) had a CID with no matching Lead Template "
                               f"tab (CIDs: {', '.join(unmatched_cids)}) — skipped for the Lead Template "
                               "step, but still added to the Accumulated Report.")
                if groups:
                    st.info(f"Valid leads also appended to their matching tab(s) across "
                            f"{len(_tmpl_files_used)} Lead Template file(s): {', '.join(sorted(_tmpl_files_used))}")
            else:
                _tmpl_header_row = find_header_row(
                    profile.lead_template_path, profile.lead_template_sheet_name, _tmpl_expected)
                unmatched_headers.update(append_leads(
                    profile.lead_template_path, profile.lead_template_sheet_name,
                    valid_leads_df, profile.field_mapping, run_date,
                    target_field_mapping=_tmpl_fm, header_row=_tmpl_header_row,
                    clear_existing=profile.lead_template_clear_existing,
                    highlight_fill=_tmpl_highlight))
                st.info(f"Valid leads also appended to Lead Template at {profile.lead_template_path}")
                lead_template_links_used[profile.lead_template_path] = profile.lead_template_link

        if unmatched_headers:
            st.warning(
                "⚠️ These columns had no matching leadfile column and were left blank: "
                f"{', '.join(sorted(unmatched_headers))}. If the leadfile does have this data under a "
                "different name, rename the leadfile column (or its header) to something closer to the "
                "target column name and re-run."
            )
        st.success("Accumulated Report updated.")
        return lead_template_links_used

    def _finalize_jira_summary(total_leads_in, valid_count, refund_count, lead_template_links_used):
        if not profile.jira_ticket_key:
            return
        st.session_state["last_finalized_summary"] = {
            "client_name": client_name,
            "ticket_key": jira_client.extract_ticket_key(profile.jira_ticket_key),
            "reporter_name": profile.jira_reporter_name,
            "run_date_display": datetime.date.today().strftime("%d-%m-%y"),
            "leads_in": total_leads_in,
            "valid": valid_count,
            "refund": refund_count,
            "accumulated_report_path": profile.accumulated_report_path,
            "accumulated_report_link": profile.accumulated_report_link,
            # (file_path, link) for every Lead Template file this run wrote to —
            # a multi-tab client can have more than one.
            "lead_template_files": sorted(lead_template_links_used.items()),
        }

    if profile.complex_account.enabled:
        # Two-step Finalize for Complex Account clients: "fill columns" runs
        # the TAL/Installed-Technologies/Predictive-Buying-Stage/phone/date/
        # asset-URL rules on just the leads that ended up valid and shows a
        # preview — nothing is written to the Accumulated Report or Lead
        # Template until "Confirm & Write" afterward.
        if "complex_enriched_leads" not in st.session_state and not result.review_reasons and \
                st.button("Finalize (fill columns)"):
            try:
                with st.spinner("Filling in Complex Account columns..."):
                    tal_index = None
                    if profile.complex_account.tal_path:
                        tal_index = _cached_tal_index(
                            profile.complex_account.tal_path, os.path.getmtime(profile.complex_account.tal_path))

                    cid_it_maps: dict[str, dict[str, str]] = {}
                    for i, f in enumerate(complex_it_files):
                        cid = complex_it_file_cids.get(i)
                        if cid and cid in _leadfile_cids:
                            f.seek(0)
                            # A domain can appear on more than one row, one
                            # technology per row — combine them all rather than
                            # only keeping whichever row happened to load last.
                            cid_it_maps[cid] = load_domain_value_map(
                                f, "Domain", "Installed Technologies", aggregate=True)
                    cid_pbs_maps: dict[str, dict[str, str]] = {}
                    for i, f in enumerate(complex_pbs_files):
                        cid = complex_pbs_file_cids.get(i)
                        if cid and cid in _leadfile_cids:
                            f.seek(0)
                            # "No Active Signals" means there's nothing to
                            # report for that domain — leave the column blank
                            # instead of writing the label text itself.
                            cid_pbs_maps[cid] = load_domain_value_map(
                                f, "Targeted Accounts", "Predictive Buying Stage",
                                skip_values={"No Active Signals"})

                    enriched_valid, _ = apply_complex_account_rules(
                        new_leads.loc[final_valid_indices], field_mapping,
                        tal_index, cid_it_maps, cid_pbs_maps)
                    st.session_state["complex_enriched_leads"] = enriched_valid
                    st.session_state["complex_final_refund_reasons"] = final_refund_reasons
                    st.session_state["complex_final_refund_indices"] = final_refund_indices
                st.rerun()
            except Exception as exc:
                render_error(exc)

        if "complex_enriched_leads" in st.session_state:
            enriched_valid = st.session_state["complex_enriched_leads"]
            st.subheader("Preview: filled columns (nothing written yet)")
            _preview_cols = [c for c in [
                field_mapping.cid, field_mapping.email, field_mapping.first_name, field_mapping.last_name,
                ACCOUNT_ID_COLUMN, COMPANY_COLUMN, TOP_TOPICS_COLUMN, INSTALLED_TECH_COLUMN, PBS_COLUMN,
                CAPTURE_DATE_COLUMN, EMAIL_OPTIN_COLUMN, PHONE_COLUMN,
            ] if c and c in enriched_valid.columns]
            st.dataframe(enriched_valid[_preview_cols], hide_index=True)

            col_write, col_discard = st.columns(2)
            if col_write.button("Confirm & Write", type="primary", use_container_width=True):
                try:
                    with st.spinner("Writing to the Accumulated Report and Lead Template..."):
                        _refund_indices = st.session_state["complex_final_refund_indices"]
                        _refund_reasons = st.session_state["complex_final_refund_reasons"]
                        lead_template_links_used = _finalize_write(
                            enriched_valid, new_leads.loc[_refund_indices], _refund_reasons)
                        _finalize_jira_summary(
                            len(new_leads), len(enriched_valid), len(_refund_indices), lead_template_links_used)
                        for key in ("run_result", "run_new_leads", "complex_enriched_leads",
                                    "complex_final_refund_reasons", "complex_final_refund_indices"):
                            st.session_state.pop(key, None)
                    st.rerun()
                except Exception as exc:
                    render_error(exc)
            if col_discard.button("Discard and re-fill", use_container_width=True):
                for key in ("complex_enriched_leads", "complex_final_refund_reasons", "complex_final_refund_indices"):
                    st.session_state.pop(key, None)
                st.rerun()
    elif not result.review_reasons and st.button("Finalize"):
        try:
            with st.spinner("Writing to the Accumulated Report and Lead Template..."):
                valid_leads_df = new_leads.loc[final_valid_indices]
                refund_leads_df = new_leads.loc[final_refund_indices]
                lead_template_links_used = _finalize_write(valid_leads_df, refund_leads_df, final_refund_reasons)
                _finalize_jira_summary(
                    len(new_leads), len(final_valid_indices), len(final_refund_indices), lead_template_links_used)
                del st.session_state["run_result"]
                del st.session_state["run_new_leads"]
        except Exception as exc:
            render_error(exc)

_just_posted_ticket = st.session_state.pop("jira_last_posted_ticket", None)
if _just_posted_ticket:
    # A plain session_state flag, not st.success() directly at post time —
    # the post handler below calls st.rerun() right after posting (so a
    # retry-only click never re-posts the comment), and Streamlit discards
    # anything shown just before a rerun before the user ever sees it.
    st.success(f"Posted to {_just_posted_ticket}.")

_pending_summary = st.session_state.get("last_finalized_summary")
if _pending_summary and _pending_summary["client_name"] == client_name:
    st.divider()
    st.subheader("Post to Jira")
    st.caption("Nothing is sent until you click Post below — review (and edit) everything first.")

    _greeting = f"Hi {_pending_summary['reporter_name']}," if _pending_summary["reporter_name"] else "Hi,"
    _default_opening = (
        f"{_greeting}\n"
        f"PFB summary for the Lead QA dated {_pending_summary['run_date_display']}. "
        f"Also, PFB the links for the relevant files."
    )
    st.text_area("Opening message", _default_opening, key="jira_comment_opening", height=140)

    _lead_template_files = _pending_summary["lead_template_files"]
    _available_links = [("Accumulated File", _pending_summary["accumulated_report_path"],
                          _pending_summary["accumulated_report_link"])]
    for _tmpl_path, _tmpl_link in _lead_template_files:
        # More than one Lead Template file used this run (per-CID routing) —
        # disambiguate labels so each checkbox/link is identifiable.
        _label = "Lead Report" if len(_lead_template_files) == 1 else f"Lead Report — {_tmpl_path}"
        _available_links.append((_label, _tmpl_path, _tmpl_link))

    st.caption("File links to include (a configured SharePoint link is used when set, otherwise a local "
               "file path that only opens on a machine where that exact path exists):")
    _selected_links = []
    for _label, _path, _link in _available_links:
        if st.checkbox(f"{_label} — {_link or _path}", value=True, key=f"jira_link_{_label}"):
            _selected_links.append((_label, _link or jira_client.path_to_link_href(_path)))

    _pacing_df = None
    _pacing_path = _pending_summary["accumulated_report_path"]
    _pacing_stale = True
    try:
        with st.spinner("Recalculating Pacing Overview..."):
            _recalculated_path = recalculate_workbook(_pacing_path)
        _pacing_stale = _recalculated_path == _pacing_path
        try:
            _pacing_df = read_pacing_overview_table(_recalculated_path)
        finally:
            if _recalculated_path != _pacing_path:
                shutil.rmtree(os.path.dirname(_recalculated_path), ignore_errors=True)
    except Exception:
        _pacing_df = None
    _include_pacing = False
    if _pacing_df is not None and not _pacing_df.empty:
        _include_pacing = st.checkbox("Include Pacing Overview table", value=True, key="jira_include_pacing")
        if _include_pacing:
            if _pacing_stale:
                st.caption("⚠️ Couldn't recalculate via Excel (not installed, or the attempt failed/timed "
                           "out) — showing the file's last-saved values, which may not reflect this run's "
                           "leads yet if any of these columns are formulas.")
            st.dataframe(_pacing_df, hide_index=True)

    st.text_area("Closing message", "Thanks", key="jira_comment_closing", height=60)

    st.caption("Optional attachment (uploaded after the comment posts):")
    _attachment_file = st.file_uploader("Attach a file", key="jira_attachment_upload")
    if _attachment_file is not None:
        st.session_state["jira_attachment_bytes"] = _attachment_file.getvalue()
        st.session_state["jira_attachment_name"] = _attachment_file.name

    # Rendered from session_state (not just inline in the click handler
    # below) so a failed attachment stays visible across reruns — Streamlit
    # discards anything shown right before a rerun, and the widgets above
    # are already drawn with the pre-click state by the time the click
    # handler below could react to it, so both the error banner and the
    # button's own label need to come from state that survives the rerun.
    _prior_errors = st.session_state.get("jira_attachment_errors", {})
    for _name, _error in _prior_errors.items():
        st.error(f"Attachment \"{_name}\" failed to upload: {_error}")

    _has_pending_attachment_errors = bool(_prior_errors)
    _post_label = (
        f"🔁 Retry failed attachment(s) for {_pending_summary['ticket_key']}"
        if _has_pending_attachment_errors
        else f"📋 Post summary to {_pending_summary['ticket_key']}"
    )

    if st.button(_post_label, key="jira_post_button"):
        jira_settings = get_jira_settings()
        if not all([jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"]]):
            st.error("Set up your Jira account (site URL, email, API token) in Client Setup first.")
        else:
            try:
                if not _has_pending_attachment_errors:
                    adf_body = jira_client.build_comment_body(
                        opening_text=st.session_state["jira_comment_opening"],
                        closing_text=st.session_state["jira_comment_closing"],
                        file_links=_selected_links,
                        table_headers=list(_pacing_df.columns) if _include_pacing and _pacing_df is not None else None,
                        table_rows=_pacing_df.values.tolist() if _include_pacing and _pacing_df is not None else None,
                    )
                    jira_client.post_comment_body(
                        jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"],
                        _pending_summary["ticket_key"], adf_body,
                    )

                # Only an attachment that failed last time (or, on a fresh
                # post, any attachment provided at all) gets (re-)uploaded —
                # never repost the comment itself on a retry.
                attachment_errors = {}

                _file_bytes = st.session_state.get("jira_attachment_bytes")
                _file_name = st.session_state.get("jira_attachment_name")
                if _file_bytes is not None and (not _has_pending_attachment_errors or _file_name in _prior_errors):
                    try:
                        jira_client.upload_attachment(
                            jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"],
                            _pending_summary["ticket_key"], _file_name, _file_bytes,
                        )
                    except JiraError as exc:
                        attachment_errors[_file_name] = str(exc)

                if attachment_errors:
                    st.session_state["jira_attachment_errors"] = attachment_errors
                else:
                    st.session_state.pop("jira_attachment_errors", None)
                    st.session_state.pop("jira_attachment_bytes", None)
                    st.session_state.pop("jira_attachment_name", None)
                    del st.session_state["last_finalized_summary"]
                if not _has_pending_attachment_errors:
                    st.session_state["jira_last_posted_ticket"] = _pending_summary["ticket_key"]
                st.rerun()
            except JiraError as exc:
                st.error(f"Jira rejected the request: {exc}")
            except requests.RequestException as exc:
                st.error(f"Couldn't reach Jira: {exc}")
    if st.button("Dismiss", key="jira_dismiss_button"):
        del st.session_state["last_finalized_summary"]
        st.session_state.pop("jira_attachment_errors", None)
        st.session_state.pop("jira_attachment_bytes", None)
        st.session_state.pop("jira_attachment_name", None)
        st.rerun()
