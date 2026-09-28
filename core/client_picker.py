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
