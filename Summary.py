import streamlit as st

from core.branding import configure_page


def _home() -> None:
    configure_page("Lead QA Automation")
    st.title("✅ Lead QA & Upload Automation")
    st.write("Use the sidebar to open **🗂️ Client Setup** or **▶️ Run Check**.")
    st.divider()
    st.caption("Client Setup configures a client's checks, reference files, and mode once. "
               "Run Check uses that configuration against a new leads batch every time you run it.")


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
        st.Page(_home, title="Home", icon="✅", default=True),
        st.Page("pages/1_Client_Setup.py", title="Client Setup", icon="🗂️"),
        st.Page("pages/2_Run_Check.py", title="Run Check", icon="▶️"),
        st.Page("pages/3_Settings.py", title="Settings", icon="⚙️"),
        st.Page("pages/4_Activity_Log.py", title="Activity Log", icon="📊"),
        st.Page("pages/5_Box_Tracker.py", title="Box Tracker", icon="📦"),
        st.Page("pages/6_Fuzzy_Match.py", title="Fuzzy Match", icon="🔍"),
    ],
    "Upload Tools": [
        st.Page("pages/7_Convertr.py", title="Convertr", icon="🔗"),
        st.Page("pages/8_Enhancio.py", title="Enhancio", icon="🔗"),
    ],
})
pg.run()
