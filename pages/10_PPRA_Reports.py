import hashlib
import re

import requests
import streamlit as st

from core import jira_client
from core.app_settings import get_jira_settings
from core.branding import configure_page
from core.errors import render_error, render_problem
from core.jira_client import JiraError
from core.ppra import engine
from core.ppra.detect import CHANNELS, REPORT_TYPES, UNIT_BY_CHANNEL, map_report_type, report_channels
from core.ppra.rules import GROUP_OF_RULE, RULE_GROUPS, RULES, RULES_BY_ID, TEXT_CHANGE_RULES
from core.ui_components import render_empty_state, render_metric_cards, stepper_markdown

_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_STEPS = ["Ticket", "Deck", "Review", "Download", "Post"]
# Every key this page keeps in st.session_state (widgets included) starts
# with this prefix, so "Start a new report" clears the page in one sweep.
_PREFIX = "ppra_"
# Survives that sweep: bumping it gives every file uploader a fresh key, so
# the browser drops the files it was holding.
_NONCE_KEY = "ppra_nonce"
_GROUP_ICONS = {
    "pacing": "table_chart", "remove": "delete", "takeaways": "lightbulb", "links": "link", "cleanup": "tune",
}

configure_page("PPRA Reports")
st.title(":material/slideshow: PPRA Reports")
st.caption("Format a raw Program Performance Report the way the CRS checklist asks, fill the Thank You page "
           "from the Jira ticket, then post the deck back to the ticket.")
_stepper = st.empty()


# ---------------------------------------------------------------- state helpers

def _nonce() -> int:
    return st.session_state.get(_NONCE_KEY, 0)


def _start_new_report() -> None:
    nonce = _nonce()
    for key in [k for k in st.session_state if str(k).startswith(_PREFIX)]:
        del st.session_state[key]
    st.session_state[_NONCE_KEY] = nonce + 1
    st.session_state["ppra_ticket_input"] = ""  # set (not just dropped) so the browser clears the box too


def _ticket_state(ticket_key: str) -> dict:
    # Everything for one ticket lives under its key, so switching tickets in
    # the same session never mixes one ticket's deck with another's.
    return st.session_state.setdefault("ppra_tickets", {}).setdefault(ticket_key, {})


_AFTER_SCAN = ("formatted", "formatted_with", "change_log", "attention", "downloaded", "posted", "posted_name",
               "transitions", "status", "status_changed")


def _reset_after_deck(state: dict) -> None:
    for key in ("scan", "scan_type", *_AFTER_SCAN):
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
    if not state.get("ticket"):
        return 1
    if not state.get("deck_bytes"):
        return 2
    if not state.get("formatted"):
        return 3
    if not state.get("downloaded") and not state.get("has_final_upload"):
        return 4
    if not state.get("posted"):
        return 5
    return len(_STEPS) + 1  # all done


def _finish() -> None:
    """Draw the stepper for where the page ended up, then end the run."""
    active = st.session_state.get("ppra_active_ticket")
    _stepper.markdown(stepper_markdown(_STEPS, _current_step(_ticket_state(active) if active else {})))
    st.stop()


def _size(n_bytes: int) -> str:
    return f"{n_bytes / 1048576:.1f} MB" if n_bytes >= 1048576 else f"{max(1, round(n_bytes / 1024))} KB"


def _clip(text: str, limit: int = 110) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


_MD_SPECIAL_RE = re.compile(r"([\\$*~`\[\]_<>])")


def _md(text) -> str:
    """Deck and ticket text shown as markdown: escape what Streamlit would
    treat as formatting ($ starts LaTeX, * and ~ style, [ ] badges/links)."""
    return _MD_SPECIAL_RE.sub(r"\\\1", str(text))


def _rule_key(ticket_key: str, rule_id: str) -> str:
    return f"ppra_rule_{ticket_key}_{rule_id}"


def _group_key(ticket_key: str, group_id: str) -> str:
    return f"ppra_group_{ticket_key}_{group_id}"


def _enabled_rule_ids(ticket_key: str, scan) -> list[str]:
    """Found rules whose group is included and whose own toggle is on."""
    return [r.id for r in RULES if scan.findings.get(r.id)
            and st.session_state.get(_group_key(ticket_key, GROUP_OF_RULE[r.id]), True)
            and st.session_state.get(_rule_key(ticket_key, r.id), True)]


def _check_key(ticket_key: str, line: str) -> str:
    return f"ppra_check_{ticket_key}_{hashlib.sha1(line.encode('utf-8')).hexdigest()[:12]}"


def _render_checklist(ticket_key: str, lines: list[str]) -> None:
    """Before you post: one checkbox per manual action left in the deck."""
    with st.container(border=True, key="ppra_checklist"):
        done = sum(bool(st.session_state.get(_check_key(ticket_key, line))) for line in lines)
        if done == len(lines):
            st.markdown(":green[:material/check_circle: **Nothing left to check by hand**]")
        else:
            st.markdown(f":material/checklist: **Before you post** · {done} of {len(lines)} checked")
        for line in lines:
            st.checkbox(_md(line), key=_check_key(ticket_key, line))
        if lines:
            st.caption("Slide numbers are in the formatted deck.")


def _type_chips(report_type: str, from_ticket: str | None, detected: str | None) -> str:
    channels = report_channels(report_type)
    chips = [f":blue-badge[{c}: {UNIT_BY_CHANNEL[c]}]" for c in CHANNELS if c in channels]
    if from_ticket == report_type:
        chips.append(":gray-badge[:material/confirmation_number: From the ticket]")
    elif detected == report_type:
        chips.append(":gray-badge[:material/search: Detected in the deck]")
    elif from_ticket or detected:
        chips.append(":gray-badge[:material/edit: Changed by you]")
    else:
        chips.append(":orange-badge[:material/help: Not detected - check this]")
    if detected and detected != report_type:
        chips.append(f":orange-badge[:material/warning: Deck looks like {detected}]")
    return " ".join(chips)


# ---------------------------------------------------------------- 1. ticket

_jira = get_jira_settings()
_jira_ready = all([_jira["base_url"], _jira["email"], _jira["api_token"]])
if not _jira_ready:
    render_problem("Your Jira account isn't set up yet.",
                   "Add your Jira site URL, email and API token in Client Setup, then come back here.",
                   level="warning")

_active = st.session_state.get("ppra_active_ticket")

st.subheader("1. Jira ticket")
_col_key, _col_fetch = st.columns([4, 1], vertical_alignment="bottom")
_ticket_input = _col_key.text_input("Jira ticket", key="ppra_ticket_input", placeholder="TM-12345 or the ticket link")
if _col_fetch.button("Fetch ticket", icon=":material/download:", key="ppra_fetch_button",
                     disabled=not _jira_ready or not _ticket_input.strip(), use_container_width=True):
    _key = jira_client.extract_ticket_key(_ticket_input)
    try:
        with st.spinner(f"Fetching {_key}..."):
            _ticket = jira_client.fetch_ppra_ticket(_jira["base_url"], _jira["email"], _jira["api_token"], _key)
        _fetched_state = _ticket_state(_key)
        _fetched_state["ticket"] = _ticket
        # The Thank You page rule reads the ticket, so an old scan is stale.
        for _stale in ("scan", "scan_type", *_AFTER_SCAN):
            _fetched_state.pop(_stale, None)
        st.session_state["ppra_active_ticket"] = _key
        _active = _key
    except JiraError as exc:
        render_problem(f"Jira rejected the request: {exc}",
                       "Check the ticket key, and that your API token in Client Setup is still valid.")
    except requests.RequestException as exc:
        render_error(exc)

if not _active or "ticket" not in _ticket_state(_active):
    _finish()

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
    _upload = st.file_uploader("Original deck", type=["pptx"], key=f"ppra_upload_{_active}_{_nonce()}")
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
    _finish()
st.caption(f":material/slideshow: {_md(_state['deck_name'])} ({_size(len(_state['deck_bytes']))})")

# ---------------------------------------------------------------- 3. review

st.subheader("3. Review changes")
_from_ticket = map_report_type(_ticket.get("report_format"), _ticket.get("products"))
_detected = _state.get("detected_type")
_default_type = _from_ticket or _detected
_options = list(REPORT_TYPES)
_type_col, _chip_col = st.columns([2, 3], vertical_alignment="bottom")
_report_type = _type_col.selectbox(
    "Report type", _options, index=_options.index(_default_type) if _default_type in _options else 0,
    key=f"ppra_report_type_{_active}", filter_mode=None,
)
_chip_col.markdown(_type_chips(_report_type, _from_ticket, _detected))

# Scan as soon as there is a deck and a report type, and again whenever the
# type changes - every finding starts selected.
if not _state.get("scan") or _state.get("scan_type") != _report_type:
    try:
        with st.spinner("Scanning the deck..."):
            _new_scan = engine.scan(_state["deck_bytes"], _report_type, _ticket)
    except Exception as exc:  # noqa: BLE001 - not a readable .pptx, most likely
        render_error(exc)
        _finish()
    for _stale in _AFTER_SCAN:
        _state.pop(_stale, None)
    _state.update(scan=_new_scan, scan_type=_report_type)
    for _rule in RULES:
        st.session_state[_rule_key(_active, _rule.id)] = bool(_new_scan.findings.get(_rule.id))
    for _gid, _title, _ids in RULE_GROUPS:
        st.session_state[_group_key(_active, _gid)] = any(_new_scan.findings.get(r) for r in _ids)

_scan = _state["scan"]
_enabled = _enabled_rule_ids(_active, _scan)
_skipped = _scan.skipped_rule_ids()
# The checklist is about the deck that will be posted: the trial format the
# scan ran, then the real one once the deck is formatted.
_checklist = engine.checklist_lines(_state["attention"] if _state.get("formatted") else _scan.attention)
render_metric_cards([
    ("Changes to make", _scan.change_count(_enabled), "edit_note"),
    ("Slides to remove", len(_scan.slides_to_remove(_enabled)), "delete"),
    ("Before you post", len(_checklist), "checklist"),
    ("Skipped (not in this deck)", len(_skipped), "block"),
])
_render_checklist(_active, _checklist)

for _gid, _title, _ids in RULE_GROUPS:
    _items = sorted(((rid, f) for rid in _ids for f in _scan.findings.get(rid) or []),
                    key=lambda item: (item[1].slide_index, item[0]))
    if not _items:
        continue
    _head, _tick = st.columns([7, 1], vertical_alignment="top")
    _included = _tick.checkbox("Include", key=_group_key(_active, _gid))
    _count = (f"{len({f.slide_index for _r, f in _items})} slides" if _gid == "remove"
              else f"{len(_items)} change{'s' if len(_items) != 1 else ''}")
    with _head.expander(f"{_title} - {_count}", icon=f":material/{_GROUP_ICONS[_gid]}:"):
        for _rid, _finding in _items:
            _line = f"Slide {_finding.slide_index + 1} - {_md(_finding.short)}"
            _on = _included and st.session_state.get(_rule_key(_active, _rid), True)
            st.markdown(_line if _on else f"~~{_line}~~ :gray-badge[skipped]")
            if _rid in TEXT_CHANGE_RULES and (_finding.before or _finding.after):
                st.caption(f"{_md(_clip(_finding.before))} -> {_md(_clip(_finding.after))}")

with st.expander("Advanced: choose individual changes", icon=":material/tune:"):
    st.caption("Turn single rules off. A group's Include box has to be on as well for its rules to run.")
    for _gid, _title, _ids in RULE_GROUPS:
        _found = [rid for rid in _ids if _scan.findings.get(rid)]
        if not _found:
            continue
        st.markdown(f"**{_title}**")
        for _rid in _found:
            st.toggle(f"{RULES_BY_ID[_rid].label} ({len(_scan.findings[_rid])})", key=_rule_key(_active, _rid))

if _skipped:
    with st.expander(f"Skipped - not in this deck ({len(_skipped)})", icon=":material/block:"):
        st.markdown("\n".join(f"- {RULES_BY_ID[rid].label}" for rid in _skipped))

# A formatted deck made from a different selection is stale (unless it is
# already posted - then it is the record of what went to Jira).
_selection = (_report_type, tuple(_enabled))
if _state.get("formatted") and _state.get("formatted_with") != _selection and not _state.get("posted"):
    for _stale in ("formatted", "formatted_with", "change_log", "attention", "downloaded"):
        _state.pop(_stale, None)

if not _enabled:
    render_empty_state("Nothing selected to change.", "Tick Include on at least one group.", icon="block")
if st.button("Format deck", type="primary", icon=":material/auto_fix_high:", key=f"ppra_format_button_{_active}",
             disabled=not _enabled or bool(_state.get("posted"))):
    try:
        with st.spinner("Formatting..."):
            _out, _log, _attention = engine.format(_state["deck_bytes"], _report_type, _ticket, _enabled)
        _state.update(formatted=_out, formatted_with=_selection, change_log=_log, attention=_attention,
                      downloaded=False, posted=False)
    except Exception as exc:  # noqa: BLE001
        render_error(exc)

if not _state.get("formatted"):
    _finish()
st.success(f"Deck formatted: {len(_state['change_log'])} changes applied.", icon=":material/check_circle:")
with st.expander(f"What changed ({len(_state['change_log'])})", icon=":material/list:"):
    st.markdown("\n".join(f"- {_md(_line)}" for _line in _state["change_log"]) or "Nothing changed.")

# ---------------------------------------------------------------- 4. download

st.subheader("4. Download")
st.download_button(
    "Download formatted deck", data=_state["formatted"], file_name=f"{_active} - Formatted.pptx",
    mime=_PPTX_MIME, icon=":material/download:", key=f"ppra_download_{_active}",
    on_click=_mark_downloaded, args=(_active,),
)
if not _state.get("downloaded"):
    st.caption("Download and check the deck before posting it to Jira - or upload your own final deck in step 5.")

# ---------------------------------------------------------------- 5. post

st.subheader("5. Post to Jira")
_posted = bool(_state.get("posted"))
_reporter_name = _reporter.get("displayName") or "there"
with st.container(border=True, key="ppra_post_card"):
    _final = st.file_uploader(
        "Upload a different final deck (optional)", type=["pptx"], key=f"ppra_final_upload_{_active}_{_nonce()}",
        help="If you finished the deck by hand, upload that version here - it is posted instead of the "
             "tool's formatted deck.", disabled=_posted,
    )
    _state["has_final_upload"] = _final is not None
    if _final is not None:
        _post_bytes, _post_name = _final.getvalue(), _final.name
        _source_badge = ":blue-badge[:material/upload_file: Your upload]"
    else:
        _post_bytes, _post_name = _state["formatted"], f"{_active} - Formatted.pptx"
        _source_badge = ":gray-badge[:material/auto_fix_high: Formatted by this tool]"
    st.markdown(f":material/attach_file: **Will attach:** {_md(_post_name)} ({_size(len(_post_bytes))}) "
                f"as `{_active}.pptx` {_source_badge}")
    st.caption("Then posts this comment:")
    st.text(jira_client.ppra_comment_preview(_reporter_name))

_ready = bool(_state.get("downloaded")) or _final is not None
if not _ready:
    st.caption("Download the formatted deck first (step 4), or upload your final deck above.")
if st.button("Post to Jira", icon=":material/send:", key=f"ppra_post_button_{_active}",
             disabled=not _ready or _posted or not _jira_ready):
    try:
        with st.spinner("Posting to Jira..."):
            jira_client.post_ppra_deck(
                _jira["base_url"], _jira["email"], _jira["api_token"], _active, _post_bytes,
                _reporter.get("accountId", ""), _reporter_name,
            )
        _state.update(posted=True, posted_name=_post_name)
    except JiraError as exc:
        render_problem(f"Jira rejected the request: {exc}", "Check your Jira API token in Client Setup.")
    except requests.RequestException as exc:
        render_error(exc)

if not _state.get("posted"):
    _finish()
st.success(f"Posted {_state.get('posted_name')} as {_active}.pptx and the comment to {_active}.",
           icon=":material/check_circle:")

# ---------------------------------------------------------------- status + new report

with st.container(border=True, key="ppra_status_card"):
    st.markdown("**Change ticket status** :gray-badge[optional]")
    if "transitions" not in _state:
        try:
            with st.spinner("Loading the ticket's statuses..."):
                _state["status"] = jira_client.get_issue_status(
                    _jira["base_url"], _jira["email"], _jira["api_token"], _active)
                _state["transitions"] = jira_client.get_transitions(
                    _jira["base_url"], _jira["email"], _jira["api_token"], _active)
        except JiraError as exc:
            _state["transitions"] = None
            render_problem(f"Couldn't load the ticket's statuses: {exc}",
                           "Change the status in Jira instead, or try again.")
        except requests.RequestException as exc:
            _state["transitions"] = None
            render_error(exc)
    _transitions = _state.get("transitions")
    if _state.get("status_changed"):
        st.success(f"Status changed to {_state['status_changed']}.", icon=":material/check_circle:")
    if _transitions is None:
        if st.button("Try again", icon=":material/refresh:", key=f"ppra_transitions_retry_{_active}"):
            _state.pop("transitions", None)
            st.rerun()
    else:
        st.markdown(f"Current status: :blue-badge[{_state.get('status') or 'unknown'}]")
        if not _transitions:
            render_empty_state("No status changes are open to you on this ticket right now.", icon="block")
        else:
            _labels = [t["name"] if not t["to"] or t["to"] == t["name"] else f"{t['name']} -> {t['to']}"
                       for t in _transitions]
            _choice = st.selectbox("Move the ticket to", _labels, index=None, placeholder="Pick a status",
                                   key=f"ppra_transition_{_active}", filter_mode=None)
            if st.button("Change status", icon=":material/swap_horiz:", key=f"ppra_transition_button_{_active}",
                         disabled=_choice is None):
                _target = _transitions[_labels.index(_choice)]
                try:
                    with st.spinner("Changing the status..."):
                        jira_client.transition_issue(_jira["base_url"], _jira["email"], _jira["api_token"],
                                                     _active, _target["id"])
                    _state["status_changed"] = _target["to"] or _target["name"]
                    _state.pop("transitions", None)  # reload: the options depend on the new status
                    st.rerun()
                except JiraError as exc:
                    render_problem(f"Jira didn't change the status: {exc}",
                                   "The transition may need fields Jira only shows in its own screen - "
                                   "change it in Jira instead.")
                except requests.RequestException as exc:
                    render_error(exc)

st.button("Start a new report", type="primary" if _state.get("status_changed") else "secondary",
          icon=":material/restart_alt:", key="ppra_new_report_button", on_click=_start_new_report,
          help="Clears this page - ticket, deck, review choices and post result - for the next report.")
_finish()
