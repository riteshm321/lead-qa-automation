import os

import streamlit as st

from core.profile_store import list_profile_groups


def group_profile_names(name_to_group: dict[str, str]) -> dict[str, list[str]]:
    """Groups profile names by their client_group. An ungrouped profile
    (client_group == "") is treated as its own singleton group, keyed by
    its own name, so every profile is reachable through the picker
    whether or not it opted into a group. Returns {group_label:
    [profile_name, ...]}, both the outer mapping and each inner list
    sorted case-insensitively.
    """
    groups: dict[str, list[str]] = {}
    for name, group in name_to_group.items():
        key = group if group else name
        groups.setdefault(key, []).append(name)
    return {
        key: sorted(names, key=str.lower)
        for key, names in sorted(groups.items(), key=lambda kv: kv[0].lower())
    }


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
    """Two-step group -> profile client picker, shared by Client Setup's
    'Edit existing client' selector and Run Check's Client selector so
    the two pages can never disagree about how grouping renders.

    Step 1 picks a client_group (or an ungrouped profile's own name,
    treated as its own singleton group) via a plain st.selectbox labeled
    exactly `label`. Step 2 -- only rendered when that group actually has
    more than one profile -- picks which profile within it, labeled
    "{label} (region)"; a single-profile group auto-selects without ever
    showing step 2, so the common (non-split) case stays exactly as fast
    as today: one click, not two, and the widget looks identical to
    today's plain flat picker.

    Returns the selected profile name, or None if there are no profiles
    at all (caller decides how to handle that -- e.g. Run Check shows a
    warning and st.stop()s).
    """
    try:
        dir_mtime = os.path.getmtime(clients_dir)
    except OSError:
        dir_mtime = 0.0
    name_to_group = _cached_profile_groups(clients_dir, dir_mtime)
    if not name_to_group:
        return None

    groups = group_profile_names(name_to_group)
    group_labels = [
        f"{key} ({len(names)} regions)" if len(names) > 1 else names[0]
        for key, names in groups.items()
    ]
    label_to_key = dict(zip(group_labels, groups.keys()))
    selected_label = st.selectbox(label, group_labels, key=f"{key_prefix}_client_group")
    candidates = groups[label_to_key[selected_label]]

    if len(candidates) == 1:
        return candidates[0]
    return st.selectbox(f"{label} (region)", candidates, key=f"{key_prefix}_client_profile")
