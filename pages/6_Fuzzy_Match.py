# pages/6_Fuzzy_Match.py
import tempfile
from pathlib import Path

import streamlit as st

from core.branding import configure_page
from core.errors import render_error
from core.excel_io import read_leadfile
from core.fuzzy_match import compare_columns, apply_match_column_colors, MATCH_COLUMN

_current_user = configure_page("Fuzzy Match")
st.title("🔍 Fuzzy Match")
st.caption(
    "Scores how closely two columns in the same file match (e.g. the leadfile's own Job Title "
    "against a LinkedIn-derived Job Title), so you can review weak matches before sending the file "
    "to the client. Not tied to a specific client — usable for anyone."
)

uploaded = st.file_uploader("File to check", type=["xlsx", "csv"])

if uploaded:
    try:
        df = read_leadfile(uploaded)
    except Exception as exc:
        render_error(exc)
        st.stop()

    headers = list(df.columns)
    col_a, col_b = st.columns(2)
    column_a = col_a.selectbox("Column A (e.g. Job Title)", headers, index=0)
    column_b = col_b.selectbox("Column B (e.g. LinkedIn Job Title)", headers, index=min(1, len(headers) - 1))

    if st.button("Run comparison", type="primary"):
        result_df = compare_columns(df, column_a, column_b)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = str(Path(tmp_dir) / "fuzzy_match_output.xlsx")
            result_df.to_excel(tmp_path, index=False)
            apply_match_column_colors(tmp_path)
            output_bytes = Path(tmp_path).read_bytes()

        st.session_state["fuzzy_match_output"] = output_bytes
        st.success(f"Compared {len(result_df)} row(s). Green ≥90%, yellow ≥75%, red below.")
        st.dataframe(result_df[[column_a, column_b, MATCH_COLUMN]], hide_index=True)

if st.session_state.get("fuzzy_match_output"):
    st.download_button(
        "Download result",
        data=st.session_state["fuzzy_match_output"],
        file_name="fuzzy_match_output.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
