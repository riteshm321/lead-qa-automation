# pages/2_Run_Check.py
import datetime

import pandas as pd
import streamlit as st

from core.aliases_path import ALIASES_PATH
from core.checks.leadcap import validate_purchased_report_cids
from core.excel_io import read_sheet_as_dataframe, append_leads, backup_file, require_columns
from core.matching import load_alias_groups, add_alias_pair
from core.pipeline import run_pipeline
from core.profile_store import list_profile_names, load_profile

st.title("Run Check")

profile_names = list_profile_names()
if not profile_names:
    st.warning("No client profiles found. Create one on the Client Setup page first.")
    st.stop()

client_name = st.selectbox("Client", profile_names)
profile = load_profile(client_name)

new_leads_file = st.file_uploader("New Leads file", type=["xlsx"])

purchased_reports: dict[str, pd.DataFrame] = {}
if profile.leadcap.enabled:
    st.subheader("Leadcap: Purchased Lead Report(s)")
    if profile.leadcap.segmented:
        for segment in profile.leadcap.segments:
            uploaded = st.file_uploader(f"Purchased Lead Report for: {segment.name} — CID {', '.join(segment.cids)}",
                                         type=["csv"], key=f"purchased_{segment.name}")
            if uploaded:
                df = pd.read_csv(uploaded)
                try:
                    require_columns(df, [profile.leadcap.purchased_report_cid_column], segment.name)
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
                require_columns(df, [profile.leadcap.purchased_report_cid_column], "Purchased Lead Report")
                purchased_reports["_flat_"] = df
            except ValueError as exc:
                st.error(str(exc))

if st.button("Run Check") and new_leads_file:
    try:
        new_leads = pd.read_excel(new_leads_file)
        accumulated_leads = read_sheet_as_dataframe(profile.accumulated_report_path, "Accumulated")

        reference_data: dict = {"purchased_reports": purchased_reports}
        if profile.exclusion.enabled:
            exclusion_df = read_sheet_as_dataframe(profile.exclusion_path, profile.exclusion.sheet_name)
            require_columns(exclusion_df, [profile.exclusion.domain_column], profile.exclusion_path)
            reference_data["exclusion_df"] = exclusion_df
        if profile.tal.enabled:
            if profile.tal.segmented:
                tal_sheets = {}
                for seg in profile.tal.segments:
                    df = read_sheet_as_dataframe(profile.tal_path, seg.sheet_name)
                    require_columns(df, [profile.tal.domain_column], f"{profile.tal_path} [{seg.sheet_name}]")
                    tal_sheets[seg.sheet_name] = df
                reference_data["tal_sheets"] = tal_sheets
            else:
                df = read_sheet_as_dataframe(profile.tal_path, profile.tal.flat_sheet_name)
                require_columns(df, [profile.tal.domain_column], f"{profile.tal_path} [{profile.tal.flat_sheet_name}]")
                reference_data["tal_sheets"] = {profile.tal.flat_sheet_name: df}
        if profile.suppression.enabled:
            suppression_df = read_sheet_as_dataframe(profile.suppression_path, profile.suppression.sheet_name)
            reference_data["suppression_df"] = suppression_df
        if profile.dedupe_list.enabled:
            dedupe_df = read_sheet_as_dataframe(profile.dedupe_list_path, profile.dedupe_list.sheet_name)
            require_columns(dedupe_df, [profile.dedupe_list.email_column], profile.dedupe_list_path)
            reference_data["dedupe_df"] = dedupe_df

        alias_groups = load_alias_groups(ALIASES_PATH)
        result = run_pipeline(new_leads, profile, accumulated_leads, reference_data, alias_groups)

        st.session_state["run_new_leads"] = new_leads
        st.session_state["run_result"] = result
    except ValueError as exc:
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
            append_leads(profile.accumulated_report_path, "Accumulated",
                         new_leads.loc[result.valid_indices], profile.field_mapping, run_date)
        if result.refund_reasons:
            refund_indices = list(result.refund_reasons.keys())
            append_leads(profile.accumulated_report_path, "Refund",
                         new_leads.loc[refund_indices], profile.field_mapping, run_date,
                         reasons=result.refund_reasons)

        st.success("Accumulated Report updated.")
        del st.session_state["run_result"]
        del st.session_state["run_new_leads"]
