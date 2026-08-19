import os
import uuid

import streamlit as st

from core.errors import render_error
from core.excel_io import (
    list_sheet_names, read_sheet_as_dataframe, detect_cids_from_pacing_overview, guess_target_field_mapping,
    find_header_row, read_sheet_headers,
)
from core.app_settings import (
    get_aliases_path, get_clients_dir, get_jira_settings, get_shared_root_dir,
    load_app_settings, save_app_settings, save_jira_settings,
)
from core.file_browser import browse_for_file, browse_for_folder
from core.jira_client import extract_ticket_key
from core.models import (
    ClientProfile, DuplicateConfig, LeadcapConfig, LeadcapSegment,
    ExclusionConfig, TalConfig, ReferenceSource, SuppressionConfig, DedupeListConfig, FieldMapping,
    LeadTemplateTab,
)
from core.profile_store import save_profile, load_profile, list_profile_names

st.title("Client Setup")

with st.expander("⚙️ Shared team data location"):
    _clients_dir = get_clients_dir()
    _aliases_path = get_aliases_path()
    st.caption(f"Clients are currently stored at: `{os.path.abspath(_clients_dir)}`")
    st.caption(f"Company aliases are currently stored at: `{os.path.abspath(_aliases_path)}`")
    st.caption(
        "By default both are private to this machine — a colleague using the exe on their own "
        "laptop won't see these clients or learned aliases. To share them across a team, point this "
        "at a folder inside a OneDrive folder you both sync locally (each person sets their own local "
        "path to that same shared folder) — pick the folder itself, not a 'clients' subfolder inside "
        "it; the app creates and manages its own `clients/` and `aliases/` subfolders under whatever "
        "you select here, the same way it does for the private default. Any aliases you'd already "
        "taught locally are copied over so nothing is lost. Note: OneDrive syncs file-by-file, not "
        "instantly — if two people save the *same* client profile at the *same* moment, OneDrive may "
        "create a conflicted copy instead of merging, so treat this as low-frequency shared config, "
        "not simultaneous editing."
    )
    # Label rendered above (not inline in the text_input) so both columns
    # start at the exact same vertical offset — keeps the Browse button
    # aligned with the input box regardless of label text/theme font metrics,
    # same as _path_input_with_browse below.
    st.markdown("**Shared team data folder**")
    col_input, col_browse = st.columns([5, 1])
    # The Browse button's session_state write must run before the
    # text_input with the same key is instantiated below — Streamlit
    # forbids modifying a widget's session_state value after that widget
    # has already been created in the same script run. Filling col_browse
    # first (button) and col_input second (text_input) — both from this one
    # st.columns() call, with no bare/unwrapped calls in between — keeps
    # col_input rendering on the left regardless of that fill order, exactly
    # like the proven pattern in _path_input_with_browse below.
    with col_browse:
        if st.button("📂 Browse...", key="clients_dir_browse", use_container_width=True):
            chosen = browse_for_folder()
            if chosen:
                st.session_state["clients_dir_input"] = chosen
                st.rerun()
    with col_input:
        _new_dir = st.text_input("Shared team data folder", value=get_shared_root_dir(),
                                  placeholder="Leave blank for the private default", key="clients_dir_input",
                                  label_visibility="collapsed")

    col_save, col_reset = st.columns(2)
    with col_save:
        if st.button("Save", key="clients_dir_save", use_container_width=True):
            new_root = _new_dir.strip()
            if new_root:
                os.makedirs(os.path.join(new_root, "clients"), exist_ok=True)
                new_aliases_path = os.path.join(new_root, "aliases", "company_aliases.json")
                old_aliases_path = get_aliases_path()
                if not os.path.isfile(new_aliases_path) and os.path.isfile(old_aliases_path):
                    import shutil
                    os.makedirs(os.path.dirname(new_aliases_path), exist_ok=True)
                    shutil.copy2(old_aliases_path, new_aliases_path)
            updated_settings = {k: v for k, v in load_app_settings().items()
                                if k not in ("clients_dir", "shared_root_dir")}
            updated_settings["shared_root_dir"] = new_root
            save_app_settings(updated_settings)
            st.success("Saved. Reloading...")
            st.rerun()
    with col_reset:
        if st.button("Reset to default", key="clients_dir_reset", use_container_width=True):
            save_app_settings({
                k: v for k, v in load_app_settings().items() if k not in ("clients_dir", "shared_root_dir")
            })
            st.rerun()

with st.expander("🔑 Jira account (private to this machine)"):
    st.caption(
        "Used only for the \"Post summary to Jira\" button on the Run Check page, so a finalized run's "
        "summary can be posted as a comment on that client's Jira ticket under your own account. "
        "This is stored locally on this machine only — never inside the shared clients folder above, "
        "since an API token is a secret tied to your Jira login."
    )
    _jira = get_jira_settings()
    jira_base_url = st.text_input("Jira site URL", value=_jira["base_url"],
                                   placeholder="https://yourcompany.atlassian.net", key="jira_base_url_input")
    jira_email = st.text_input("Your Jira email", value=_jira["email"], key="jira_email_input")
    jira_api_token = st.text_input(
        "Your Jira API token", value=_jira["api_token"], type="password", key="jira_api_token_input",
        help="Generate one at id.atlassian.com/manage-profile/security/api-tokens",
    )
    if st.button("Save Jira account", key="jira_settings_save"):
        save_jira_settings(jira_base_url, jira_email, jira_api_token)
        st.success("Saved.")
        st.rerun()


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
        st.caption("No tabs configured yet.")
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


def _render_sources_section(
    section_key: str,
    label: str,
    check_domain: bool,
    check_company: bool,
    check_email: bool,
) -> list[ReferenceSource]:
    result: list[ReferenceSource] = []
    if not st.session_state[section_key]:
        st.caption(f"No {label} sources configured yet.")
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
                    header_options = list(read_sheet_as_dataframe(src["file_path"], src["sheet_name"]).columns)
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
    return FieldMapping(email=email, first_name=first_name, last_name=last_name, company=company, cid=cid)


existing = list_profile_names(get_clients_dir())
mode = st.radio("Mode", ["Create new client", "Edit existing client"])

if mode == "Edit existing client" and existing:
    selected_name = st.selectbox("Client", existing)
    try:
        profile = load_profile(selected_name, get_clients_dir())
    except TypeError as exc:
        st.error(f"Could not load the profile for '{selected_name}' — it may be in an older format. "
                 f"Delete and re-create it in Client Setup. (Technical detail: {exc})")
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

tab_basics, tab_leadcap, tab_exclusion, tab_tal, tab_suppression, tab_dedupe = st.tabs([
    "🗂️ Basics", "🧮 Leadcap", "🚫 Exclusion", "🎯 TAL", "🔕 Suppression", "🧹 Dedupe & Duplicate",
])

with tab_basics:
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

    st.divider()
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
        lead_template_link = st.text_input(
            "Lead Template SharePoint link (optional)",
            value=profile.lead_template_link if profile else "",
            placeholder="e.g. https://madlog.sharepoint.com/:x:/s/.../...",
            help="Used as the \"Lead Report\" link when posting a summary to Jira, instead of a local "
                 "file path. This is the default for every tab below — a tab with its own file (and its "
                 "own SharePoint link) can override it individually.",
        )

        lead_template_multi_tab = st.checkbox(
            "This Lead Template has multiple tabs (routed by CID)",
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
            st.caption("Each tab below receives leads whose CID matches its list. A lead whose CID matches "
                       "no tab is skipped for the Lead Template step (with a warning) — it still goes to "
                       "the Accumulated Report normally.")
            lead_template_tabs_result = _render_lead_template_tabs(lead_template_path)
            if not lead_template_tabs_result:
                st.warning("Multi-tab is enabled but no tabs are configured — "
                           "no leads will be pasted into the Lead Template.")
            _header_source_sheet = lead_template_tabs_result[0].sheet_name if lead_template_tabs_result else ""
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

        _tmpl_file_identity = f"{lead_template_path}::{_header_source_sheet}"
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
            lead_template_path, _header_source_sheet, _tmpl_expected_for_detection)

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
                st.caption("Enter a valid Lead Template path and sheet above to map its columns.")
            else:
                st.caption("Header row auto-detected — rows above it (titles, instructions) are left untouched.")

    st.divider()
    st.subheader("Duplicate Check")
    duplicate_enabled = st.checkbox("Enable Duplicate check", value=profile.duplicate.enabled if profile else False)

with tab_leadcap:
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

    if not client_name:
        st.error("Client name is required.")
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
        )
        saved_path = save_profile(new_profile, get_clients_dir())
        st.success(f"Saved profile to {saved_path}")
