# pages/2_Run_Check.py
import datetime

import pandas as pd
import streamlit as st

from core.aliases_path import ALIASES_PATH
from core.checks.leadcap import validate_purchased_report_cids
from core.excel_io import read_sheet_as_dataframe, append_leads, backup_file, require_columns
from core.matching import load_alias_groups, add_alias_pair
from core.models import FieldMapping
from core.pipeline import run_pipeline
from core.profile_store import list_profile_names, load_profile, save_profile

st.title("Run Check")

profile_names = list_profile_names()
if not profile_names:
    st.warning("No client profiles found. Create one on the Client Setup page first.")
    st.stop()

client_name = st.selectbox("Client", profile_names)
profile = load_profile(client_name)

new_leads_file = st.file_uploader("New Leads file", type=["xlsx"])

new_leads_df = None
new_leads_headers: list[str] = []
if new_leads_file:
    new_leads_df = pd.read_excel(new_leads_file)
    new_leads_headers = list(new_leads_df.columns)

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
        save_profile(profile)
        st.success("Column mapping saved for this client.")
        st.rerun()

purchased_reports: dict[str, pd.DataFrame] = {}
if profile.leadcap.enabled:
    st.subheader("Leadcap: Purchased Lead Report(s)")
    leadcap_required_cols = [profile.leadcap.purchased_report_cid_column, profile.leadcap.purchased_report_email_column]
    if profile.leadcap.check_company_name:
        leadcap_required_cols.append(profile.leadcap.purchased_report_company_column)
    if profile.leadcap.segmented:
        for segment in profile.leadcap.segments:
            uploaded = st.file_uploader(f"Purchased Lead Report for: {segment.name} — CID {', '.join(segment.cids)}",
                                         type=["csv"], key=f"purchased_{segment.name}")
            if uploaded:
                df = pd.read_csv(uploaded)
                try:
                    require_columns(df, leadcap_required_cols, segment.name)
                    unexpected = validate_purchased_report_cids(df, segment.cids, profile.leadcap.purchased_report_cid_column)
                    if unexpected:
                        st.warning(f"'{segment.name}' file contains unexpected CIDs {unexpected} — wrong file?")
                    purchased_reports[segment.name] = df
                except ValueError as exc:
                    st.error(str(exc))
    else:
        uploaded = st.file_uploader("Purchased Lead Report", type=["csv"], key="purchased_flat")
        if uploaded:
            df = pd.read_csv(uploaded)
            try:
                require_columns(df, leadcap_required_cols, "Purchased Lead Report")
                purchased_reports["_flat_"] = df
            except ValueError as exc:
                st.error(str(exc))

if st.button("Run Check") and new_leads_file:
    if not mapping_valid:
        st.error("Map the New Leads columns above before running the check.")
        st.stop()
    try:
        new_leads = new_leads_df
        accumulated_leads = read_sheet_as_dataframe(profile.accumulated_report_path, profile.accumulated_tab_name)

        reference_data: dict = {"purchased_reports": purchased_reports}
        if profile.exclusion.enabled:
            exclusion_sources_data: dict[str, pd.DataFrame] = {}
            for source in profile.exclusion.sources:
                df = read_sheet_as_dataframe(source.file_path, source.sheet_name)
                require_columns(df, [source.domain_column], f"{source.file_path} [{source.sheet_name}]")
                exclusion_sources_data[source.name] = df
            reference_data["exclusion_sources"] = exclusion_sources_data
        if profile.tal.enabled:
            tal_sources_data: dict[str, pd.DataFrame] = {}
            for source in profile.tal.sources:
                df = read_sheet_as_dataframe(source.file_path, source.sheet_name)
                require_columns(df, [source.domain_column], f"{source.file_path} [{source.sheet_name}]")
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

        alias_groups = load_alias_groups(ALIASES_PATH)
        result = run_pipeline(new_leads, profile, accumulated_leads, reference_data, alias_groups)

        st.session_state["run_new_leads"] = new_leads
        st.session_state["run_result"] = result
    except Exception as exc:
        st.error(str(exc))

if "run_result" in st.session_state:
    new_leads = st.session_state["run_new_leads"]
    result = st.session_state["run_result"]

    st.subheader("Summary")
    st.write(f"{len(new_leads)} in → {len(result.valid_indices)} valid, "
             f"{len(result.refund_reasons)} refunded, {len(result.review_reasons)} needs review")

    if result.refund_reasons:
        st.subheader("Refund Reasons")
        st.dataframe(pd.DataFrame([
            {"row": idx, "reason": reason} for idx, reason in result.refund_reasons.items()
        ]))

    if result.review_reasons:
        st.subheader("Needs Review")
        for idx, reasons in list(result.review_reasons.items()):
            with st.expander(f"Row {idx}: {new_leads.loc[idx].to_dict()}"):
                st.write(reasons)
                col1, col2 = st.columns(2)
                if col1.button("Approve as valid", key=f"approve_{idx}"):
                    result.valid_indices.append(idx)
                    del result.review_reasons[idx]
                    st.rerun()
                if col2.button("Mark as refund", key=f"refund_{idx}"):
                    result.refund_reasons[idx] = "; ".join(reasons)
                    del result.review_reasons[idx]
                    st.rerun()

    if not result.review_reasons and st.button("Finalize"):
        backup_path = backup_file(profile.accumulated_report_path)
        st.info(f"Backed up Accumulated Report to {backup_path}")

        run_date = datetime.date.today().isoformat()
        if result.valid_indices:
            append_leads(profile.accumulated_report_path, profile.accumulated_tab_name,
                         new_leads.loc[result.valid_indices], profile.field_mapping, run_date)
        if result.refund_reasons:
            refund_indices = list(result.refund_reasons.keys())
            append_leads(profile.accumulated_report_path, profile.refund_tab_name,
                         new_leads.loc[refund_indices], profile.field_mapping, run_date,
                         reasons=result.refund_reasons)

        st.success("Accumulated Report updated.")
        del st.session_state["run_result"]
        del st.session_state["run_new_leads"]
