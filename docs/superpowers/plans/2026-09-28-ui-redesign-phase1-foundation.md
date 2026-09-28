# UI Redesign Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the two foundation pieces of the UI redesign that pay off
immediately on their own: a Material Symbols icon system replacing emoji,
and a two-step client-group picker so a brand split across regional
profiles (e.g. one APAC profile and one EMEA profile) is pickable as one
group instead of two unrelated flat-list entries.

**Architecture:** A one-file icon swap in `Summary.py`. A new optional
`client_group` field on `ClientProfile`, a new `list_profile_groups` in
`core/profile_store.py`, and a new `core/client_picker.py` module (a pure
grouping function + a Streamlit rendering function) shared by Client
Setup's "Edit existing client" selector and Run Check's "Client" selector.

**Tech Stack:** Python, Streamlit (built-in Material Symbols support via
`icon=":material/name:"` — no new dependency), pytest.

## Global Constraints

- **Zero behavior change for any client that doesn't set a group.**
  `client_group` defaults to `""` on every profile. When a group has
  exactly one profile in it (true for every profile today, since none has
  `client_group` set yet), the picker must render as a *single*
  `st.selectbox` labeled exactly `"Client"`, with that profile's own name
  as one of its options unchanged — this is what keeps every existing
  test across `tests/test_run_check_page.py`,
  `tests/test_enhancio_page.py`, `tests/test_convertr_page.py`, and
  others (which all do
  `next(s for s in at.selectbox if s.label == "Client").set_value("<name>").run()`)
  passing with **no changes to those test files**. Do not rename this
  widget's label, and do not add a suffix/count badge to a singleton
  group's own label — only a group with 2+ profiles gets the
  `" (N regions)"` suffix, and only THEN does a second `st.selectbox`
  appear.
- `list_profile_names()` (existing function, dozens of callers across the
  codebase) is not touched or renamed — `list_profile_groups` is
  additive, alongside it, in the same file.
- Run the affected test file(s) after each task; run the full suite
  (`python -m pytest -q`) before considering the plan done.

---

### Task 1: Icon system — swap sidebar nav emoji for Material Symbols

**Files:**
- Modify: `Summary.py`
- Test: `tests/test_branding.py` (or a new small test file if that one is
  the wrong home — check first)

**Interfaces:**
- No new functions — this only changes the `icon=` string literals passed
  to each `st.Page(...)` call already in `Summary.py`.

- [ ] **Step 1: Write the failing test**

Streamlit's `st.navigation`/`st.Page` icon isn't directly inspectable
through `AppTest` in a simple way, so this task is verified by confirming
the page still loads with no exception and by a direct read of the source
(a real regression test that a future edit can't silently emoji-ify
again):

```python
# tests/test_branding.py (append)
def test_sidebar_nav_uses_material_symbols_not_emoji():
    with open("Summary.py", encoding="utf-8") as f:
        source = f.read()
    # Every icon= argument passed to st.Page must be a :material/...:
    # shorthand, not a raw emoji -- catches a future page addition that
    # reverts to emoji just as easily as it catches this task's own change.
    import re
    icon_args = re.findall(r'icon="([^"]+)"', source)
    assert len(icon_args) >= 10  # one per st.Page call (10 pages + Home)
    assert all(icon.startswith(":material/") for icon in icon_args)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_branding.py -k material_symbols -v`
Expected: FAIL — current icons are emoji (`"✅"`, `"🗂️"`, etc.), not
`:material/...:` strings.

- [ ] **Step 3: Swap the icons**

In `Summary.py`, replace each `icon="<emoji>"` with a Material Symbols
shorthand. Read the current file first to confirm the exact current
emoji-to-page mapping before editing (do not guess at line numbers), then
apply:

| Page | Old icon | New icon |
|---|---|---|
| Home | `"✅"` | `":material/home:"` |
| Client Setup | `"🗂️"` | `":material/folder:"` |
| Run Check | `"▶️"` | `":material/play_arrow:"` |
| Settings | `"⚙️"` | `":material/settings:"` |
| Activity Log | `"📊"` | `":material/bar_chart:"` |
| Box Tracker | `"📦"` | `":material/inventory_2:"` |
| Fuzzy Match | `"🔍"` | `":material/search:"` |
| Convertr | `"🔗"` | `":material/link:"` |
| Enhancio | `"🔗"` | `":material/link:"` |
| Integrate | `"🔗"` | `":material/link:"` |

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_branding.py -k material_symbols -v`
Expected: PASS

- [ ] **Step 5: Manually verify the icons actually render**

Start the dev server (`preview_start` with the `streamlit-app-dev`
config), log in, and look at the sidebar: every nav item must show a
real, recognizable line icon, not a blank/missing-icon gap. Streamlit
silently renders nothing for an unrecognized `:material/name:` string
rather than erroring, so this visual check is the only way to catch a
mistyped icon name. If any icon is blank, check the exact name against
Google's Material Symbols catalog (fonts.google.com/icons) and correct it.

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS, same pre-existing count as before this task (no other
test references these emoji, but confirm nothing unexpected broke).

- [ ] **Step 7: Commit**

```bash
git add Summary.py tests/test_branding.py
git commit -m "Replace sidebar nav emoji with Material Symbols icons"
```

---

### Task 2: `client_group` field on `ClientProfile`

**Files:**
- Modify: `core/models.py`
- Modify: `core/profile_store.py`
- Test: `tests/test_models.py`, `tests/test_profile_store.py`

**Interfaces:**
- Produces: `ClientProfile.client_group: str` (default `""`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_models.py (append)
def test_client_profile_defaults_to_no_client_group():
    profile = ClientProfile(name="X", accumulated_report_path="acc.xlsx")
    assert profile.client_group == ""
```

```python
# tests/test_profile_store.py (append -- read an existing simple-string
# round-trip test first, e.g. search "jira_ticket_key", to match its
# exact fixture style before writing this)
def test_client_group_round_trips_through_save_and_load(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile, load_profile

    profile = ClientProfile(
        name="Autodesk APAC", accumulated_report_path="acc.xlsx", client_group="Autodesk",
    )
    save_profile(profile, get_clients_dir())

    loaded = load_profile("Autodesk APAC", get_clients_dir())
    assert loaded.client_group == "Autodesk"


def test_load_profile_defaults_client_group_for_old_schema_json(tmp_path, monkeypatch):
    # A profile saved before client_group existed has no such key at all
    # -- must default to "" (ungrouped), not crash on the missing key.
    monkeypatch.chdir(tmp_path)
    import json
    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile

    clients_dir = get_clients_dir()
    os.makedirs(clients_dir, exist_ok=True)
    with open(os.path.join(clients_dir, "Old Schema Client.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "Old Schema Client", "accumulated_report_path": "acc.xlsx"}, f)

    loaded = load_profile("Old Schema Client", clients_dir)
    assert loaded.client_group == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_models.py tests/test_profile_store.py -k client_group -v`
Expected: FAIL with `TypeError: ClientProfile.__init__() got an unexpected keyword argument 'client_group'`

- [ ] **Step 3: Add the field**

In `core/models.py`, find `class ClientProfile:` and `jira_ticket_key: str = ""`
(the first plain-string field) and add immediately after `name`/
`accumulated_report_path` (or alongside `jira_ticket_key` — read the
current field order first, place it in the same early cluster of
identity/basics fields, not buried among check-specific config):

```python
    # Groups this profile with other regional profiles for the same brand
    # (e.g. "Autodesk APAC" and "Autodesk EMEA" both set this to
    # "Autodesk") so the client picker in Client Setup/Run Check can offer
    # them as one recognizable group instead of two unrelated flat-list
    # entries. Blank (the default) means "not part of any group" -- this
    # profile is picked exactly as it is today.
    client_group: str = ""
```

- [ ] **Step 4: Wire deserialization into `core/profile_store.py`**

Find `jira_ticket_key=data.get("jira_ticket_key", ""),` inside
`load_profile`'s `ClientProfile(...)` constructor call and add immediately
after it:

```python
        client_group=data.get("client_group", ""),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_models.py tests/test_profile_store.py -k client_group -v`
Expected: PASS

- [ ] **Step 6: Run the full model/profile_store suite**

Run: `python -m pytest tests/test_models.py tests/test_profile_store.py -q`
Expected: PASS, all tests (confirms every existing profile round-trips
identically with the new field defaulting silently to `""`)

- [ ] **Step 7: Commit**

```bash
git add core/models.py core/profile_store.py tests/test_models.py tests/test_profile_store.py
git commit -m "Add client_group field to ClientProfile"
```

---

### Task 3: `list_profile_groups` in `core/profile_store.py`

**Files:**
- Modify: `core/profile_store.py`
- Test: `tests/test_profile_store.py`

**Interfaces:**
- Consumes: `ClientProfile.client_group` (Task 2).
- Produces: `list_profile_groups(clients_dir: str = "clients") -> dict[str, str]`
  (profile name -> its `client_group`, `""` for an ungrouped profile).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_store.py (append)
def test_list_profile_groups_returns_name_to_group_mapping(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile, list_profile_groups

    clients_dir = get_clients_dir()
    save_profile(ClientProfile(name="Autodesk APAC", accumulated_report_path="a.xlsx",
                                client_group="Autodesk"), clients_dir)
    save_profile(ClientProfile(name="Autodesk EMEA", accumulated_report_path="a.xlsx",
                                client_group="Autodesk"), clients_dir)
    save_profile(ClientProfile(name="Solo Client", accumulated_report_path="a.xlsx"), clients_dir)

    assert list_profile_groups(clients_dir) == {
        "Autodesk APAC": "Autodesk", "Autodesk EMEA": "Autodesk", "Solo Client": "",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_profile_store.py -k list_profile_groups -v`
Expected: FAIL with `ImportError: cannot import name 'list_profile_groups'`

- [ ] **Step 3: Implement it**

Read `list_profile_names`/`_looks_like_profile` in `core/profile_store.py`
first (they already open and JSON-parse every candidate file once) and add
a sibling function right after `list_profile_names` that does the same
scan but keeps each parsed dict's `client_group` instead of discarding it:

```python
def list_profile_groups(clients_dir: str = "clients") -> dict[str, str]:
    """Every existing profile's name mapped to its client_group ("" for a
    profile that isn't part of any group) -- the raw data
    core.client_picker groups into a pickable {group: [names]} structure.
    Does its own directory scan (same shape as list_profile_names) rather
    than calling it and re-opening each file a second time.
    """
    if not os.path.isdir(clients_dir):
        return {}
    result: dict[str, str] = {}
    for f in os.listdir(clients_dir):
        if not f.endswith(".json"):
            continue
        path = os.path.join(clients_dir, f)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(data, dict) and "accumulated_report_path" in data:
            result[os.path.splitext(f)[0]] = data.get("client_group", "")
    return result
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_profile_store.py -k list_profile_groups -v`
Expected: PASS

- [ ] **Step 5: Run the full profile_store suite**

Run: `python -m pytest tests/test_profile_store.py -q`
Expected: PASS, all tests

- [ ] **Step 6: Commit**

```bash
git add core/profile_store.py tests/test_profile_store.py
git commit -m "Add list_profile_groups to core/profile_store.py"
```

---

### Task 4: `core/client_picker.py` — pure grouping function

**Files:**
- Create: `core/client_picker.py`
- Test: `tests/test_client_picker.py`

**Interfaces:**
- Produces: `group_profile_names(name_to_group: dict[str, str]) -> dict[str, list[str]]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_client_picker.py
from core.client_picker import group_profile_names


def test_ungrouped_profile_becomes_its_own_singleton_group():
    result = group_profile_names({"Solo Client": ""})
    assert result == {"Solo Client": ["Solo Client"]}


def test_shared_group_collects_all_its_profiles_sorted():
    result = group_profile_names({
        "Autodesk EMEA": "Autodesk", "Autodesk APAC": "Autodesk", "Solo Client": "",
    })
    assert result == {
        "Autodesk": ["Autodesk APAC", "Autodesk EMEA"],
        "Solo Client": ["Solo Client"],
    }


def test_groups_are_sorted_case_insensitively():
    result = group_profile_names({"zebra corp": "", "Acme": ""})
    assert list(result.keys()) == ["Acme", "zebra corp"]


def test_empty_input_returns_empty_dict():
    assert group_profile_names({}) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_client_picker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.client_picker'`

- [ ] **Step 3: Implement it**

```python
# core/client_picker.py
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_client_picker.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/client_picker.py tests/test_client_picker.py
git commit -m "Add group_profile_names to core/client_picker.py"
```

---

### Task 5: `core/client_picker.py` — `render_client_picker` UI function

**Files:**
- Modify: `core/client_picker.py`
- Test: `tests/test_client_picker.py`

**Interfaces:**
- Consumes: `group_profile_names` (Task 4), `list_profile_groups` (Task 3).
- Produces: `render_client_picker(clients_dir: str, key_prefix: str, label: str = "Client") -> str | None`.

- [ ] **Step 1: Write the failing tests**

This needs a real page to mount the widget in (`AppTest` requires a
script file) — read `tests/test_run_check_page.py`'s existing fixture
setup for the exact `save_profile`/`get_clients_dir` pattern, then write a
tiny throwaway host script inline via `tmp_path` to actually mount
`render_client_picker` and exercise its group/profile-step behavior
end to end.

Add `import os` and `from streamlit.testing.v1 import AppTest` to this
test file's existing imports at the top (not appended after the Task 4
tests), then append these test functions:

```python
# tests/test_client_picker.py (new test functions, appended after Task 4's)
def _write_host_script(tmp_path) -> str:
    script = tmp_path / "_host.py"
    script.write_text(
        "import streamlit as st\n"
        "from core.app_settings import get_clients_dir\n"
        "from core.client_picker import render_client_picker\n"
        "st.session_state['picked'] = render_client_picker(get_clients_dir(), key_prefix='test')\n",
        encoding="utf-8",
    )
    return str(script)


def test_single_profile_group_renders_one_selectbox_labeled_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Solo Client", accumulated_report_path="a.xlsx"), get_clients_dir())

    at = AppTest.from_file(_write_host_script(tmp_path), default_timeout=15)
    at.run()
    assert not at.exception
    client_selectboxes = [s for s in at.selectbox if s.label == "Client"]
    assert len(client_selectboxes) == 1
    assert client_selectboxes[0].options == ["Solo Client"]
    assert at.session_state["picked"] == "Solo Client"


def test_multi_profile_group_shows_a_second_step_with_a_region_count(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Autodesk APAC", accumulated_report_path="a.xlsx",
                                client_group="Autodesk"), get_clients_dir())
    save_profile(ClientProfile(name="Autodesk EMEA", accumulated_report_path="a.xlsx",
                                client_group="Autodesk"), get_clients_dir())

    at = AppTest.from_file(_write_host_script(tmp_path), default_timeout=15)
    at.run()
    assert not at.exception
    group_box = next(s for s in at.selectbox if s.label == "Client")
    assert group_box.options == ["Autodesk (2 regions)"]

    group_box.set_value("Autodesk (2 regions)").run()
    assert not at.exception
    profile_box = next(s for s in at.selectbox if s.label == "Client (region)")
    assert set(profile_box.options) == {"Autodesk APAC", "Autodesk EMEA"}
```

(Verified directly: `AppTest` re-runs the whole script on `.set_value(...).run()`
and the newly-appeared second `st.selectbox` is immediately visible in
`at.selectbox` afterward — no `session_state` clearing or other special
handling needed.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_client_picker.py -v`
Expected: FAIL — `render_client_picker` doesn't exist yet.

- [ ] **Step 3: Implement it**

```python
# core/client_picker.py (append)
import os

import streamlit as st

from core.profile_store import list_profile_groups


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
        f"{key} ({len(names)} regions)" if len(names) > 1 else key
        for key, names in groups.items()
    ]
    label_to_key = dict(zip(group_labels, groups.keys()))
    selected_label = st.selectbox(label, group_labels, key=f"{key_prefix}_client_group")
    candidates = groups[label_to_key[selected_label]]

    if len(candidates) == 1:
        return candidates[0]
    return st.selectbox(f"{label} (region)", candidates, key=f"{key_prefix}_client_profile")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_client_picker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/client_picker.py tests/test_client_picker.py
git commit -m "Add render_client_picker two-step group/profile UI"
```

---

### Task 6: Wire the picker into Client Setup

**Files:**
- Modify: `pages/1_Client_Setup.py`
- Test: `tests/test_client_setup_page.py`

**Interfaces:**
- Consumes: `render_client_picker` (Task 5), `ClientProfile.client_group` (Task 2).

- [ ] **Step 1: Write the failing test**

Read `tests/test_client_setup_page.py`'s existing "Edit existing client"
test(s) first (search for `"Edit existing client"`) to match the exact
fixture/save pattern, then add:

```python
def test_saving_a_client_group_persists_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(t for t in at.text_input if t.label == "Client name").set_value("Autodesk APAC").run()
    at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "acc.xlsx")).run()
    next(t for t in at.text_input if t.label == "Client group (optional)").set_value("Autodesk").run()
    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.profile_store import load_profile
    saved = load_profile("Autodesk APAC", get_clients_dir())
    assert saved.client_group == "Autodesk"


def test_edit_existing_client_picker_still_selects_by_exact_name_when_ungrouped(tmp_path, monkeypatch):
    # The load-bearing backward-compat guarantee from this plan's Global
    # Constraints: an ungrouped client (every profile that existed before
    # this task) must still be selectable through one plain selectbox
    # labeled "Client", by its own exact name, with no second step.
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Existing Client", accumulated_report_path="a.xlsx"), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    client_boxes = [s for s in at.selectbox if s.label == "Client"]
    assert len(client_boxes) == 1
    client_boxes[0].set_value("Existing Client").run()
    assert not at.exception
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_client_setup_page.py -k "client_group or edit_existing_client_picker" -v`
Expected: FAIL — no "Client group (optional)" field exists yet, and the
"Edit existing client" selector isn't wired to the new picker yet (this
second test may already pass against the CURRENT flat selectbox — that's
fine, it's here to lock in the behavior through the coming change, not
prove a current gap).

- [ ] **Step 3: Add the "Client group" field and wire the picker**

Read the current "Client name" text input and the current
`selected_name = st.selectbox("Client", existing)` line in
`pages/1_Client_Setup.py` directly first (search `"Client name"` and
`"Edit existing client"`) before editing, then:

1. Add a new `st.text_input("Client group (optional)", value=profile.client_group if profile else "", key="client_group_input", help="Groups this profile with other regional profiles for the same brand (e.g. \"Autodesk APAC\" and \"Autodesk EMEA\" both set this to \"Autodesk\") so the client picker offers them as one group instead of two unrelated entries. Leave blank if this client isn't split by region.")` directly below the existing "Client name" input.
2. Replace `selected_name = st.selectbox("Client", existing)` with
   `selected_name = render_client_picker(get_clients_dir(), key_prefix="client_setup")` — add
   `from core.client_picker import render_client_picker` to this file's
   imports. `existing` (the `_cached_profile_names(...)` result) is no
   longer needed for this selectbox specifically — check whether it's
   still used elsewhere in this file before removing it; if it's only used
   here, remove the now-dead `_cached_profile_names` call too, but leave
   `list_profile_names`'s import alone if anything else in the file still
   needs it.
3. In the `ClientProfile(...)` save constructor call (search for
   `jira_ticket_key=jira_ticket_key.strip()` or similar to find it), add
   `client_group=client_group_input.strip(),` as a sibling argument.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_client_setup_page.py -k "client_group or edit_existing_client_picker" -v`
Expected: PASS

- [ ] **Step 5: Run the full Client Setup suite**

Run: `python -m pytest tests/test_client_setup_page.py -q`
Expected: PASS, all tests (including every pre-existing "Edit existing
client" test — confirms the picker swap is truly transparent for every
already-tested ungrouped-client scenario)

- [ ] **Step 6: Commit**

```bash
git add pages/1_Client_Setup.py tests/test_client_setup_page.py
git commit -m "Add client group field and wire the shared client picker into Client Setup"
```

---

### Task 7: Wire the picker into Run Check

**Files:**
- Modify: `pages/2_Run_Check.py`
- Test: `tests/test_run_check_page.py`

**Interfaces:**
- Consumes: `render_client_picker` (Task 5).

- [ ] **Step 1: Write the failing test**

```python
def test_client_picker_groups_regional_profiles_on_run_check(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Autodesk APAC", accumulated_report_path="a.xlsx",
                                client_group="Autodesk"), get_clients_dir())
    save_profile(ClientProfile(name="Autodesk EMEA", accumulated_report_path="a.xlsx",
                                client_group="Autodesk"), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    group_box = next(s for s in at.selectbox if s.label == "Client")
    assert group_box.options == ["Autodesk (2 regions)"]


def test_client_picker_still_selects_ungrouped_clients_by_exact_name_on_run_check(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Existing Client", accumulated_report_path="a.xlsx"), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    client_boxes = [s for s in at.selectbox if s.label == "Client"]
    assert len(client_boxes) == 1
    client_boxes[0].set_value("Existing Client").run()
    assert not at.exception
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_run_check_page.py -k client_picker -v`
Expected: FAIL — Run Check's selector isn't wired to the new picker yet.

- [ ] **Step 3: Wire the picker**

Read the current `profile_names = _cached_profile_names(...)` /
`client_name = st.selectbox("Client", profile_names)` block in
`pages/2_Run_Check.py` directly first (search `st.selectbox("Client"`),
then replace it:

```python
from core.client_picker import render_client_picker  # add to this file's imports

client_name = render_client_picker(get_clients_dir(), key_prefix="run_check")
if client_name is None:
    st.warning("No client profiles found. Create one on the Client Setup page first.")
    st.stop()
```

placed where the old `profile_names = ...` / empty-check / `st.selectbox`
block was — keep the `col_client, col_clear = st.columns(...)` layout and
the "🔄 Clear" button exactly as they are today, just swap what fills
`col_client`. Remove the now-unused `_cached_profile_names`/
`_clients_dir_mtime` pair in this file if nothing else in
`pages/2_Run_Check.py` still calls them — check first.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_check_page.py -k client_picker -v`
Expected: PASS

- [ ] **Step 5: Run the full Run Check suite**

Run: `python -m pytest tests/test_run_check_page.py -q`
Expected: PASS, all tests (this is the highest-risk task in the plan —
Run Check has the largest number of existing tests that select "Client"
by exact name; this confirms every one of them still works unchanged)

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: everything passes except the 2 pre-existing, unrelated
`tests/test_end_to_end_basware.py` errors — this specifically also
re-confirms every OTHER page's own "Client" selectbox tests (Enhancio,
Convertr, Box Tracker, etc.) still pass, since none of them were touched
by this plan but all of them select "Client" by exact name the same way.

- [ ] **Step 7: Commit**

```bash
git add pages/2_Run_Check.py tests/test_run_check_page.py
git commit -m "Wire the shared client picker into Run Check"
```

## Self-Review Notes

- **Spec coverage:** this plan covers the two Phase 1 items from
  `docs/superpowers/specs/2026-09-28-ui-redesign-design.md` that have
  concrete, immediately-shippable payoff on their own: the icon system and
  the client-group picker. The card/chip/empty-state component-building
  and the Client Setup save-spinner extension are deliberately deferred to
  the Phase 2 plan (Client Setup restructure), where they'll be built
  against real usage instead of speculatively now — building a shared
  component library with no real caller yet risks designing the wrong
  API and reworking it once Phase 2 actually needs it.
- **Type consistency:** `group_profile_names`'s return shape
  (`dict[str, list[str]]`) matches between Task 4's definition and Task
  5's consumption. `render_client_picker`'s signature
  (`clients_dir, key_prefix, label="Client") -> str | None`) matches
  between Task 5's definition and Tasks 6-7's call sites.
- **Backward compatibility is the load-bearing property of this whole
  plan** — re-stated here because it's easy to lose sight of while
  implementing task by task: every profile that exists today has
  `client_group == ""`, so `group_profile_names` puts every one of them in
  its own singleton group, so `render_client_picker` renders exactly one
  `st.selectbox` labeled `"Client"` with that profile's own name as an
  option, exactly like today. Task 6 and Task 7's own test suites (the
  FULL existing `tests/test_client_setup_page.py` and
  `tests/test_run_check_page.py`, plus every other page's tests that
  select "Client" the same way) are what actually prove this, not a new
  assertion — if any of those pre-existing tests need to change to pass,
  something in this plan's design has gone wrong and needs to be revisited
  before continuing, not patched around in the test.
