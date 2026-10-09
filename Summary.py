import streamlit as st

from core.branding import configure_page


def _home() -> None:
    configure_page("Lead QA Automation")
    st.title(":material/fact_check: Lead QA & Upload Automation")
    st.caption("Configure a client once, then QA and upload every new leads batch in a few clicks.")
    st.write("")
    col_setup, col_run = st.columns(2)
    with col_setup.container(border=True, key="ml_card_client_setup"):
        st.page_link("pages/1_Client_Setup.py", label="Client Setup", icon=":material/folder:")
        st.caption("Set up a client's checks, reference files, and mode once.")
    with col_run.container(border=True, key="ml_card_run_check"):
        st.page_link("pages/2_Run_Check.py", label="Run Check", icon=":material/play_arrow:")
        st.caption("Run that configuration against a new leads batch.")


# st.navigation() with a {section title: [st.Page, ...]} dict groups the
# sidebar into labeled sections -- Convertr and Enhancio (both "upload a
# verified leadfile to a vendor" tools) live under their own "Upload Tools"
# heading instead of blending into the rest of the page list. Each target
# script still calls configure_page() as its own first Streamlit command
# (set_page_config() et al) exactly like before -- st.navigation() itself
# only selects which page's code runs this rerun, so nothing about the
# individual pages changes, no need for pg.run()'s current page.
pg = st.navigation({
    "Lead QA": [
        st.Page(_home, title="Home", icon=":material/home:", default=True),
        st.Page("pages/1_Client_Setup.py", title="Client Setup", icon=":material/folder:"),
        st.Page("pages/2_Run_Check.py", title="Run Check", icon=":material/play_arrow:"),
        st.Page("pages/3_Settings.py", title="Settings", icon=":material/settings:"),
        st.Page("pages/4_Activity_Log.py", title="Activity Log", icon=":material/bar_chart:"),
        st.Page("pages/5_Box_Tracker.py", title="Box Tracker", icon=":material/inventory_2:"),
        st.Page("pages/6_Fuzzy_Match.py", title="Fuzzy Match", icon=":material/search:"),
    ],
    "Upload Tools": [
        st.Page("pages/7_Convertr.py", title="Convertr", icon=":material/link:"),
        st.Page("pages/8_Enhancio.py", title="Enhancio", icon=":material/link:"),
        st.Page("pages/9_Integrate.py", title="Integrate", icon=":material/link:"),
        st.Page("pages/10_PPRA_Reports.py", title="PPRA Reports", icon=":material/slideshow:"),
    ],
})
pg.run()
