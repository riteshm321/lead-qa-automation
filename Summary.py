import streamlit as st

st.set_page_config(page_title="Lead QA Automation", page_icon="✅", layout="wide")
st.title("✅ Lead QA & Upload Automation")
st.write("Use the sidebar to open **🗂️ Client Setup** or **▶️ Run Check**.")
st.divider()
st.caption("Client Setup configures a client's checks, reference files, and mode once. "
           "Run Check uses that configuration against a new leads batch every time you run it.")
