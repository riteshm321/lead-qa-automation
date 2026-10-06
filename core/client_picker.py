import os

import streamlit as st

from core.profile_store import list_profile_groups


ALL_GROUPS_LABEL = "All groups"
UNGROUPED_LABEL = "Ungrouped"


def group_filter_options(name_to_group: dict[str, str]) -> list[str]:
    """Options for the picker's "Group" filter: "All groups", then every
    distinct non-blank group sorted case-insensitively, then "Ungrouped"
    (only if some profile has no group). Returns [] when no profile has a
    group at all -- the picker then shows only the flat Client selectbox.
    """
    groups = sorted({g for g in name_to_group.values() if g}, key=str.lower)
    if not groups:
        return []
    options = [ALL_GROUPS_LABEL, *groups]
    if any(not g for g in name_to_group.values()):
        options.append(UNGROUPED_LABEL)
    return options


def profiles_in_group(name_to_group: dict[str, str], group_filter: str) -> list[str]:
    """Profile names matching a Group filter option, sorted
    case-insensitively: all profiles for "All groups", blank-group profiles
    for "Ungrouped", otherwise exactly that group's members.
    """
    if group_filter == ALL_GROUPS_LABEL:
        names = list(name_to_group)
    elif group_filter == UNGROUPED_LABEL:
        names = [n for n, g in name_to_group.items() if not g]
    else:
        names = [n for n, g in name_to_group.items() if g == group_filter]
    return sorted(names, key=str.lower)


@st.cache_data(show_spinner=False)
def _cached_profile_groups(clients_dir: str, dir_mtime: float) -> dict[str, str]:
    # dir_mtime must NOT be underscore-prefixed -- Streamlit excludes any
    # parameter named with a leading underscore from the cache key hash.
    # Keyed on the directory's own mtime so a newly saved/removed/
    # regrouped profile still shows up on the very next rerun, matching
    # the exact pattern pages/1_Client_Setup.py and pages/2_Run_Check.py
    # already use for list_profile_names.
    return list_profile_groups(clients_dir)


def render_client_picker(clients_dir: str, key_prefix: str, label: str = "Client") -> str | None:
    """Group -> Client picker shared by Client Setup's 'Edit existing
    client' selector and Run Check's Client selector.

    When at least one profile has a client_group, a "Group" filter
    selectbox (All groups / each group / Ungrouped) renders on the left and
    the Client selectbox (labeled `label`) on the right lists only that
    group's profiles by exact name. With no groups at all, only the flat
    Client selectbox renders. Returns the selected profile name, or None
    if there are no profiles.
    """
    try:
        dir_mtime = os.path.getmtime(clients_dir)
    except OSError:
        dir_mtime = 0.0
    name_to_group = _cached_profile_groups(clients_dir, dir_mtime)
    if not name_to_group:
        return None

    client_key = f"{key_prefix}_client_profile"
    filter_options = group_filter_options(name_to_group)
    if not filter_options:
        return _client_selectbox(st, label, profiles_in_group(name_to_group, ALL_GROUPS_LABEL), client_key)

    filter_key = f"{key_prefix}_group_filter"
    if st.session_state.get(filter_key) not in filter_options:
        st.session_state.pop(filter_key, None)
    group_col, client_col = st.columns(2)
    selected_group = group_col.selectbox(
        "Group", filter_options, key=filter_key, filter_mode=None,
        on_change=_select_first_client_of_group, args=(name_to_group, filter_key, client_key))
    return _client_selectbox(client_col, label, profiles_in_group(name_to_group, selected_group), client_key)


def preselect_client_state(key_prefix: str, client_name: str, name_to_group: dict[str, str]) -> dict[str, str]:
    """session_state values that make render_client_picker(..., key_prefix)
    render with `client_name` selected on its next run: the Group filter
    (only when groups exist) set to the client's own group -- or "All
    groups" for an ungrouped client -- so the client is guaranteed to be in
    the filtered Client options, plus the Client selectbox itself. Returns
    {} for a name that isn't a known profile.
    """
    if client_name not in name_to_group:
        return {}
    state = {}
    if group_filter_options(name_to_group):
        state[f"{key_prefix}_group_filter"] = name_to_group[client_name] or ALL_GROUPS_LABEL
    state[f"{key_prefix}_client_profile"] = client_name
    return state


def preselect_client(key_prefix: str, client_name: str, clients_dir: str) -> None:
    """Preselect `client_name` in another page's client picker (e.g. Run
    Check -> Client Setup). Must be called for a picker NOT rendered in the
    current run -- Streamlit forbids writing a widget's key after that
    widget was instantiated in the same run.
    """
    st.session_state.update(preselect_client_state(key_prefix, client_name, list_profile_groups(clients_dir)))


def _select_first_client_of_group(name_to_group: dict[str, str], filter_key: str, client_key: str) -> None:
    # Group on_change callback: runs before the rerun's script body, so the
    # Client selectbox is rendered with the new group's first client as an
    # explicitly set value. Just dropping the old key left the browser still
    # DISPLAYING the previous client while the page returned (and loaded) a
    # different one.
    names = profiles_in_group(name_to_group, st.session_state.get(filter_key, ALL_GROUPS_LABEL))
    if names:
        st.session_state[client_key] = names[0]
    else:
        st.session_state.pop(client_key, None)


def _client_selectbox(container, label: str, names: list[str], key: str) -> str | None:
    # Fall back to the first client when the previous pick isn't in this
    # (possibly re-filtered) list, so the selectbox never holds a stale value.
    # Assign it explicitly rather than popping the key: an explicit
    # session_state value is pushed to the browser, a popped key is not, and
    # the displayed client must always equal the returned one.
    if names and st.session_state.get(key) not in names:
        st.session_state[key] = names[0]
    return container.selectbox(label, names, key=key, filter_mode=None)


NEW_GROUP_SENTINEL = "\x00__new_group__"
NEW_GROUP_LABEL = "+ Create new group…"
NO_GROUP_LABEL = "No group"


def group_choices(name_to_group: dict[str, str], current_group: str = "") -> list[tuple[str, str]]:
    """Choices for Client Setup's client-group dropdown, as (label, value)
    pairs: "No group" (value ""), then every distinct non-blank group sorted
    case-insensitively and labeled with its member count, then the
    create-new sentinel. `current_group`, if non-blank and not already a
    known group, is still included so it can be preselected.
    """
    counts: dict[str, int] = {}
    for group in name_to_group.values():
        if group:
            counts[group] = counts.get(group, 0) + 1
    if current_group and current_group not in counts:
        counts[current_group] = 0
    choices = [(NO_GROUP_LABEL, "")]
    for group in sorted(counts, key=str.lower):
        n = counts[group]
        choices.append((f"{group} ({n} client{'' if n == 1 else 's'})", group))
    choices.append((NEW_GROUP_LABEL, NEW_GROUP_SENTINEL))
    return choices


def render_group_selector(clients_dir: str, current_group: str, key_prefix: str) -> str:
    """Dropdown of existing client groups plus "No group" and "+ Create new
    group..."; the latter reveals a "New group name" text input. Widget keys
    are f"{key_prefix}_select" and f"{key_prefix}_new" -- callers must reset
    both when switching profiles. Returns the group to save (stripped; ""
    for no group, including a blank new-group name).
    """
    try:
        dir_mtime = os.path.getmtime(clients_dir)
    except OSError:
        dir_mtime = 0.0
    select_key = f"{key_prefix}_select"
    name_to_group = _cached_profile_groups(clients_dir, dir_mtime)
    if select_key not in st.session_state:
        st.session_state[select_key] = current_group
    # Keep whatever is currently selected (e.g. a group not yet on disk)
    # in the options so the selectbox never holds an invalid value.
    selected_now = st.session_state[select_key]
    extra = selected_now if selected_now != NEW_GROUP_SENTINEL else current_group
    choices = group_choices(name_to_group, extra)
    values = [v for _, v in choices]
    labels = {v: lbl for lbl, v in choices}
    selected = st.selectbox(
        "Assign to group",
        values,
        format_func=labels.__getitem__,
        key=select_key,
        filter_mode=None,
        help="Groups this profile with other regional profiles for the same brand (e.g. \"Autodesk APAC\" and "
             "\"Autodesk EMEA\" both in \"Autodesk\") so the Group filter above the client picker can show them "
             "together. Pick \"No group\" if this client isn't split by region.",
    )
    if selected == NEW_GROUP_SENTINEL:
        return st.text_input("New group name", key=f"{key_prefix}_new").strip()
    return selected
