import os
import uuid

import streamlit as st

from core.errors import render_error
from core.excel_io import (
    list_sheet_names, read_sheet_as_dataframe, detect_cids_from_pacing_overview, guess_target_field_mapping,
    find_header_row, read_sheet_headers,
)
from core.app_settings import (
    get_clients_dir, get_convertr_account_credentials, save_convertr_account_credentials,
    get_enhancio_client_id,
)
from core.branding import configure_page
from core import convertr_client
from core.convertr_client import ConvertrError
from core import enhancio_client
from core.enhancio_client import EnhancioError
from core.file_browser import browse_for_file
from core.jira_client import extract_ticket_key
from core.models import (
    ClientProfile, DuplicateConfig, LeadcapConfig, LeadcapSegment,
    ExclusionConfig, TalConfig, ReferenceSource, SuppressionConfig, DedupeListConfig, FieldMapping,
    LeadTemplateTab, ComplexAccountConfig, BoxTrackerConfig, ConvertrConfig, ConvertrCampaignMapping,
    EnhancioConfig, EnhancioAllocationMapping, IntegrateConfig,
)
from core.profile_store import save_profile, load_profile, list_profile_names
from core.toast import show_pending_toast

configure_page("Client Setup")
show_pending_toast()
st.title("Client Setup")
st.caption("Shared team data location and Jira account credentials moved to the ⚙️ Settings page.")


def _path_input_with_browse(label: str, session_key: str, current_value: str, show_label: bool = True) -> str:
    # Label rendered above (not inline in the text_input) so both columns
    # start at the exact same vertical offset — keeps the Browse button
    # aligned with the input box regardless of label text/theme font metrics.
    if show_label:
        st.markdown(f"**{label}**")
    col1, col2 = st.columns([5, 1])
    # The button's click handling (and any session_state write) must run
    # before the text_input with the same key is instantiated below —
    # Streamlit forbids modifying a widget's session_state value after that
    # widget has already been created in the same script run. Writing the
    # `with col2:` block first achieves that while col1 (input) still
    # renders visually on the left, since column position on screen is
    # independent of the order these blocks execute in.
    with col2:
        if st.button("📂 Browse...", key=f"{session_key}_browse", use_container_width=True):
            chosen = browse_for_file()
            if chosen:
                st.session_state[session_key] = chosen
                st.rerun()
    with col1:
        value = st.text_input(label, value=current_value, key=session_key, label_visibility="collapsed")
    return value


def _tabs_to_state(tabs: list[LeadTemplateTab]) -> list[dict]:
    return [
        {"id": str(uuid.uuid4()), "sheet_name": t.sheet_name, "cids": ",".join(t.cids),
         "file_path": t.file_path, "link": t.link}
        for t in tabs
    ]


def _render_lead_template_tabs(template_path: str) -> list[LeadTemplateTab]:
    if not st.session_state["lead_template_tabs"]:
        st.caption("📭 No tabs configured yet — click **➕ Add Tab** below to create one.")
    if st.button("➕ Add Tab", key="lead_template_tabs_add"):
        st.session_state["lead_template_tabs"].append(
            {"id": str(uuid.uuid4()), "sheet_name": "", "cids": "", "file_path": "", "link": ""})

    result: list[LeadTemplateTab] = []
    remove_id = None
    for row in st.session_state["lead_template_tabs"]:
        row_id = row["id"]
        with st.container(border=True):
            row["file_path"] = _path_input_with_browse(
                "File for this tab (leave blank to use the Lead Template path above)",
                f"tmpl_tab_filepath_{row_id}", row.get("file_path", ""))
            effective_path = row["file_path"] or template_path
            sheet_options: list[str] = []
            if effective_path:
                try:
                    sheet_options = list_sheet_names(effective_path)
                except Exception:
                    sheet_options = []
            if sheet_options:
                idx = sheet_options.index(row["sheet_name"]) if row["sheet_name"] in sheet_options else 0
                row["sheet_name"] = st.selectbox("Tab (sheet) name", sheet_options, index=idx,
                                                  key=f"tmpl_tab_sheet_{row_id}")
            else:
                row["sheet_name"] = st.text_input(
                    "Tab (sheet) name (enter a valid file path above to pick from a list)",
                    value=row["sheet_name"], key=f"tmpl_tab_sheet_text_{row_id}")
            row["cids"] = st.text_input("CIDs routed to this tab (comma-separated)",
                                         value=row["cids"], key=f"tmpl_tab_cids_{row_id}")
            row["link"] = st.text_input(
                "SharePoint link for this tab's file (leave blank to use the Lead Template link above)",
                value=row.get("link", ""), key=f"tmpl_tab_link_{row_id}",
                placeholder="e.g. https://madlog.sharepoint.com/:x:/s/.../...",
            )
            if st.button("🗑️ Remove this tab", key=f"tmpl_tab_remove_{row_id}"):
                remove_id = row_id

        result.append(LeadTemplateTab(
            sheet_name=row["sheet_name"],
            cids=[c.strip() for c in row["cids"].split(",") if c.strip()],
            file_path=row["file_path"],
            link=row.get("link", ""),
        ))

    if remove_id is not None:
        st.session_state["lead_template_tabs"] = [r for r in st.session_state["lead_template_tabs"] if r["id"] != remove_id]
        st.rerun()

    return result


def _sources_to_state(sources: list[ReferenceSource]) -> list[dict]:
    return [
        {"id": str(uuid.uuid4()), "name": s.name, "file_path": s.file_path, "sheet_name": s.sheet_name,
         "cids": ",".join(s.cids), "domain_column": s.domain_column,
         "company_column": s.company_column, "email_column": s.email_column}
        for s in sources
    ]


@st.cache_data(show_spinner=False)
def _cached_sheet_columns(path: str, sheet_name: str, mtime: float) -> list[str]:
    # mtime must NOT be underscore-prefixed -- Streamlit excludes any
    # parameter named with a leading underscore from the cache key hash,
    # which would silently defeat the whole point of passing it in (to
    # invalidate the cache when the file changes on disk mid-session).
    # A TAL/Exclusion/Suppression/Dedupe source can be a large (500k+ row)
    # reference file per core.complex_account.load_tal_index's own
    # docstring -- this was being fully re-parsed via read_sheet_as_dataframe
    # on every rerun of the whole page (any widget interaction anywhere,
    # not just edits to this specific source row) purely to populate a
    # column-name dropdown, making the page seconds-to-tens-of-seconds
    # laggy per interaction. Same fix as _cached_sheet_df in
    # pages/2_Run_Check.py, applied to the exact same read call so the
    # column list is guaranteed identical to before, just no longer
    # redundantly recomputed.
    return list(read_sheet_as_dataframe(path, sheet_name).columns)


def _render_sources_section(
    section_key: str,
    label: str,
    check_domain: bool,
    check_company: bool,
    check_email: bool,
) -> list[ReferenceSource]:
    result: list[ReferenceSource] = []
    if not st.session_state[section_key]:
        st.caption(f"📭 No {label} sources configured yet — click **➕ Add {label} Source** below to create one.")
    if st.button(f"➕ Add {label} Source", key=f"{section_key}_add"):
        st.session_state[section_key].append({
            "id": str(uuid.uuid4()), "name": "", "file_path": "", "sheet_name": "", "cids": "",
            "domain_column": "Domain", "company_column": "Account Name", "email_column": "Email",
        })

    remove_id = None
    for src in st.session_state[section_key]:
        row_id = src["id"]
        path_key = f"{section_key}_path_{row_id}"

        with st.container(border=True):
            st.markdown(f"**📄 {label} Source: {src['name'] or '(unnamed)'}**")

            src["name"] = st.text_input("Name", value=src["name"], key=f"{section_key}_name_{row_id}")
            src["file_path"] = _path_input_with_browse("File path", path_key, src["file_path"], show_label=False)

            sheet_options: list[str] = []
            if src["file_path"]:
                try:
                    sheet_options = list_sheet_names(src["file_path"])
                except Exception as exc:
                    st.caption(f"File: {src['file_path']}")
                    render_error(exc)
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
                    header_options = _cached_sheet_columns(
                        src["file_path"], src["sheet_name"], os.path.getmtime(src["file_path"]))
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

            col_a, col_b, col_c = st.columns(3)
            if check_domain:
                with col_a:
                    src["domain_column"] = _column_picker("Domain column", "domain_column", "Domain")
            if check_company:
                with col_b:
                    src["company_column"] = _column_picker("Company column", "company_column", "Account Name")
            if check_email:
                with col_c:
                    src["email_column"] = _column_picker("Email column", "email_column", "Email")

            src["cids"] = st.text_input("CIDs this source applies to (comma-separated, blank = applies to all leads)",
                                         value=src["cids"], key=f"{section_key}_cids_{row_id}")

            if st.button("🗑️ Remove this source", key=f"{section_key}_remove_{row_id}"):
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


def _safe_read_template_headers(
    path: str, sheet_name: str, expected_headers: list | None = None
) -> tuple[list[str], Exception | None]:
    # Lead Templates sometimes have title/instruction rows above the real
    # header row, so headers aren't assumed to start at row 1. Returns the
    # exception (rather than swallowing it) so the caller can show the real
    # reason — e.g. the file being an undownloaded OneDrive placeholder —
    # instead of a misleading "enter a valid path" message.
    if not path or not sheet_name:
        return [], None
    try:
        header_row = find_header_row(path, sheet_name, expected_headers)
        return [h for h in read_sheet_headers(path, sheet_name, header_row) if h is not None], None
    except Exception as exc:
        return [], exc


_NO_MAPPING_OPTION = "(none — this file has no such column)"


def _render_target_field_mapping(label: str, key_prefix: str, headers: list[str]) -> FieldMapping | None:
    if not headers:
        return None
    st.caption(f"Map which {label} column corresponds to each field — needed if the header text "
               f"doesn't match the leadfile's own column names. Leave a field as \"{_NO_MAPPING_OPTION}\" "
               f"if this file doesn't have that column at all (e.g. no CID column) — it won't be populated.")

    options = [_NO_MAPPING_OPTION] + headers

    def _col(role_label: str, key: str) -> str:
        current = st.session_state.get(key, "")
        idx = options.index(current) if current in options else 0
        selected = st.selectbox(role_label, options, index=idx, key=key)
        return "" if selected == _NO_MAPPING_OPTION else selected

    email = _col("Email column", f"{key_prefix}_map_email")
    first_name = _col("First Name column", f"{key_prefix}_map_first")
    last_name = _col("Last Name column", f"{key_prefix}_map_last")
    company = _col("Company column", f"{key_prefix}_map_company")
    cid = _col("CID column", f"{key_prefix}_map_cid")
    if not any([email, first_name, last_name, company, cid]):
        # Every dropdown left at "No mapping" -- this whole section is
        # optional, so treat that the same as never having opened it
        # (None), not as an explicit "map every field to blank" that
        # then wins over the fallback this profile is supposed to use.
        return None
    return FieldMapping(email=email, first_name=first_name, last_name=last_name, company=company, cid=cid)


def _render_leadfile_column_mapping(key_prefix: str, existing: FieldMapping | None) -> FieldMapping | None:
    # Free-text (not a selectbox, unlike _render_target_field_mapping) --
    # this runs at Client Setup time, before any specific leadfile has been
    # uploaded, so there are no known headers to pick from. Leaving every
    # field blank means "fall back to this client's QA field_mapping",
    # handled by the caller page, not here.
    st.caption(
        "Which of the UPLOADED leadfile's own columns hold each field — lets this tool work standalone, "
        "without needing this client's QA field mapping (Run Check) configured at all. Leave every field "
        "blank to keep using the QA field mapping instead, if one exists."
    )
    existing = existing or FieldMapping(email="", first_name="", last_name="", company="", cid="")
    _col1, _col2 = st.columns(2)
    email = _col1.text_input("Email column", value=existing.email, key=f"{key_prefix}_lf_email")
    first_name = _col1.text_input("First Name column", value=existing.first_name, key=f"{key_prefix}_lf_first")
    last_name = _col1.text_input("Last Name column", value=existing.last_name, key=f"{key_prefix}_lf_last")
    company = _col2.text_input("Company column", value=existing.company, key=f"{key_prefix}_lf_company")
    cid = _col2.text_input("CID column", value=existing.cid, key=f"{key_prefix}_lf_cid")
    if not any([email, first_name, last_name, company, cid]):
        return None
    return FieldMapping(email=email, first_name=first_name, last_name=last_name, company=company, cid=cid)


def _render_paired_field_mapping(key_prefix: str, target_name: str, existing: dict[str, str]) -> dict[str, str]:
    # Two plain lists, paired by line position, instead of one delimited
    # line per mapping ("Column,Field" or "Column -> Field"). A real
    # leadfile column is often a verbatim survey/consent question that can
    # contain commas, arrows, or any other punctuation a delimiter might
    # pick -- no delimiter at all is the only scheme that can't be
    # misparsed by the leadfile's own text. Self-mapped fields (column name
    # == target name, the common case) just get typed once, at the same
    # line in both boxes -- never twice on one line, which is what
    # actually kept going wrong here.
    st.caption(
        f"Leadfile columns to send to {target_name}, one per line — don't include CID here, the "
        "uploaded row itself is kept and reused when writing Accumulated/Refund later, not anything "
        f"{target_name} echoes back:"
    )
    _cols_text = st.text_area(
        f"{target_name} leadfile columns", value="\n".join(existing.keys()),
        key=f"{key_prefix}_field_map_cols_input", label_visibility="collapsed", height=100)

    st.caption(
        f"The matching {target_name} field name for each column above — same order, one per line. Type "
        "the column name again on its own line when it's identical on both sides (the common case for a "
        "survey/consent question worded the same way on both ends):"
    )
    _targets_text = st.text_area(
        f"{target_name} field names", value="\n".join(existing.values()),
        key=f"{key_prefix}_field_map_targets_input", label_visibility="collapsed", height=100)

    _cols = [line.strip() for line in _cols_text.splitlines() if line.strip()]
    _targets = [line.strip() for line in _targets_text.splitlines() if line.strip()]

    if len(_cols) != len(_targets):
        st.error(
            f"Leadfile columns ({len(_cols)} line(s)) and {target_name} field names ({len(_targets)} "
            "line(s)) don't have the same number of lines — line N in one box has to be line N's match "
            "in the other. Keeping the previously saved mapping until these line up."
        )
        return dict(existing)

    mapping = dict(zip(_cols, _targets))
    if mapping:
        st.caption("Preview — this is exactly what will be sent:")
        st.dataframe(
            {"Leadfile column": list(mapping.keys()), f"{target_name} field": list(mapping.values())},
            hide_index=True, use_container_width=True,
        )
    return mapping


@st.cache_data(show_spinner=False)
def _cached_profile_names(clients_dir: str, dir_mtime: float) -> list[str]:
    # dir_mtime must NOT be underscore-prefixed -- Streamlit excludes any
    # parameter named with a leading underscore from the cache key hash.
    # list_profile_names() opens and JSON-parses every client profile in
    # the shared OneDrive clients folder to confirm each one really is a
    # profile -- re-scanning all of them (currently 15+) on every single
    # widget interaction, not just page navigation, was a real and growing
    # source of sluggishness as the client list grows. Keyed on the
    # directory's own mtime so a newly saved/removed profile still shows
    # up on the very next rerun.
    return list_profile_names(clients_dir)


def _clients_dir_mtime(clients_dir: str) -> float:
    try:
        return os.path.getmtime(clients_dir)
    except OSError:
        return 0.0


existing = _cached_profile_names(get_clients_dir(), _clients_dir_mtime(get_clients_dir()))
mode = st.radio("Mode", ["Create new client", "Edit existing client"])

@st.cache_data(show_spinner=False)
def _cached_load_profile(name: str, clients_dir: str, mtime: float):
    # mtime must NOT be underscore-prefixed -- see _cached_profile_names
    # above for why. Re-reading the same client's profile from the shared
    # OneDrive folder on every single widget interaction (not just when
    # the client selection actually changes) was another redundant read
    # on every rerun of this page.
    return load_profile(name, clients_dir)


def _profile_file_mtime(name: str, clients_dir: str) -> float:
    try:
        return os.path.getmtime(os.path.join(clients_dir, f"{name}.json"))
    except OSError:
        return 0.0


if mode == "Edit existing client" and existing:
    selected_name = st.selectbox("Client", existing)
    try:
        _clients_dir_now = get_clients_dir()
        profile = _cached_load_profile(
            selected_name, _clients_dir_now, _profile_file_mtime(selected_name, _clients_dir_now))
    except (TypeError, ValueError, OSError) as exc:
        # TypeError: an older-format profile whose fields no longer match
        # ClientProfile's dataclass. ValueError (json.JSONDecodeError is a
        # subclass)/OSError: the shared profile JSON was mid-write from
        # another machine when this read hit it, or a transient OneDrive
        # lock -- both real possibilities for a file under the shared
        # OneDrive clients folder, previously an unhandled crash here.
        st.error(f"Could not load the profile for '{selected_name}' — it may be in an older format, or the "
                 "file may have been mid-write on another machine (try again in a moment). If it keeps "
                 f"happening, delete and re-create it in Client Setup. (Technical detail: {exc})")
        st.stop()
else:
    selected_name = None
    profile = None

_profile_identity = f"{mode}::{selected_name or ''}"
if st.session_state.get("_loaded_sources_for") != _profile_identity:
    st.session_state["_loaded_sources_for"] = _profile_identity
    st.session_state["exclusion_sources"] = _sources_to_state(profile.exclusion.sources) if profile else []
    st.session_state["tal_sources"] = _sources_to_state(profile.tal.sources) if profile else []
    st.session_state["suppression_sources"] = _sources_to_state(profile.suppression.sources) if profile else []
    st.session_state["dedupe_sources"] = _sources_to_state(profile.dedupe_list.sources) if profile else []
    st.session_state["lead_template_tabs"] = _tabs_to_state(profile.lead_template_tabs) if profile else []
    st.session_state["accumulated_path_input"] = profile.accumulated_report_path if profile else ""
    st.session_state["lead_template_path_input"] = profile.lead_template_path if profile else ""
    st.session_state["leadcap_segments_text"] = (
        "\n".join(f"{', '.join(s.cids)} - {s.cap}" for s in profile.leadcap.segments) if profile else ""
    )
    # Force the file-identity-based mapping resets below to recompute fresh
    # for this profile, rather than reusing whatever file another profile
    # (or no profile) had loaded.
    st.session_state.pop("_acc_mapping_for", None)
    st.session_state.pop("_tmpl_mapping_for", None)

client_name = st.text_input("Client name", value=profile.name if profile else "")

st.divider()

tab_basics, tab_leadcap, tab_exclusion, tab_tal, tab_suppression, tab_dedupe, tab_complex = st.tabs([
    "🗂️ Basics", "🧮 Leadcap", "🚫 Exclusion", "🎯 TAL", "🔕 Suppression", "🧹 Dedupe & Duplicate",
    "🧩 Complex Account",
])

with tab_basics:
    with st.container(border=True):
        st.subheader("Reference Files")
        accumulated_path = _path_input_with_browse(
            "Accumulated Report path", "accumulated_path_input",
            profile.accumulated_report_path if profile else "")
        accumulated_report_link = st.text_input(
            "Accumulated Report SharePoint link (optional)",
            value=profile.accumulated_report_link if profile else "",
            placeholder="e.g. https://madlog.sharepoint.com/:x:/s/.../...",
            help="Used as the \"Accumulated File\" link when posting a summary to Jira, instead of a local "
                 "file path that only opens on your own machine. Leave blank to fall back to the local path.",
        )
        col_acc, col_ref = st.columns(2)
        with col_acc:
            accumulated_tab_name = st.text_input("Accumulated tab name",
                                                  value=profile.accumulated_tab_name if profile else "Accumulated")
        with col_ref:
            refund_tab_name = st.text_input("Refund tab name",
                                             value=profile.refund_tab_name if profile else "Refund")

        col_jira_ticket, col_jira_reporter = st.columns(2)
        with col_jira_ticket:
            jira_ticket_key = st.text_input(
                "Jira ticket key or link (optional)", value=profile.jira_ticket_key if profile else "",
                placeholder="e.g. PROJ-1234 or https://yourteam.atlassian.net/browse/PROJ-1234",
                help="Paste either the ticket key or the full link — either works. Enables a \"Post summary "
                     "to Jira\" button on Run Check after Finalize. Leave blank to skip. The same ticket "
                     "usually covers a whole campaign — come back here and update it if that ever changes.",
            )
        with col_jira_reporter:
            jira_reporter_name = st.text_input(
                "Jira reporter's name (optional)", value=profile.jira_reporter_name if profile else "",
                placeholder="e.g. Jane",
                help="Used for the \"Hi <name>\" greeting in the posted summary.",
            )

        accumulated_headers, accumulated_headers_error = _safe_read_template_headers(accumulated_path, accumulated_tab_name)

        # Reset the mapping dropdowns whenever the actual file/tab changes —
        # a keyed selectbox ignores a fresh `index=` on later reruns and just
        # keeps showing whatever's already in session_state, so switching files
        # without this explicit reset would leave stale selections on screen.
        _acc_file_identity = f"{accumulated_path}::{accumulated_tab_name}"
        if st.session_state.get("_acc_mapping_for") != _acc_file_identity:
            st.session_state["_acc_mapping_for"] = _acc_file_identity
            _acc_fm_match = (
                profile.accumulated_field_mapping
                if profile and profile.accumulated_report_path == accumulated_path
                and profile.accumulated_tab_name == accumulated_tab_name else None
            )
            _acc_guess = guess_target_field_mapping(accumulated_headers) if not _acc_fm_match else {}
            st.session_state["acc_map_email"] = _acc_fm_match.email if _acc_fm_match else _acc_guess.get("email", "")
            st.session_state["acc_map_first"] = _acc_fm_match.first_name if _acc_fm_match else _acc_guess.get("first_name", "")
            st.session_state["acc_map_last"] = _acc_fm_match.last_name if _acc_fm_match else _acc_guess.get("last_name", "")
            st.session_state["acc_map_company"] = _acc_fm_match.company if _acc_fm_match else _acc_guess.get("company", "")
            st.session_state["acc_map_cid"] = _acc_fm_match.cid if _acc_fm_match else _acc_guess.get("cid", "")

        accumulated_field_mapping_result = None
        with st.expander("🔗 Map Accumulated Report columns (optional)"):
            accumulated_field_mapping_result = _render_target_field_mapping(
                "Accumulated Report", "acc", accumulated_headers)
            if accumulated_headers_error is not None:
                st.error(f"Couldn't read '{accumulated_path}' [{accumulated_tab_name}]: {accumulated_headers_error}")
            elif not accumulated_headers:
                st.caption("Enter a valid Accumulated Report path and tab name above to map its columns.")

    with st.container(border=True):
        st.subheader("File Collation (optional)")
        st.caption(
            "Offers a \"collate multiple files into one New Leads file\" option on Run Check for this "
            "client. Not forced on — you can still upload an already-collated file directly on any given run."
        )
        collation_enabled = st.checkbox(
            "Enable file collation for this client",
            value=profile.collation_enabled if profile else False,
        )

    with st.container(border=True):
        st.subheader("Client Mode")
        _CLIENT_MODES = ["Lead QA", "Lead QA & Upload"]
        _mode_default = profile.client_mode if profile and profile.client_mode in _CLIENT_MODES else "Lead QA"
        client_mode = st.radio("Mode", _CLIENT_MODES, index=_CLIENT_MODES.index(_mode_default), horizontal=True)

        lead_template_path = ""
        lead_template_link = ""
        lead_template_sheet_name = ""
        lead_template_multi_tab = False
        lead_template_tabs_result: list[LeadTemplateTab] = []
        lead_template_field_mapping_result = None
        if client_mode == "Lead QA":
            lead_template_path = _path_input_with_browse(
                "Lead Template path", "lead_template_path_input",
                profile.lead_template_path if profile else "")
            st.caption("The default/shared Lead Template file. Leave this blank if every CID group below has "
                       "its own separate file — a shared default isn't required.")
            lead_template_link = st.text_input(
                "Lead Template SharePoint link (optional)",
                value=profile.lead_template_link if profile else "",
                placeholder="e.g. https://madlog.sharepoint.com/:x:/s/.../...",
                help="Used as the \"Lead Report\" link when posting a summary to Jira, instead of a local "
                     "file path. This is the default for every tab below — a tab with its own file (and its "
                     "own SharePoint link) can override it individually.",
            )

            lead_template_multi_tab = st.checkbox(
                "Route different CIDs to different tabs and/or separate files",
                value=profile.lead_template_multi_tab if profile else False)

            lead_template_clear_existing = st.checkbox(
                "Clear existing leads before adding new ones",
                value=profile.lead_template_clear_existing if profile else False,
                help="On: removes all existing data rows (keeping the header and its formatting, which is "
                     "reused for the new rows) before pasting this run's leads — for a Lead Report that's "
                     "re-sent fresh each time rather than accumulated. Off (default): new leads are appended "
                     "below whatever's already there, like the Accumulated Report.",
            )

            if lead_template_multi_tab:
                st.info(
                    "Add one tab below for each group of CIDs. By default a tab writes into the shared Lead "
                    "Template file above, on the sheet you pick for it — set **\"File for this tab\"** only "
                    "when that CID group's leads go into a completely **different workbook** (its own "
                    "SharePoint file), not just a different sheet in the same file. A lead whose CID matches "
                    "no tab is skipped for the Lead Template step (with a warning) — it still goes to the "
                    "Accumulated Report normally."
                )
                lead_template_tabs_result = _render_lead_template_tabs(lead_template_path)
                if not lead_template_tabs_result:
                    st.warning("Multi-tab is enabled but no tabs are configured — "
                               "no leads will be pasted into the Lead Template.")
                _header_source_sheet = lead_template_tabs_result[0].sheet_name if lead_template_tabs_result else ""
                # A tab can point at a completely different workbook than the shared
                # path above — the column-mapping preview must read from whichever
                # file the first tab will actually write to, not always the shared
                # default (which can legitimately be left blank).
                _header_source_path = (
                    (lead_template_tabs_result[0].file_path or lead_template_path)
                    if lead_template_tabs_result else lead_template_path
                )
            else:
                template_sheet_options: list[str] = []
                if lead_template_path:
                    try:
                        template_sheet_options = list_sheet_names(lead_template_path)
                    except Exception as exc:
                        render_error(exc)
                if template_sheet_options:
                    default_template_sheet = profile.lead_template_sheet_name if profile else ""
                    template_sheet_idx = (
                        template_sheet_options.index(default_template_sheet)
                        if default_template_sheet in template_sheet_options else 0
                    )
                    lead_template_sheet_name = st.selectbox("Lead Template sheet", template_sheet_options,
                                                              index=template_sheet_idx, key="lead_template_sheet_select")
                else:
                    lead_template_sheet_name = st.text_input(
                        "Lead Template sheet name (enter a valid file path above to pick from a list)",
                        value=profile.lead_template_sheet_name if profile else "", key="lead_template_sheet_text")
                _header_source_sheet = lead_template_sheet_name
                _header_source_path = lead_template_path

            _tmpl_file_identity = f"{_header_source_path}::{_header_source_sheet}"
            _tmpl_fm_match = (
                profile.lead_template_field_mapping
                if profile and profile.lead_template_path == lead_template_path
                and (profile.lead_template_multi_tab == lead_template_multi_tab)
                and ((not lead_template_multi_tab and profile.lead_template_sheet_name == lead_template_sheet_name)
                     or (lead_template_multi_tab and profile.lead_template_tabs
                         and profile.lead_template_tabs[0].sheet_name == _header_source_sheet))
                else None
            )
            _tmpl_expected_for_detection = [v for v in [
                _tmpl_fm_match.email, _tmpl_fm_match.first_name, _tmpl_fm_match.last_name,
                _tmpl_fm_match.company, _tmpl_fm_match.cid,
            ] if v] if _tmpl_fm_match else None
            template_headers, template_headers_error = _safe_read_template_headers(
                _header_source_path, _header_source_sheet, _tmpl_expected_for_detection)

            # Same reset requirement as the Accumulated Report mapping above —
            # a keyed selectbox won't pick up a new default on its own when the
            # underlying file/sheet changes.
            if st.session_state.get("_tmpl_mapping_for") != _tmpl_file_identity:
                st.session_state["_tmpl_mapping_for"] = _tmpl_file_identity
                _tmpl_guess = guess_target_field_mapping(template_headers) if not _tmpl_fm_match else {}
                st.session_state["tmpl_map_email"] = _tmpl_fm_match.email if _tmpl_fm_match else _tmpl_guess.get("email", "")
                st.session_state["tmpl_map_first"] = _tmpl_fm_match.first_name if _tmpl_fm_match else _tmpl_guess.get("first_name", "")
                st.session_state["tmpl_map_last"] = _tmpl_fm_match.last_name if _tmpl_fm_match else _tmpl_guess.get("last_name", "")
                st.session_state["tmpl_map_company"] = _tmpl_fm_match.company if _tmpl_fm_match else _tmpl_guess.get("company", "")
                st.session_state["tmpl_map_cid"] = _tmpl_fm_match.cid if _tmpl_fm_match else _tmpl_guess.get("cid", "")

            with st.expander("🔗 Map Lead Template columns (optional)"):
                lead_template_field_mapping_result = _render_target_field_mapping(
                    "Lead Template", "tmpl", template_headers)
                if template_headers_error:
                    render_error(template_headers_error)
                elif not template_headers:
                    st.caption("Enter a valid Lead Template path and sheet above to map its columns — for "
                               "multiple tabs/files, this reads from the first tab's own file if it has one, "
                               "otherwise the shared Lead Template path.")
                else:
                    st.caption("Header row auto-detected — rows above it (titles, instructions) are left untouched.")

    with st.container(border=True):
        st.subheader("Duplicate Check")
        duplicate_enabled = st.checkbox("Enable Duplicate check", value=profile.duplicate.enabled if profile else False)

with tab_leadcap:
    with st.container(border=True):
        leadcap_enabled = st.checkbox("Enable Leadcap check", value=profile.leadcap.enabled if profile else False)
        leadcap_check_company = st.checkbox("Also check Leadcap by company name",
                                             value=profile.leadcap.check_company_name if profile else False)
        leadcap_segmented = st.checkbox("Leadcap is segmented by CID", value=profile.leadcap.segmented if profile else False)
        leadcap_flat_cap = None
        leadcap_segments: list[LeadcapSegment] = []
        leadcap_blank_cap_segments: list[str] = []
        if leadcap_enabled and not leadcap_segmented:
            leadcap_flat_cap = st.number_input("Flat lead cap", min_value=0, step=1,
                                                value=profile.leadcap.flat_cap if profile and profile.leadcap.flat_cap else 0)
        if leadcap_enabled and leadcap_segmented:
            if accumulated_path and st.button("Detect CIDs from Accumulated Report"):
                try:
                    detected = detect_cids_from_pacing_overview(accumulated_path)
                    st.session_state["leadcap_segments_text"] = "\n".join(f"{cid} - " for cid, _name in detected)
                except Exception as exc:
                    render_error(exc)
            st.caption("Define segments as: comma-separated CIDs - cap, one per line. "
                       "Merge two rows' CIDs together (comma-separated) to share one cap across them. "
                       "For eg:- 119336 - 3 or 119336, 119337 - 2")
            default_text = "\n".join(f"{', '.join(s.cids)} - {s.cap}" for s in (profile.leadcap.segments if profile else []))
            segment_text = st.text_area("Leadcap segments", value=default_text, key="leadcap_segments_text")
            for line in segment_text.splitlines():
                if not line.strip():
                    continue
                cids_str, _, cap_str = line.rpartition("-")
                cids_str, cap_str = cids_str.strip(), cap_str.strip()
                cids = [c.strip() for c in cids_str.split(",") if c.strip()]
                segment_name = ", ".join(cids)
                if not cap_str:
                    leadcap_blank_cap_segments.append(segment_name or "(unnamed)")
                    leadcap_segments.append(LeadcapSegment(name=segment_name, cids=cids, cap=0))
                else:
                    leadcap_segments.append(LeadcapSegment(name=segment_name, cids=cids, cap=int(cap_str)))
        if not leadcap_enabled:
            st.caption("Leadcap check is disabled.")

with tab_exclusion:
    with st.container(border=True):
        exclusion_enabled = st.checkbox("Enable Exclusion check", value=profile.exclusion.enabled if profile else False)
        exclusion_check_company = st.checkbox("Also check Exclusion by company name",
                                               value=profile.exclusion.check_company_name if profile else False)
        exclusion_sources_result: list[ReferenceSource] = []
        if exclusion_enabled:
            exclusion_sources_result = _render_sources_section(
                "exclusion_sources", "Exclusion", check_domain=True, check_company=exclusion_check_company, check_email=False)
            if not exclusion_sources_result:
                st.warning("Exclusion is enabled but no sources are configured — this check will do nothing.")
        else:
            st.caption("Exclusion check is disabled.")

with tab_tal:
    with st.container(border=True):
        tal_enabled = st.checkbox("Enable TAL check", value=profile.tal.enabled if profile else False)
        tal_check_company = st.checkbox("Also check TAL by company name", value=profile.tal.check_company_name if profile else False)
        tal_sources_result: list[ReferenceSource] = []
        if tal_enabled:
            tal_sources_result = _render_sources_section(
                "tal_sources", "TAL", check_domain=True, check_company=tal_check_company, check_email=False)
            if not tal_sources_result:
                st.warning("TAL is enabled but no sources are configured — this check will do nothing.")
        else:
            st.caption("TAL check is disabled.")

with tab_suppression:
    with st.container(border=True):
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
            if not suppression_sources_result:
                st.warning("Suppression is enabled but no sources are configured — this check will do nothing.")
        else:
            st.caption("Suppression check is disabled.")

with tab_dedupe:
    with st.container(border=True):
        st.subheader("Dedupe List")
        dedupe_enabled = st.checkbox("Enable Dedupe list check", value=profile.dedupe_list.enabled if profile else False)
        dedupe_sources_result: list[ReferenceSource] = []
        if dedupe_enabled:
            dedupe_sources_result = _render_sources_section(
                "dedupe_sources", "Dedupe List", check_domain=False, check_company=False, check_email=True)
            if not dedupe_sources_result:
                st.warning("Dedupe list is enabled but no sources are configured — this check will do nothing.")
        else:
            st.caption("Dedupe list check is disabled.")

with tab_complex:
    with st.container(border=True):
        st.subheader("Complex Account")
        st.caption(
            "For accounts that need extra, highly specific enrichment rules beyond the standard checks — "
            "TAL account-ID/company mapping, per-CID Installed Technologies and Predictive Buying Stage "
            "lookups, Capture Date/Email Opt-in/phone cleanup, and asset metadata auto-correction. These "
            "rules are hardcoded (not configurable per field) since they're currently built for one client's "
            "exact file layout — see core/complex_account.py."
        )
        complex_account_enabled = st.checkbox(
            "This is a complex account", value=profile.complex_account.enabled if profile else False)
        complex_account_tal_path = ""
        complex_account_specifications_path = ""
        if complex_account_enabled:
            complex_account_tal_path = _path_input_with_browse(
                "TAL file path", "complex_account_tal_path_input",
                profile.complex_account.tal_path if profile else "")
            st.caption("Account ID / company-name reference — matched by domain, with Country as a tie-breaker "
                       "when a domain maps to more than one account.")
            complex_account_specifications_path = _path_input_with_browse(
                "Specifications file path (\"...BANT NTQ & EHS\")", "complex_account_specs_path_input",
                profile.complex_account.specifications_path if profile else "")
            st.caption("Asset Name → URN / Asset URL 1 & 2 / Dell URL reference, used to auto-correct those "
                       "columns for each lead's Asset Title.")
            st.caption("The Installed Technologies and Predictive Buying Stage files are uploaded fresh on "
                       "the Run Check page each time, like the Purchased Lead Report — not configured here.")
        else:
            st.caption("Complex Account rules are disabled for this client.")

        st.divider()
        st.markdown("**Box Tracker (optional)**")
        st.caption(
            "For clients whose lead-approval process runs through a Box-hosted tracker workbook this app "
            "can't write to directly (no Box API access) — the tool instead maintains a local mirror "
            "workbook with the same tab/column shape, which gets copy-pasted into the real Box file by "
            "hand. See docs/superpowers/plans/2026-09-07-ibm-apac-box-tracker-automation.md."
        )
        box_tracker_enabled = st.checkbox(
            "This client uses a Box Tracker", value=profile.box_tracker.enabled if profile else False)
        box_tracker_mirror_path = ""
        box_tracker_cid_map: dict[str, str] = {}
        box_tracker_lead_template_map: dict[str, str] = {}
        box_tracker_pacing_skipped: list[str] = []
        if box_tracker_enabled:
            box_tracker_mirror_path = _path_input_with_browse(
                "Local mirror workbook path", "box_tracker_mirror_path_input",
                profile.box_tracker.mirror_workbook_path if profile else "")
            st.caption("CID → Campaign name mapping, one per line, format `CID,Campaign Name`:")
            _existing_map_text = "\n".join(
                f"{cid},{name}" for cid, name in
                (profile.box_tracker.cid_campaign_map.items() if profile else [])
            )
            _map_text = st.text_area(
                "CID to Campaign mapping", value=_existing_map_text, key="box_tracker_cid_map_input",
                label_visibility="collapsed", height=120)
            for _line in _map_text.splitlines():
                _line = _line.strip()
                if not _line or "," not in _line:
                    continue
                _cid, _name = _line.split(",", 1)
                box_tracker_cid_map[_cid.strip()] = _name.strip()

            st.caption(
                "CID → Lead Template file path, one per line, format `CID,file path` — each live "
                "segment has its own template file, routed to by the lead's own CID:"
            )
            _existing_template_map_text = "\n".join(
                f"{cid},{path}" for cid, path in
                (profile.box_tracker.cid_lead_template_path.items() if profile else [])
            )
            _template_map_text = st.text_area(
                "CID to Lead Template path mapping", value=_existing_template_map_text,
                key="box_tracker_lead_template_map_input", label_visibility="collapsed", height=120)
            for _line in _template_map_text.splitlines():
                _line = _line.strip()
                if not _line or "," not in _line:
                    continue
                _cid, _path = _line.split(",", 1)
                box_tracker_lead_template_map[_cid.strip()] = _path.strip()

            st.caption(
                "Campaign names to skip Pacing updates for (one per line) — for a segment that's just "
                "gone live with no established Pacing history yet, picks ALL available blank-Status "
                "leads instead of the Diff-based cap, and never writes to Pacing's Delivered cell:"
            )
            _existing_skip_text = "\n".join(profile.box_tracker.pacing_skipped_campaigns if profile else [])
            _skip_text = st.text_area(
                "Campaigns to skip Pacing updates for", value=_existing_skip_text,
                key="box_tracker_pacing_skipped_input", label_visibility="collapsed", height=68)
            box_tracker_pacing_skipped = [line.strip() for line in _skip_text.splitlines() if line.strip()]
        else:
            st.caption("Box Tracker is disabled for this client.")

        st.divider()
        st.markdown("**Convertr Upload (optional)**")
        st.caption(
            "Uploads a client-verified leadfile straight to Convertr via the Publisher API — every "
            "Publisher account has access to this by default, no Campaign Admin access required. Each "
            "CID routes to its own Convertr campaign."
        )
        convertr_enabled = st.checkbox(
            "This client uploads to Convertr", value=profile.convertr.enabled if profile else False)
        convertr_enterprise = ""
        convertr_publisher_id = ""
        convertr_campaigns: list[ConvertrCampaignMapping] = []
        convertr_field_mapping: dict[str, str] = {}
        convertr_leadfile_mapping: FieldMapping | None = None
        convertr_account_username = ""
        convertr_account_password = ""
        if convertr_enabled:
            convertr_enterprise = st.text_input(
                "Convertr enterprise subdomain (the {{enterprise}} in https://{{enterprise}}.cvtr.io)",
                value=profile.convertr.enterprise if profile else "").strip()
            convertr_publisher_id = st.text_input(
                "Your Convertr Publisher ID (Tracking → API Credentials on any campaign)",
                value=profile.convertr.publisher_id if profile else "").strip()

            st.caption(
                "CID → Convertr Campaign ID (SID) mapping, one per line, format `CID,CampaignID` — "
                "optionally add a third value for the Form ID once you know it (Tracking → API "
                "Credentials, or Test connection below): `CID,CampaignID,FormID`:"
            )
            _existing_campaigns_text = "\n".join(
                f"{c.cid},{c.campaign_id}" + (f",{c.global_form_id}" if c.global_form_id else "")
                for c in (profile.convertr.campaigns if profile else [])
            )
            _campaigns_text = st.text_area(
                "CID to Convertr campaign mapping", value=_existing_campaigns_text,
                key="convertr_campaigns_input", label_visibility="collapsed", height=160)
            for _line in _campaigns_text.splitlines():
                _line = _line.strip()
                if not _line or "," not in _line:
                    continue
                _parts = [p.strip() for p in _line.split(",")]
                _cid, _campaign_id = _parts[0], _parts[1]
                _global_form_id = _parts[2] if len(_parts) > 2 else ""
                convertr_campaigns.append(ConvertrCampaignMapping(
                    cid=_cid, campaign_id=_campaign_id, global_form_id=_global_form_id))

            convertr_field_mapping = _render_paired_field_mapping(
                "convertr", "Convertr", profile.convertr.field_mapping if profile else {})

            convertr_leadfile_mapping = _render_leadfile_column_mapping(
                "convertr", profile.convertr.leadfile_field_mapping if profile else None)

            st.caption(
                "Account login — used both to upload leads and to read back accepted/rejected outcomes "
                "(every Publisher user has API access with these same credentials) — stored locally on "
                "this machine only, never in the shared client profile:"
            )
            _existing_creds = get_convertr_account_credentials(client_name) if client_name else {
                "username": "", "password": ""}
            _account_col1, _account_col2 = st.columns(2)
            convertr_account_username = _account_col1.text_input(
                "Convertr username", value=_existing_creds["username"], key="convertr_account_username")
            convertr_account_password = _account_col2.text_input(
                "Convertr password", value=_existing_creds["password"], type="password",
                key="convertr_account_password")

            _unique_campaign_ids = sorted({c.campaign_id for c in convertr_campaigns if c.campaign_id})
            for _campaign_id in _unique_campaign_ids:
                if st.button(f"Test connection — campaign {_campaign_id}", key=f"convertr_test_{_campaign_id}"):
                    if not convertr_enterprise or not convertr_account_username or not convertr_account_password:
                        st.warning("Enter the enterprise subdomain and account login first.")
                    else:
                        try:
                            with st.spinner(f"Calling Convertr for campaign {_campaign_id}..."):
                                _token = convertr_client.login(
                                    convertr_enterprise, convertr_account_username, convertr_account_password,
                                )["access_token"]
                                _forms = convertr_client.get_publisher_form_fields(
                                    convertr_enterprise, _token, _campaign_id)
                            if not _forms:
                                st.warning("Connected, but Convertr returned no forms for this campaign.")
                            for _form in _forms:
                                _field_keys = ", ".join(
                                    f.removeprefix("form[").removesuffix("]") for f in _form.get("fields", []))
                                st.success(
                                    f"✅ Form \"{_form.get('formName')}\" (Form ID "
                                    f"{_form.get('formId')}) — fields: {_field_keys}"
                                )
                        except ConvertrError as exc:
                            st.error(f"❌ {exc}")
        else:
            st.caption("Convertr upload is disabled for this client.")

        st.divider()
        st.markdown("**Enhancio Upload (optional)**")
        st.caption(
            "Uploads a client-verified leadfile straight to Enhancio's Lead Import API. Unlike Convertr, "
            "auth is ONE shared org-wide Client ID (set once on the ⚙️ Settings page) — every client just "
            "needs its own CID → Enhancio allocation mapping. Each CID routes to its own allocation."
        )
        enhancio_enabled = st.checkbox(
            "This client uploads to Enhancio", value=profile.enhancio.enabled if profile else False)
        enhancio_allocations: list[EnhancioAllocationMapping] = []
        enhancio_field_mapping: dict[str, str] = {}
        enhancio_fixed_values: dict[str, dict[str, str]] = {}
        enhancio_leadfile_mapping: FieldMapping | None = None
        if enhancio_enabled:
            st.caption(
                "CID → Enhancio allocation mapping, one per line, format `CID,allocationUid` — use "
                "\"Fetch allocations from Enhancio\" below to find the right allocationUid instead of "
                "hunting for it in the Enhancio portal:"
            )
            _existing_allocations_text = "\n".join(
                f"{a.cid},{a.allocation_uid}" for a in (profile.enhancio.allocations if profile else [])
            )
            _allocations_text = st.text_area(
                "CID to Enhancio allocation mapping", value=_existing_allocations_text,
                key="enhancio_allocations_input", label_visibility="collapsed", height=120)
            for _line in _allocations_text.splitlines():
                _line = _line.strip()
                if not _line or "," not in _line:
                    continue
                _cid, _allocation_uid = (p.strip() for p in _line.split(",", 1))
                enhancio_allocations.append(EnhancioAllocationMapping(cid=_cid, allocation_uid=_allocation_uid))

            st.caption(
                "Use the field labels the Describe Fields API reports for the allocation (Test "
                "connection below) as the target names."
            )
            enhancio_field_mapping = _render_paired_field_mapping(
                "enhancio", "Enhancio", profile.enhancio.field_mapping if profile else {})

            st.caption(
                "Fixed field values per allocation, one per line, format `allocationUid,Field "
                "Label,Fixed Value` — for a field that's the SAME for every lead sent to that "
                "allocation (e.g. Company Size, Lead Source), not read from the leadfile. Confirmed "
                "once here — every future upload to that allocation applies it automatically, no "
                "need to set it again:"
            )
            _existing_fixed_values_text = "\n".join(
                f"{allocation_uid},{field_label},{fixed_value}"
                for allocation_uid, fields in (profile.enhancio.fixed_field_values.items() if profile else [])
                for field_label, fixed_value in fields.items()
            )
            _fixed_values_text = st.text_area(
                "Enhancio fixed field values", value=_existing_fixed_values_text,
                key="enhancio_fixed_values_input", label_visibility="collapsed", height=100)
            for _line in _fixed_values_text.splitlines():
                _line = _line.strip()
                if not _line or _line.count(",") < 2:
                    continue
                _allocation_uid, _field_label, _fixed_value = (p.strip() for p in _line.split(",", 2))
                enhancio_fixed_values.setdefault(_allocation_uid, {})[_field_label] = _fixed_value

            enhancio_leadfile_mapping = _render_leadfile_column_mapping(
                "enhancio", profile.enhancio.leadfile_field_mapping if profile else None)

            _enhancio_client_id = get_enhancio_client_id()
            if not _enhancio_client_id:
                st.caption("No Enhancio Client ID configured yet — set one on the ⚙️ Settings page to "
                           "enable the lookup/test buttons below.")
            else:
                if st.button("Fetch allocations from Enhancio", key="enhancio_fetch_allocations"):
                    try:
                        with st.spinner("Calling Enhancio..."):
                            _token = enhancio_client.get_access_token(_enhancio_client_id)["access_token"]
                            _allocations = enhancio_client.list_publisher_allocations(_token)
                        if not _allocations:
                            st.warning("Connected, but Enhancio returned no allocations for this account.")
                        for _allocation in _allocations:
                            st.success(
                                f"✅ \"{_allocation.get('campaignName')}\" — allocationUid "
                                f"{_allocation.get('uniqueId')} ({_allocation.get('allocationStatus')})"
                            )
                    except EnhancioError as exc:
                        st.error(f"❌ {exc}")

                _unique_allocation_uids = sorted({a.allocation_uid for a in enhancio_allocations if a.allocation_uid})
                for _allocation_uid in _unique_allocation_uids:
                    if st.button(f"Test connection — allocation {_allocation_uid}",
                                 key=f"enhancio_test_{_allocation_uid}"):
                        try:
                            with st.spinner(f"Calling Enhancio for allocation {_allocation_uid}..."):
                                _token = enhancio_client.get_access_token(_enhancio_client_id)["access_token"]
                                _fields = enhancio_client.describe_fields(_token, _allocation_uid)
                            if not _fields:
                                st.warning("Connected, but Enhancio returned no fields for this allocation.")
                            # Cross-check against the field mapping above --
                            # a mandatory field Enhancio will reject the
                            # whole import for if it's missing, so this is
                            # caught here, before ever uploading a single
                            # lead, rather than discovered only from a
                            # failed-import count in the Enhancio portal.
                            _mapped_targets = set(enhancio_field_mapping.values())
                            _unmapped_mandatory = [
                                _field.get("fieldLabel") for _field in _fields
                                if _field.get("mandatory") == "Y" and _field.get("fieldLabel") not in _mapped_targets
                            ]
                            if _unmapped_mandatory:
                                st.error(
                                    "❌ These mandatory fields have NO mapping entry pointing to them at all "
                                    "-- Enhancio will reject every lead sent to this allocation until each has "
                                    "one: " + "; ".join(f'\"{f}\"' for f in _unmapped_mandatory)
                                )
                            for _field in _fields:
                                _label = _field.get("fieldLabel")
                                _required = "required" if _field.get("mandatory") == "Y" else "optional"
                                _mapped_from = next(
                                    (col for col, target in enhancio_field_mapping.items() if target == _label),
                                    None)
                                _line = f"✅ \"{_label}\" ({_required})"
                                if _mapped_from is not None:
                                    _line += f" — mapped from leadfile column \"{_mapped_from}\""
                                st.success(_line)
                                # A field constrained to a fixed picklist
                                # (Enhancio rejects anything outside it as
                                # "Invalid field value") -- surfaced so a
                                # rejected-batch mismatch can be diagnosed
                                # here instead of guessing at allowed values.
                                _allowed_values = _field.get("fieldValues")
                                if _allowed_values:
                                    st.caption(f"　　Allowed values: {', '.join(str(v) for v in _allowed_values)}")
                        except EnhancioError as exc:
                            st.error(f"❌ {exc}")
        else:
            st.caption("Enhancio upload is disabled for this client.")

        st.divider()
        st.markdown("**Integrate Upload (optional)**")
        st.caption(
            "Uploads a client-verified leadfile straight to Integrate.com's Lead API. One shared "
            "org-wide API Key/Secret (set once on the ⚙️ Settings page) — this client just needs its "
            "own Source ID (SID), from that Source's URL on home.integrate.com."
        )
        integrate_enabled = st.checkbox(
            "This client uploads to Integrate", value=profile.integrate.enabled if profile else False,
            key="integrate_enabled")
        integrate_sid = ""
        integrate_callback_url = ""
        integrate_field_mapping: dict[str, str] = {}
        integrate_fixed_values: dict[str, str] = {}
        integrate_leadfile_mapping: FieldMapping | None = None
        if integrate_enabled:
            integrate_sid = st.text_input(
                "Integrate Source ID (SID) — the GUID in home.integrate.com/sources/{SID}",
                value=profile.integrate.sid if profile else "", key="integrate_sid_input").strip()
            integrate_callback_url = st.text_input(
                "Callback URL (optional — leave blank unless Integrate told you to set one)",
                value=profile.integrate.callback_url if profile else "", key="integrate_callback_url_input").strip()

            integrate_field_mapping = _render_paired_field_mapping(
                "integrate", "Integrate", profile.integrate.field_mapping if profile else {})

            st.caption(
                "Fixed field values, one per line, format `Attribute,Fixed Value` — for an Integrate "
                "attribute that's the SAME for every lead this client sends (e.g. country), not read "
                "from the leadfile:"
            )
            _existing_integrate_fixed_text = "\n".join(
                f"{attr},{value}"
                for attr, value in (profile.integrate.fixed_field_values.items() if profile else [])
            )
            _integrate_fixed_text = st.text_area(
                "Integrate fixed field values", value=_existing_integrate_fixed_text,
                key="integrate_fixed_values_input", label_visibility="collapsed", height=80)
            for _line in _integrate_fixed_text.splitlines():
                _line = _line.strip()
                if not _line or "," not in _line:
                    continue
                _attr, _value = (p.strip() for p in _line.split(",", 1))
                integrate_fixed_values[_attr] = _value

            integrate_leadfile_mapping = _render_leadfile_column_mapping(
                "integrate", profile.integrate.leadfile_field_mapping if profile else None)
        else:
            st.caption("Integrate upload is disabled for this client.")

st.divider()

_enabled_summary = ", ".join(
    label for label, on in [
        ("Duplicate", duplicate_enabled), ("Leadcap", leadcap_enabled), ("Exclusion", exclusion_enabled),
        ("TAL", tal_enabled), ("Suppression", suppression_enabled), ("Dedupe list", dedupe_enabled),
    ] if on
) or "None"
st.caption(f"Enabled checks: {_enabled_summary}")

if st.button("💾 Save Client Profile", type="primary"):
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

    _blank_tab_count = sum(1 for t in lead_template_tabs_result if not t.sheet_name)

    _client_name_invalid_chars = set('/\\') & set(client_name)
    if not client_name:
        st.error("Client name is required.")
    elif _client_name_invalid_chars or ".." in client_name:
        # The name becomes a bare filename ("<name>.json") under clients_dir
        # with no further sanitizing — a "/" or "\" silently creates a
        # nested, orphaned profile that list_profile_names()'s flat scan can
        # never show again, and ".." can escape clients_dir entirely onto
        # an arbitrary path on disk.
        st.error("Client name can't contain a slash, a backslash, or \"..\" — these would break "
                 "how the profile is saved to disk.")
    elif leadcap_enabled and leadcap_segmented and leadcap_blank_cap_segments:
        st.error("Leadcap segments are missing a cap: " + ", ".join(leadcap_blank_cap_segments) +
                  ". Fill in a cap for every segment before saving (this is required after using "
                  "'Detect CIDs from Accumulated Report', which leaves caps blank).")
    elif lead_template_multi_tab and _blank_tab_count:
        st.error(f"{_blank_tab_count} Lead Template tab(s) are missing a sheet name. "
                 "Pick a sheet for every tab before saving.")
    elif _name_error:
        st.error(_name_error)
    else:
        new_profile = ClientProfile(
            name=client_name,
            accumulated_report_path=accumulated_path,
            accumulated_tab_name=accumulated_tab_name or "Accumulated",
            refund_tab_name=refund_tab_name or "Refund",
            jira_ticket_key=extract_ticket_key(jira_ticket_key) if jira_ticket_key.strip() else "",
            jira_reporter_name=jira_reporter_name.strip(),
            accumulated_report_link=accumulated_report_link.strip(),
            lead_template_link=lead_template_link.strip() if client_mode == "Lead QA" else "",
            client_mode=client_mode,
            collation_enabled=collation_enabled,
            lead_template_path=lead_template_path if client_mode == "Lead QA" else "",
            lead_template_sheet_name=(
                lead_template_sheet_name if client_mode == "Lead QA" and not lead_template_multi_tab else ""),
            lead_template_multi_tab=lead_template_multi_tab if client_mode == "Lead QA" else False,
            lead_template_tabs=(
                lead_template_tabs_result if client_mode == "Lead QA" and lead_template_multi_tab else []),
            lead_template_clear_existing=(
                lead_template_clear_existing if client_mode == "Lead QA" else False),
            field_mapping=profile.field_mapping if profile else None,
            accumulated_field_mapping=accumulated_field_mapping_result,
            lead_template_field_mapping=lead_template_field_mapping_result if client_mode == "Lead QA" else None,
            duplicate=DuplicateConfig(enabled=duplicate_enabled),
            leadcap=LeadcapConfig(enabled=leadcap_enabled, segmented=leadcap_segmented,
                                   flat_cap=int(leadcap_flat_cap) if leadcap_flat_cap else None,
                                   segments=leadcap_segments, check_company_name=leadcap_check_company),
            exclusion=ExclusionConfig(enabled=exclusion_enabled, check_company_name=exclusion_check_company,
                                       sources=exclusion_sources_result if exclusion_enabled else (
                                           profile.exclusion.sources if profile else [])),
            tal=TalConfig(enabled=tal_enabled, check_company_name=tal_check_company,
                          sources=tal_sources_result if tal_enabled else (
                              profile.tal.sources if profile else [])),
            suppression=SuppressionConfig(enabled=suppression_enabled, check_domain=suppression_check_domain,
                                           check_company_name=suppression_check_company,
                                           check_email=suppression_check_email,
                                           sources=suppression_sources_result if suppression_enabled else (
                                               profile.suppression.sources if profile else [])),
            dedupe_list=DedupeListConfig(enabled=dedupe_enabled, sources=dedupe_sources_result if dedupe_enabled else (
                profile.dedupe_list.sources if profile else [])),
            complex_account=ComplexAccountConfig(
                enabled=complex_account_enabled,
                tal_path=complex_account_tal_path if complex_account_enabled else "",
                specifications_path=complex_account_specifications_path if complex_account_enabled else "",
            ),
            box_tracker=BoxTrackerConfig(
                enabled=box_tracker_enabled,
                mirror_workbook_path=box_tracker_mirror_path if box_tracker_enabled else "",
                cid_campaign_map=box_tracker_cid_map if box_tracker_enabled else {},
                cid_lead_template_path=box_tracker_lead_template_map if box_tracker_enabled else {},
                pacing_skipped_campaigns=box_tracker_pacing_skipped if box_tracker_enabled else [],
            ),
            convertr=ConvertrConfig(
                enabled=convertr_enabled,
                enterprise=convertr_enterprise if convertr_enabled else "",
                publisher_id=convertr_publisher_id if convertr_enabled else "",
                campaigns=convertr_campaigns if convertr_enabled else [],
                field_mapping=convertr_field_mapping if convertr_enabled else {},
                leadfile_field_mapping=convertr_leadfile_mapping if convertr_enabled else None,
            ),
            enhancio=EnhancioConfig(
                enabled=enhancio_enabled,
                allocations=enhancio_allocations if enhancio_enabled else [],
                field_mapping=enhancio_field_mapping if enhancio_enabled else {},
                fixed_field_values=enhancio_fixed_values if enhancio_enabled else {},
                leadfile_field_mapping=enhancio_leadfile_mapping if enhancio_enabled else None,
            ),
            integrate=IntegrateConfig(
                enabled=integrate_enabled,
                sid=integrate_sid if integrate_enabled else "",
                callback_url=integrate_callback_url if integrate_enabled else "",
                field_mapping=integrate_field_mapping if integrate_enabled else {},
                fixed_field_values=integrate_fixed_values if integrate_enabled else {},
                leadfile_field_mapping=integrate_leadfile_mapping if integrate_enabled else None,
            ),
        )
        saved_path = save_profile(new_profile, get_clients_dir())
        if convertr_enabled and (convertr_account_username or convertr_account_password):
            save_convertr_account_credentials(
                client_name, convertr_account_username, convertr_account_password)
        st.toast(f"Saved profile to {saved_path}", icon="✅")
