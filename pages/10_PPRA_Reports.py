import hashlib

import requests
import streamlit as st

from core import jira_client
from core.app_settings import get_jira_settings
from core.branding import configure_page
from core.errors import render_error, render_problem
from core.jira_client import JiraError
from core.ppra import engine
from core.ppra.detect import REPORT_TYPES, map_report_type
from core.ppra.rules import RULES
from core.ui_components import render_stepper

_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_STEPS = ["Ticket", "Deck", "Scan", "Format", "Download", "Post"]

configure_page("PPRA Reports")
st.title(":material/slideshow: PPRA Reports")
st.caption("Format a raw Program Performance Report the way the CRS checklist asks, fill the Thank You page "
           "from the Jira ticket, then post the deck back to the ticket.")


def _ticket_state(ticket_key: str) -> dict:
    # Everything for one ticket lives under its key, so switching tickets in
    # the same session never mixes one ticket's deck with another's.
    return st.session_state.setdefault("ppra_tickets", {}).setdefault(ticket_key, {})


def _reset_after_deck(state: dict) -> None:
    for key in ("scan", "scan_type", "formatted", "change_log", "attention", "downloaded", "posted"):
        state.pop(key, None)


def _set_deck(state: dict, name: str, data: bytes) -> None:
    digest = hashlib.sha1(data).hexdigest()
    if state.get("deck_digest") == digest:
        return
    _reset_after_deck(state)
    state.update(deck_name=name, deck_bytes=data, deck_digest=digest)
    try:
        state["detected_type"] = engine.detect_report_type(data)
    except Exception:  # noqa: BLE001 - an unreadable deck is reported when it is scanned
        state["detected_type"] = None


def _mark_downloaded(ticket_key: str) -> None:
    _ticket_state(ticket_key)["downloaded"] = True


def _current_step(state: dict) -> int:
    if not state:
        return 1
    if not state.get("deck_bytes"):
        return 2
    if not state.get("scan"):
        return 3
    if not state.get("formatted"):
        return 4
    if not state.get("downloaded"):
        return 5
    return 6


_jira = get_jira_settings()
_jira_ready = all([_jira["base_url"], _jira["email"], _jira["api_token"]])
if not _jira_ready:
    render_problem("Your Jira account isn't set up yet.",
                   "Add your Jira site URL, email and API token in Client Setup, then come back here.",
                   level="warning")

_active = st.session_state.get("ppra_active_ticket")
render_stepper(_STEPS, _current_step(_ticket_state(_active) if _active else {}))

# ---------------------------------------------------------------- 1. ticket
st.subheader("1. Jira ticket")
_col_key, _col_fetch = st.columns([4, 1], vertical_alignment="bottom")
_ticket_input = _col_key.text_input("Jira ticket", key="ppra_ticket_input", placeholder="TM-12345 or the ticket link")
if _col_fetch.button("Fetch ticket", icon=":material/download:", key="ppra_fetch_button",
                     disabled=not _jira_ready or not _ticket_input.strip(), use_container_width=True):
    _key = jira_client.extract_ticket_key(_ticket_input)
    try:
        with st.spinner(f"Fetching {_key}..."):
            _ticket = jira_client.fetch_ppra_ticket(_jira["base_url"], _jira["email"], _jira["api_token"], _key)
        _ticket_state(_key)["ticket"] = _ticket
        st.session_state["ppra_active_ticket"] = _key
        _active = _key
    except JiraError as exc:
        render_problem(f"Jira rejected the request: {exc}",
                       "Check the ticket key, and that your API token in Client Setup is still valid.")
    except requests.RequestException as exc:
        render_error(exc)

if not _active or "ticket" not in _ticket_state(_active):
    st.stop()

_state = _ticket_state(_active)
_ticket = _state["ticket"]
_reporter = _ticket.get("reporter") or {}
with st.container(border=True, key="ppra_ticket_card"):
    st.markdown(f"**{_active}** - {_ticket.get('summary') or '(no summary)'}")
    _c1, _c2, _c3 = st.columns(3)
    _c1.markdown(f"**Client**  \n{_ticket.get('client_name') or '-'}")
    _c1.markdown(f"**Reporter**  \n{_reporter.get('displayName') or '-'}")
    _c2.markdown(f"**PPRA Report Format**  \n{_ticket.get('report_format') or '-'}")
    _c2.markdown(f"**Products**  \n{', '.join(_ticket.get('products') or []) or '-'}")
    _c3.markdown(f"**Flight dates**  \n{_ticket.get('flight_start') or '?'} to {_ticket.get('flight_end') or '?'}")
    _owner = [_ticket.get("owner_name"), _ticket.get("owner_title"), _ticket.get("owner_email")]
    _c3.markdown("**Thank You page owner**  \n" + (" / ".join(x for x in _owner if x) or "-"))
    if not all(_owner):
        render_problem("The ticket is missing some Thank You Page Deck Owner details.",
                       "The Thank You page will be left as it is - fill it in by hand or update the ticket "
                       "and fetch it again.", level="warning")

# ---------------------------------------------------------------- 2. deck
st.subheader("2. Original deck")
_attachments = _ticket.get("attachments") or []
_sources = ["Upload a .pptx"] + (["Use a ticket attachment"] if _attachments else [])
_source = st.radio("Deck source", _sources, horizontal=True, key=f"ppra_source_{_active}")
if _source == "Upload a .pptx":
    _upload = st.file_uploader("Original deck", type=["pptx"], key=f"ppra_upload_{_active}")
    if _upload is not None:
        _set_deck(_state, _upload.name, _upload.getvalue())
else:
    _names = [a["filename"] for a in _attachments]
    _pick = st.selectbox("Ticket attachment", _names, key=f"ppra_attachment_{_active}", filter_mode=None)
    if st.button("Load attachment", icon=":material/attach_file:", key=f"ppra_load_attachment_{_active}"):
        _att = _attachments[_names.index(_pick)]
        try:
            with st.spinner(f"Downloading {_pick}..."):
                _data = jira_client.download_attachment(_jira["email"], _jira["api_token"], _att["content_url"])
            _set_deck(_state, _pick, _data)
        except JiraError as exc:
            render_problem(f"Couldn't download the attachment: {exc}", "Try uploading the deck instead.")
        except requests.RequestException as exc:
            render_error(exc)

if not _state.get("deck_bytes"):
    st.stop()
st.caption(f"Deck: {_state['deck_name']}")

# ---------------------------------------------------------------- 3. report type + scan
st.subheader("3. Report type and scan")
_from_ticket = map_report_type(_ticket.get("report_format"), _ticket.get("products"))
_default_type = _from_ticket or _state.get("detected_type")
_options = list(REPORT_TYPES)
_report_type = st.selectbox(
    "Report type", _options, index=_options.index(_default_type) if _default_type in _options else 0,
    key=f"ppra_report_type_{_active}", filter_mode=None,
)
if _from_ticket:
    st.caption(f"Pre-filled from the ticket's PPRA Report Format / Products ({_from_ticket}).")
elif _state.get("detected_type"):
    st.caption(f"Pre-filled from the deck's Flight Dates ({_state['detected_type']}).")
else:
    st.caption("Couldn't tell the report type from the ticket or the deck - pick it here.")

if st.button("Scan deck", icon=":material/search:", key=f"ppra_scan_button_{_active}"):
    try:
        _state["scan"] = engine.scan(_state["deck_bytes"], _report_type, _ticket)
        _state["scan_type"] = _report_type
        for _key in ("formatted", "change_log", "attention", "downloaded", "posted"):
            _state.pop(_key, None)
        for _rule in RULES:
            st.session_state[f"ppra_rule_{_active}_{_rule.id}"] = bool(_state["scan"].findings.get(_rule.id))
    except Exception as exc:  # noqa: BLE001 - not a readable .pptx, most likely
        render_error(exc)

_scan = _state.get("scan")
if not _scan:
    st.stop()
if _state.get("scan_type") != _report_type:
    render_problem("The report type changed since the scan.", "Scan again so the rules match it.", level="warning")
    st.stop()

for _rule in RULES:
    _findings = _scan.findings.get(_rule.id) or []
    with st.container(border=True, key=f"ppra_rule_card_{_rule.id}"):
        _left, _right = st.columns([6, 1], vertical_alignment="center")
        _badge = (f":blue-badge[:material/edit: Will change {len(_findings)}]" if _findings
                  else ":gray-badge[Not found - skipped]")
        _left.markdown(f"**{_rule.id}** {_rule.label} {_badge}")
        _right.toggle("Apply", key=f"ppra_rule_{_active}_{_rule.id}", disabled=not _findings)
        for _finding in _findings[:8]:
            _left.caption(f"{_finding.description}: {_finding.before} -> {_finding.after}")
        if len(_findings) > 8:
            _left.caption(f"...and {len(_findings) - 8} more.")
if _scan.attention:
    with st.expander(f"Needs your attention ({len(_scan.attention)})"):
        for _item in _scan.attention:
            st.markdown(f"- {_item}")

# ---------------------------------------------------------------- 4. format
st.subheader("4. Format")
_enabled = [r.id for r in RULES if st.session_state.get(f"ppra_rule_{_active}_{r.id}")]
if st.button("Format deck", type="primary", icon=":material/auto_fix_high:", key=f"ppra_format_button_{_active}",
             disabled=not _enabled):
    try:
        with st.spinner("Formatting..."):
            _out, _log, _attention = engine.format(_state["deck_bytes"], _report_type, _ticket, _enabled)
        _state.update(formatted=_out, change_log=_log, attention=_attention, downloaded=False, posted=False)
    except Exception as exc:  # noqa: BLE001
        render_error(exc)

if not _state.get("formatted"):
    st.stop()
with st.expander(f"Change log ({len(_state['change_log'])})", expanded=True):
    for _line in _state["change_log"]:
        st.markdown(f"- {_line}")
if _state["attention"]:
    with st.container(border=True, key="ppra_attention_card"):
        st.markdown(":orange-badge[:material/warning: Needs your attention]")
        for _item in _state["attention"]:
            st.markdown(f"- {_item}")

# ---------------------------------------------------------------- 5. download
st.subheader("5. Download")
st.download_button(
    "Download formatted deck", data=_state["formatted"], file_name=f"{_active} - Formatted.pptx",
    mime=_PPTX_MIME, icon=":material/download:", key=f"ppra_download_{_active}",
    on_click=_mark_downloaded, args=(_active,),
)
if not _state.get("downloaded"):
    st.caption("Download and check the deck before posting it to Jira.")

# ---------------------------------------------------------------- 6. post
st.subheader("6. Post to Jira")
_reporter_name = _reporter.get("displayName") or "there"
with st.container(border=True, key="ppra_comment_preview"):
    st.caption(f"Attaches {_active}.pptx, then posts:")
    st.text(jira_client.ppra_comment_preview(_reporter_name))
if st.button("Post to Jira", icon=":material/send:", key=f"ppra_post_button_{_active}",
             disabled=not _state.get("downloaded") or bool(_state.get("posted")) or not _jira_ready):
    try:
        with st.spinner("Posting to Jira..."):
            jira_client.post_ppra_deck(
                _jira["base_url"], _jira["email"], _jira["api_token"], _active, _state["formatted"],
                _reporter.get("accountId", ""), _reporter_name,
            )
        _state["posted"] = True
    except JiraError as exc:
        render_problem(f"Jira rejected the request: {exc}", "Check your Jira API token in Client Setup.")
    except requests.RequestException as exc:
        render_error(exc)
if _state.get("posted"):
    st.success(f"Posted {_active}.pptx and the comment to {_active}.", icon=":material/check_circle:")
