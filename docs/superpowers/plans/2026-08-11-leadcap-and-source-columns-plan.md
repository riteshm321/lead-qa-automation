# Leadcap Company Pass, Per-Source Columns & Run-Check-Only Leads File Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a company-name leadcap pass with CID auto-detection, move Domain/Company/Email column selection to be per-source (not per-check) across Exclusion/TAL/Suppression/Dedupe with a native file-browse button, and move the New Leads file + column mapping entirely onto the Run Check page.

**Architecture:** `LeadcapConfig` gains a second, company-based pass that only evaluates leads already past the domain pass. `ReferenceSource` grows per-source `domain_column`/`company_column`/`email_column` fields, and Suppression/Dedupe converge onto the same `sources: list[ReferenceSource]` shape Exclusion/TAL already use, so all four checks share one multi-source, CID-scoped, union-matching code path. A new `core/file_browser.py` wraps `tkinter.filedialog` for a native "Browse..." button reusable across every file-path field. Client Setup drops its Field Mapping section entirely; Run Check gains an inline mapping step that only appears when needed and persists itself into the profile.

**Tech Stack:** Python 3, Streamlit, pandas, openpyxl, tkinter (standard library, ships with Windows Python) — no new third-party dependencies.

## Global Constraints

- Leadcap's company-name pass only evaluates leads that already passed the domain pass — a lead gets at most one leadcap reason: `"Leadcap exceeded"` (domain) or `"Leadcap Exceed - By Company Name"` (company).
- Leadcap company matching is exact, case-insensitive, and whitespace-trimmed — NOT fuzzy (explicit user decision, do not reuse `company_names_match`).
- A `ReferenceSource` with an empty `cids` list applies to every lead regardless of CID; non-empty `cids` scopes it to only those leads. This CID-scoping and union-matching semantics (already built for Exclusion/TAL) must be replicated identically for Suppression and Dedupe.
- `domain_column`/`company_column`/`email_column` are now per-`ReferenceSource` fields, not per-check config fields — every check's config drops its own copies of these.
- No migration path is needed for existing saved profiles — none currently exist in `clients/` (git-ignored), consistent with prior work on this project.
- Full test suite must pass after every task (`python -m pytest -v`); the baseline before this plan is 67 passing.
- No automated test exists (or is expected) for Streamlit page behavior or for the native file-browse dialog's actual GUI — these are verified by reading the code and, where the implementer has interactive browser access, by running the app. The `browse_for_file()` function itself IS testable via mocking `tkinter`, since it's a plain Python function, not a Streamlit widget.

---

## Task 1: Leadcap — Company-Name Pass

**Files:**
- Modify: `core/models.py` (only the `LeadcapConfig` class)
- Modify: `core/checks/leadcap.py`
- Modify: `tests/checks/test_leadcap.py`

**Interfaces:**
- Produces: `LeadcapConfig` gains `check_company_name: bool = False` and `purchased_report_company_column: str = "Company"`, inserted after `segments` and before `purchased_report_cid_column`.
- Produces: `check_leadcap(new_leads, field_mapping, config, purchased_reports) -> CheckOutcome` — same signature as before, internal logic gains a second pass.

- [ ] **Step 1: Write the failing tests**

Add these to `tests/checks/test_leadcap.py` (keep all existing tests in the file — these are additions):

```python
def test_leadcap_company_pass_fails_when_passed_domain_but_exceeds_company():
    config = LeadcapConfig(enabled=True, segmented=True, check_company_name=True, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778", "98779"], cap=3),
    ])
    purchased = pd.DataFrame({
        "Campaign ID": ["98778", "98778", "98778", "98779"],
        "Email": ["a1@one.com", "a2@two.com", "a3@three.com", "b1@four.com"],
        "Company": ["Acme Corp", "Acme Corp", "Acme Corp", "Other Co"],
    })
    new_leads = pd.DataFrame([
        {"CID": "98778", "emailaddress": "new@brandnewdomain.com", "company": "Acme Corp"},
    ])

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert outcome.fail[0] == "Leadcap Exceed - By Company Name"


def test_leadcap_company_pass_skipped_when_domain_already_failed():
    config = LeadcapConfig(enabled=True, segmented=True, check_company_name=True, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778"], cap=1),
    ])
    purchased = pd.DataFrame({
        "Campaign ID": ["98778"],
        "Email": ["existing@samedomain.com"],
        "Company": ["Totally Different Co"],
    })
    new_leads = pd.DataFrame([
        {"CID": "98778", "emailaddress": "new@samedomain.com", "company": "Totally Different Co"},
    ])

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert outcome.fail[0] == "Leadcap exceeded"


def test_leadcap_company_pass_not_evaluated_when_toggle_off():
    config = LeadcapConfig(enabled=True, segmented=True, check_company_name=False, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778"], cap=1),
    ])
    purchased = pd.DataFrame({
        "Campaign ID": ["98778"],
        "Email": ["existing@other.com"],
        "Company": ["Acme Corp"],
    })
    new_leads = pd.DataFrame([
        {"CID": "98778", "emailaddress": "new@newdomain.com", "company": "Acme Corp"},
    ])

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert outcome.fail == {}


def test_leadcap_company_match_is_exact_case_insensitive_trimmed():
    config = LeadcapConfig(enabled=True, segmented=True, check_company_name=True, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778"], cap=1),
    ])
    purchased = pd.DataFrame({
        "Campaign ID": ["98778"],
        "Email": ["existing@other.com"],
        "Company": ["  Acme Corp  "],
    })
    new_leads = pd.DataFrame([
        {"CID": "98778", "emailaddress": "new@newdomain.com", "company": "acme corp"},
    ])

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert outcome.fail[0] == "Leadcap Exceed - By Company Name"


def test_leadcap_company_near_match_does_not_count_not_fuzzy():
    config = LeadcapConfig(enabled=True, segmented=True, check_company_name=True, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778"], cap=1),
    ])
    purchased = pd.DataFrame({
        "Campaign ID": ["98778"],
        "Email": ["existing@other.com"],
        "Company": ["Acme Corporation"],
    })
    new_leads = pd.DataFrame([
        {"CID": "98778", "emailaddress": "new@newdomain.com", "company": "Acme Corp"},
    ])

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert outcome.fail == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/checks/test_leadcap.py -v`
Expected: FAIL — `TypeError: LeadcapConfig.__init__() got an unexpected keyword argument 'check_company_name'`

- [ ] **Step 3: Update `LeadcapConfig` in `core/models.py`**

Find the existing `LeadcapConfig` class and replace it with:

```python
@dataclass
class LeadcapConfig:
    enabled: bool = False
    segmented: bool = False
    flat_cap: Optional[int] = None
    segments: list[LeadcapSegment] = field(default_factory=list)
    check_company_name: bool = False
    purchased_report_cid_column: str = "Campaign ID"
    purchased_report_email_column: str = "Email"
    purchased_report_company_column: str = "Company"
```

- [ ] **Step 4: Rewrite `core/checks/leadcap.py`**

```python
import pandas as pd

from core.check_result import CheckOutcome
from core.matching import extract_domain
from core.models import FieldMapping, LeadcapConfig


def _resolve_scope(cid: str, config: LeadcapConfig):
    if config.segmented:
        segment = next((s for s in config.segments if cid in s.cids), None)
        if segment is None:
            return None, None, None
        return segment.name, segment.cap, segment.cids
    return "_flat_", config.flat_cap, None


def check_leadcap(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: LeadcapConfig,
    purchased_reports: dict[str, pd.DataFrame],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    for idx, row in new_leads.iterrows():
        cid = str(row.get(field_mapping.cid, "")).strip()
        report_key, cap, relevant_cids = _resolve_scope(cid, config)
        if report_key is None:
            continue

        report = purchased_reports.get(report_key)
        if report is None or cap is None or config.purchased_report_cid_column not in report.columns:
            continue

        cid_col = report[config.purchased_report_cid_column].astype(str).str.strip()
        cid_mask = cid_col.isin(relevant_cids) if relevant_cids is not None else (cid_col == cid)

        domain_pass_failed = False
        if config.purchased_report_email_column in report.columns:
            lead_domain = extract_domain(str(row.get(field_mapping.email, "")))
            domain_col = report[config.purchased_report_email_column].astype(str).map(extract_domain)
            domain_count = (cid_mask & (domain_col == lead_domain)).sum()
            if domain_count >= cap:
                outcome.fail[idx] = "Leadcap exceeded"
                domain_pass_failed = True

        if domain_pass_failed:
            continue

        if config.check_company_name and config.purchased_report_company_column in report.columns:
            lead_company = str(row.get(field_mapping.company, "") or "").strip().lower()
            if lead_company:
                company_col = report[config.purchased_report_company_column].astype(str).str.strip().str.lower()
                company_count = (cid_mask & (company_col == lead_company)).sum()
                if company_count >= cap:
                    outcome.fail[idx] = "Leadcap Exceed - By Company Name"

    return outcome


def validate_purchased_report_cids(report: pd.DataFrame, expected_cids: list[str], cid_column: str) -> list[str]:
    actual = set(report[cid_column].astype(str).str.strip().unique())
    expected = set(expected_cids)
    return sorted(actual - expected)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/checks/test_leadcap.py -v`
Expected: PASS (11 tests — 6 existing + 5 new)

- [ ] **Step 6: Commit**

```bash
git add core/models.py core/checks/leadcap.py tests/checks/test_leadcap.py
git commit -m "feat: add leadcap company-name pass, evaluated only after domain pass"
```

---

## Task 2: `ReferenceSource` Per-Source Columns & Config Convergence

**Files:**
- Modify: `core/models.py` (full file)
- Modify: `core/profile_store.py` (full file)
- Modify: `tests/test_models.py`
- Modify: `tests/test_profile_store.py`

**Interfaces:**
- Produces: `ReferenceSource(name, file_path, sheet_name, cids=[], domain_column="Domain", company_column="Account Name", email_column="Email")`.
- Produces: `ExclusionConfig(enabled, check_company_name, sources)`, `TalConfig(enabled, check_company_name, sources)` — `domain_column`/`company_column` REMOVED (now per-source).
- Produces: `SuppressionConfig(enabled, check_domain, check_company_name, check_email, sources)` — `sheet_name`/`domain_column`/`company_column`/`email_column` REMOVED (now per-source).
- Produces: `DedupeListConfig(enabled, sources)` — `sheet_name`/`email_column` REMOVED (now per-source).
- Produces: `ClientProfile` — `suppression_path`/`dedupe_list_path` REMOVED (paths now live inside each source).

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_models.py` in full:

```python
from core.models import (
    FieldMapping, LeadcapSegment, LeadcapConfig, TalConfig,
    ExclusionConfig, ReferenceSource, SuppressionConfig, DedupeListConfig, DuplicateConfig,
    ClientProfile,
)
from core.check_result import CheckOutcome


def test_client_profile_defaults():
    fm = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                       company="company", cid="CID")
    profile = ClientProfile(
        name="Basware",
        accumulated_report_path="sample_data/Basware APAC – Accumulated Report.xlsx",
        field_mapping=fm,
    )
    assert profile.duplicate == DuplicateConfig()
    assert profile.leadcap.enabled is False
    assert profile.tal.sources == []
    assert profile.exclusion.sources == []
    assert profile.suppression.sources == []
    assert profile.dedupe_list.sources == []
    assert profile.field_mapping.email == "emailaddress"


def test_leadcap_segment_equality():
    a = LeadcapSegment(name="AU Geo", cids=["114578"], cap=8)
    b = LeadcapSegment(name="AU Geo", cids=["114578"], cap=8)
    assert a == b


def test_reference_source_defaults_to_applying_everywhere():
    source = ReferenceSource(name="Global", file_path="x.xlsx", sheet_name="Sheet1")
    assert source.cids == []


def test_reference_source_column_defaults():
    source = ReferenceSource(name="Global", file_path="x.xlsx", sheet_name="Sheet1")
    assert source.domain_column == "Domain"
    assert source.company_column == "Account Name"
    assert source.email_column == "Email"


def test_reference_source_equality():
    a = ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"])
    b = ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"])
    assert a == b


def test_check_outcome_defaults_are_independent():
    a = CheckOutcome()
    b = CheckOutcome()
    a.fail[1] = "x"
    assert b.fail == {}
```

Replace `tests/test_profile_store.py` in full:

```python
from core.models import (
    ClientProfile, FieldMapping, LeadcapConfig, LeadcapSegment,
    TalConfig, ExclusionConfig, ReferenceSource, SuppressionConfig, DedupeListConfig,
)
from core.profile_store import save_profile, load_profile, list_profile_names


def _sample_profile() -> ClientProfile:
    return ClientProfile(
        name="Basware",
        accumulated_report_path="sample_data/Basware APAC – Accumulated Report.xlsx",
        field_mapping=FieldMapping(email="emailaddress", first_name="firstname",
                                    last_name="lastname", company="company", cid="CID"),
        leadcap=LeadcapConfig(enabled=True, segmented=True, check_company_name=True, segments=[
            LeadcapSegment(name="AU Geo", cids=["114578"], cap=8),
            LeadcapSegment(name="IN Geo", cids=["114568"], cap=5),
        ]),
        tal=TalConfig(enabled=True, sources=[
            ReferenceSource(name="Global TAL", file_path="sample_data/tal.xlsx", sheet_name="Sheet1"),
        ]),
        exclusion=ExclusionConfig(enabled=True, sources=[
            ReferenceSource(name="Global Exclusion", file_path="sample_data/Basware -Exclusion List.xlsx",
                             sheet_name="Exclusion"),
            ReferenceSource(name="EMEA Exclusion", file_path="sample_data/emea_exclusion.xlsx",
                             sheet_name="Sheet1", cids=["114578", "114579"],
                             domain_column="Website", company_column="Company"),
        ]),
        suppression=SuppressionConfig(enabled=True, check_domain=True, sources=[
            ReferenceSource(name="Global Suppression", file_path="sample_data/suppression.xlsx", sheet_name="Sheet1"),
        ]),
        dedupe_list=DedupeListConfig(enabled=True, sources=[
            ReferenceSource(name="Global Dedupe", file_path="sample_data/dedupe.xlsx", sheet_name="Sheet1"),
        ]),
    )


def test_save_and_load_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()

    saved_path = save_profile(profile, clients_dir=clients_dir)
    assert saved_path.endswith("Basware.json")

    loaded = load_profile("Basware", clients_dir=clients_dir)
    assert loaded == profile


def test_list_profile_names(tmp_path):
    clients_dir = str(tmp_path / "clients")
    save_profile(_sample_profile(), clients_dir=clients_dir)
    assert list_profile_names(clients_dir=clients_dir) == ["Basware"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_models.py tests/test_profile_store.py -v`
Expected: FAIL — `TypeError: ReferenceSource.__init__() got an unexpected keyword argument 'domain_column'`

- [ ] **Step 3: Replace `core/models.py` in full**

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FieldMapping:
    email: str
    first_name: str
    last_name: str
    company: str
    cid: str


@dataclass
class LeadcapSegment:
    name: str
    cids: list[str]
    cap: int


@dataclass
class LeadcapConfig:
    enabled: bool = False
    segmented: bool = False
    flat_cap: Optional[int] = None
    segments: list[LeadcapSegment] = field(default_factory=list)
    check_company_name: bool = False
    purchased_report_cid_column: str = "Campaign ID"
    purchased_report_email_column: str = "Email"
    purchased_report_company_column: str = "Company"


@dataclass
class ReferenceSource:
    name: str
    file_path: str
    sheet_name: str
    cids: list[str] = field(default_factory=list)
    domain_column: str = "Domain"
    company_column: str = "Account Name"
    email_column: str = "Email"


@dataclass
class TalConfig:
    enabled: bool = False
    check_company_name: bool = False
    sources: list[ReferenceSource] = field(default_factory=list)


@dataclass
class ExclusionConfig:
    enabled: bool = False
    check_company_name: bool = False
    sources: list[ReferenceSource] = field(default_factory=list)


@dataclass
class SuppressionConfig:
    enabled: bool = False
    check_domain: bool = False
    check_company_name: bool = False
    check_email: bool = False
    sources: list[ReferenceSource] = field(default_factory=list)


@dataclass
class DuplicateConfig:
    enabled: bool = False


@dataclass
class DedupeListConfig:
    enabled: bool = False
    sources: list[ReferenceSource] = field(default_factory=list)


@dataclass
class ClientProfile:
    name: str
    accumulated_report_path: str
    accumulated_tab_name: str = "Accumulated"
    refund_tab_name: str = "Refund"
    field_mapping: Optional[FieldMapping] = None
    duplicate: DuplicateConfig = field(default_factory=DuplicateConfig)
    leadcap: LeadcapConfig = field(default_factory=LeadcapConfig)
    exclusion: ExclusionConfig = field(default_factory=ExclusionConfig)
    tal: TalConfig = field(default_factory=TalConfig)
    suppression: SuppressionConfig = field(default_factory=SuppressionConfig)
    dedupe_list: DedupeListConfig = field(default_factory=DedupeListConfig)
```

- [ ] **Step 4: Replace `core/profile_store.py` in full**

```python
import dataclasses
import json
import os

from core.models import (
    ClientProfile, FieldMapping, LeadcapConfig, LeadcapSegment,
    TalConfig, ExclusionConfig, SuppressionConfig,
    DuplicateConfig, DedupeListConfig, ReferenceSource,
)


def _profile_path(name: str, clients_dir: str) -> str:
    return os.path.join(clients_dir, f"{name}.json")


def save_profile(profile: ClientProfile, clients_dir: str = "clients") -> str:
    os.makedirs(clients_dir, exist_ok=True)
    path = _profile_path(profile.name, clients_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dataclasses.asdict(profile), f, indent=2)
    return path


def load_profile(name: str, clients_dir: str = "clients") -> ClientProfile:
    path = _profile_path(name, clients_dir)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    fm = data.get("field_mapping")
    field_mapping = FieldMapping(**fm) if fm else None

    leadcap = data.get("leadcap") or {}
    leadcap["segments"] = [LeadcapSegment(**s) for s in leadcap.get("segments", [])]

    exclusion = data.get("exclusion") or {}
    exclusion["sources"] = [ReferenceSource(**s) for s in exclusion.get("sources", [])]

    tal = data.get("tal") or {}
    tal["sources"] = [ReferenceSource(**s) for s in tal.get("sources", [])]

    suppression = data.get("suppression") or {}
    suppression["sources"] = [ReferenceSource(**s) for s in suppression.get("sources", [])]

    dedupe_list = data.get("dedupe_list") or {}
    dedupe_list["sources"] = [ReferenceSource(**s) for s in dedupe_list.get("sources", [])]

    return ClientProfile(
        name=data["name"],
        accumulated_report_path=data["accumulated_report_path"],
        accumulated_tab_name=data.get("accumulated_tab_name", "Accumulated"),
        refund_tab_name=data.get("refund_tab_name", "Refund"),
        field_mapping=field_mapping,
        duplicate=DuplicateConfig(**(data.get("duplicate") or {})),
        leadcap=LeadcapConfig(**leadcap),
        exclusion=ExclusionConfig(**exclusion),
        tal=TalConfig(**tal),
        suppression=SuppressionConfig(**suppression),
        dedupe_list=DedupeListConfig(**dedupe_list),
    )


def list_profile_names(clients_dir: str = "clients") -> list[str]:
    if not os.path.isdir(clients_dir):
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(clients_dir)
        if f.endswith(".json")
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py tests/test_profile_store.py -v`
Expected: PASS (8 tests — 6 in test_models.py, 2 in test_profile_store.py)

Note: this task will break `core/checks/exclusion.py`, `core/checks/tal.py`, `core/checks/suppression.py`, `core/checks/dedupe_list.py`, `core/pipeline.py`, `pages/1_Client_Setup.py`, `pages/2_Run_Check.py`, and their tests (they reference removed config-level `domain_column`/`company_column`/`sheet_name`/`email_column` fields, and `ClientProfile.suppression_path`/`dedupe_list_path`). This is expected — Tasks 3–9 fix each in turn. Running the full suite now will show failures elsewhere; that's fine.

- [ ] **Step 6: Commit**

```bash
git add core/models.py core/profile_store.py tests/test_models.py tests/test_profile_store.py
git commit -m "feat: move domain/company/email column selection to per-source, converge Suppression/Dedupe onto ReferenceSource"
```

---

## Task 3: Exclusion & TAL Check Logic — Per-Source Columns

**Files:**
- Modify: `core/checks/exclusion.py`
- Modify: `core/checks/tal.py`
- Modify: `tests/checks/test_exclusion.py`
- Modify: `tests/checks/test_tal.py`

**Interfaces:**
- Consumes: `core.models.ReferenceSource` with its new `domain_column`/`company_column` fields (Task 2).
- Produces: `check_exclusion`/`check_tal` — same signatures as before; internal logic reads `source.domain_column`/`source.company_column` per source instead of `config.domain_column`/`config.company_column`.

- [ ] **Step 1: Add new tests (existing tests in both files are unaffected by this change and need no edits, since `ReferenceSource`'s new column defaults — "Domain"/"Account Name" — match what the existing fixtures already relied on at the config level)**

Add to `tests/checks/test_exclusion.py`:

```python
def test_sources_with_different_column_names_each_use_their_own():
    df_a = pd.DataFrame([{"Domain": "a.com", "Account Name": "A Co"}])
    df_b = pd.DataFrame([{"Website": "b.com", "Company": "B Co"}])
    config = ExclusionConfig(enabled=True, sources=[
        ReferenceSource(name="A", file_path="a.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="B", file_path="b.xlsx", sheet_name="Sheet1",
                         domain_column="Website", company_column="Company"),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@b.com", "company": "B Co", "CID": "1"}])

    outcome = check_exclusion(new_leads, FM, config, {"A": df_a, "B": df_b}, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - domain"
```

Add to `tests/checks/test_tal.py`:

```python
def test_sources_with_different_column_names_each_use_their_own():
    df_a = pd.DataFrame([{"Domain": "a.com", "Account Name": "A Co"}])
    df_b = pd.DataFrame([{"Website": "b.com", "Company": "B Co"}])
    config = TalConfig(enabled=True, sources=[
        ReferenceSource(name="A", file_path="a.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="B", file_path="b.xlsx", sheet_name="Sheet1",
                         domain_column="Website", company_column="Company"),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@b.com", "company": "B Co", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"A": df_a, "B": df_b}, alias_groups=[])

    assert outcome.fail == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/checks/test_exclusion.py tests/checks/test_tal.py -v`
Expected: `test_sources_with_different_column_names_each_use_their_own` FAILs in both files (current code reads `config.domain_column`, which no longer exists on `ExclusionConfig`/`TalConfig` after Task 2 — `AttributeError: 'ExclusionConfig' object has no attribute 'domain_column'`)

- [ ] **Step 3: Update `core/checks/exclusion.py`**

```python
import pandas as pd

from core.check_result import CheckOutcome
from core.matching import extract_domain, company_names_match
from core.models import FieldMapping, ExclusionConfig


def _applicable_sources(cid: str, config: ExclusionConfig) -> list:
    return [s for s in config.sources if not s.cids or cid in s.cids]


def check_exclusion(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: ExclusionConfig,
    sources_data: dict[str, pd.DataFrame],
    alias_groups: list[list[str]],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    for idx, row in new_leads.iterrows():
        cid = str(row.get(field_mapping.cid, "")).strip()
        applicable = _applicable_sources(cid, config)
        if not applicable:
            continue

        domains: set[str] = set()
        companies: list[str] = []
        for source in applicable:
            df = sources_data.get(source.name)
            if df is None:
                continue
            if source.domain_column in df.columns:
                domains |= set(df[source.domain_column].astype(str).str.strip().str.lower())
            if config.check_company_name and source.company_column in df.columns:
                companies.extend(list(df[source.company_column].astype(str)))

        email = str(row.get(field_mapping.email, "") or "")
        domain = extract_domain(email)
        reasons = []

        if domain and domain in domains:
            reasons.append("Exclusion - domain")

        if config.check_company_name:
            company = str(row.get(field_mapping.company, "") or "")
            status = "no_match"
            for candidate in companies:
                result = company_names_match(company, candidate, alias_groups)
                if result.status == "match":
                    status = "match"
                    break
                if result.status == "review":
                    status = "review"
            if status == "match":
                reasons.append("Exclusion - company")
            elif status == "review" and not reasons:
                outcome.review[idx] = "Exclusion - company name ambiguous match"

        if reasons:
            outcome.fail[idx] = "; ".join(reasons)

    return outcome
```

- [ ] **Step 4: Update `core/checks/tal.py`**

```python
import pandas as pd

from core.check_result import CheckOutcome
from core.matching import extract_domain, company_names_match
from core.models import FieldMapping, TalConfig


def _applicable_sources(cid: str, config: TalConfig) -> list:
    return [s for s in config.sources if not s.cids or cid in s.cids]


def check_tal(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: TalConfig,
    sources_data: dict[str, pd.DataFrame],
    alias_groups: list[list[str]],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    for idx, row in new_leads.iterrows():
        cid = str(row.get(field_mapping.cid, "")).strip()
        applicable = _applicable_sources(cid, config)
        if not applicable:
            continue

        domains: set[str] = set()
        companies: list[str] = []
        for source in applicable:
            df = sources_data.get(source.name)
            if df is None:
                continue
            if source.domain_column in df.columns:
                domains |= set(df[source.domain_column].astype(str).str.strip().str.lower())
            if config.check_company_name and source.company_column in df.columns:
                companies.extend(list(df[source.company_column].astype(str)))

        email = str(row.get(field_mapping.email, "") or "")
        domain = extract_domain(email)
        domain_found = domain in domains

        if not domain_found:
            outcome.fail[idx] = "TAL - not found"
            continue

        if config.check_company_name:
            company = str(row.get(field_mapping.company, "") or "")
            status = "no_match"
            for candidate in companies:
                result = company_names_match(company, candidate, alias_groups)
                if result.status == "match":
                    status = "match"
                    break
                if result.status == "review":
                    status = "review"
            if status == "no_match":
                outcome.fail[idx] = "TAL - company not found"
            elif status == "review":
                outcome.review[idx] = "TAL - company name ambiguous match"

    return outcome
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/checks/test_exclusion.py tests/checks/test_tal.py -v`
Expected: PASS (8 tests in test_exclusion.py, 9 tests in test_tal.py)

- [ ] **Step 6: Commit**

```bash
git add core/checks/exclusion.py core/checks/tal.py tests/checks/test_exclusion.py tests/checks/test_tal.py
git commit -m "feat: read domain/company columns per-source in Exclusion and TAL checks"
```

---

## Task 4: Suppression Check — Multi-Source Rewrite

**Files:**
- Modify: `core/checks/suppression.py`
- Modify: `tests/checks/test_suppression.py`

**Interfaces:**
- Consumes: `core.models.ReferenceSource`, `core.models.SuppressionConfig` (Task 2, now sources-based).
- Produces: `check_suppression(new_leads, field_mapping, config, sources_data, alias_groups) -> CheckOutcome` — `sources_data: dict[str, pandas.DataFrame]` keyed by `ReferenceSource.name`, REPLACING the old single `suppression_df` parameter.

- [ ] **Step 1: Replace `tests/checks/test_suppression.py` in full**

```python
import pandas as pd

from core.checks.suppression import check_suppression
from core.models import FieldMapping, SuppressionConfig, ReferenceSource

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

SUPPRESSION_DF = pd.DataFrame([
    {"Account Name": "Acme Corp", "Domain": "acme.com", "Email": "known@acme.com"},
    {"Account Name": "Acme Industries", "Domain": "acmeindustries.com", "Email": "info@acmeindustries.com"},
])

UNIVERSAL_SOURCE = ReferenceSource(name="Global", file_path="unused.xlsx", sheet_name="Sheet1")


def test_domain_check_fails():
    config = SuppressionConfig(enabled=True, check_domain=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@acme.com", "company": "Someone", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"Global": SUPPRESSION_DF}, alias_groups=[])

    assert outcome.fail[0] == "Suppression - domain"


def test_email_check_fails():
    config = SuppressionConfig(enabled=True, check_email=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "known@acme.com", "company": "Someone", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"Global": SUPPRESSION_DF}, alias_groups=[])

    assert outcome.fail[0] == "Suppression - email"


def test_company_check_fails_when_toggled_on():
    config = SuppressionConfig(enabled=True, check_company_name=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@other.com", "company": "Acme Corp", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"Global": SUPPRESSION_DF}, alias_groups=[])

    assert outcome.fail[0] == "Suppression - company"


def test_no_toggles_enabled_produces_no_failures_even_if_row_matches():
    config = SuppressionConfig(enabled=True, check_domain=False, check_company_name=False, check_email=False,
                                sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "known@acme.com", "company": "Acme Corp", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"Global": SUPPRESSION_DF}, alias_groups=[])

    assert outcome.fail == {}


def test_disabled_check_produces_no_failures():
    config = SuppressionConfig(enabled=False, check_domain=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@acme.com", "company": "Someone", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"Global": SUPPRESSION_DF}, alias_groups=[])

    assert outcome.fail == {}


def test_company_name_gray_zone_match_routes_to_review():
    config = SuppressionConfig(enabled=True, check_company_name=True, check_domain=False, check_email=False,
                                sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@other.com", "company": "Acme Industrial", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"Global": SUPPRESSION_DF}, alias_groups=[])

    assert 0 not in outcome.fail
    assert outcome.review[0] == "Suppression - company name ambiguous match"


def test_multiple_sources_are_unioned():
    df_a = pd.DataFrame([{"Domain": "a.com"}])
    df_b = pd.DataFrame([{"Domain": "b.com"}])
    config = SuppressionConfig(enabled=True, check_domain=True, sources=[
        ReferenceSource(name="A", file_path="a.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="B", file_path="b.xlsx", sheet_name="Sheet1"),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@b.com", "company": "X", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"A": df_a, "B": df_b}, alias_groups=[])

    assert outcome.fail[0] == "Suppression - domain"


def test_segment_scoped_source_only_applies_to_its_own_cids():
    df_emea = pd.DataFrame([{"Domain": "emea-suppressed.com"}])
    config = SuppressionConfig(enabled=True, check_domain=True, sources=[
        ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"]),
    ])
    apac_lead = pd.DataFrame([{"emailaddress": "x@emea-suppressed.com", "company": "X", "CID": "200"}])

    outcome = check_suppression(apac_lead, FM, config, {"EMEA": df_emea}, alias_groups=[])

    assert outcome.fail == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/checks/test_suppression.py -v`
Expected: FAIL — `check_suppression()` still takes a single `suppression_df` positional argument, not `sources_data`

- [ ] **Step 3: Rewrite `core/checks/suppression.py`**

```python
import pandas as pd

from core.check_result import CheckOutcome
from core.matching import extract_domain, company_names_match
from core.models import FieldMapping, SuppressionConfig


def _applicable_sources(cid: str, config: SuppressionConfig) -> list:
    return [s for s in config.sources if not s.cids or cid in s.cids]


def check_suppression(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: SuppressionConfig,
    sources_data: dict[str, pd.DataFrame],
    alias_groups: list[list[str]],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    for idx, row in new_leads.iterrows():
        cid = str(row.get(field_mapping.cid, "")).strip()
        applicable = _applicable_sources(cid, config)
        if not applicable:
            continue

        domains: set[str] = set()
        emails: set[str] = set()
        companies: list[str] = []
        for source in applicable:
            df = sources_data.get(source.name)
            if df is None:
                continue
            if config.check_domain and source.domain_column in df.columns:
                domains |= set(df[source.domain_column].astype(str).str.strip().str.lower())
            if config.check_email and source.email_column in df.columns:
                emails |= set(df[source.email_column].astype(str).str.strip().str.lower())
            if config.check_company_name and source.company_column in df.columns:
                companies.extend(list(df[source.company_column].astype(str)))

        email = str(row.get(field_mapping.email, "") or "").strip().lower()
        domain = extract_domain(email)
        reasons = []

        if config.check_domain and domain and domain in domains:
            reasons.append("Suppression - domain")
        if config.check_email and email and email in emails:
            reasons.append("Suppression - email")

        if config.check_company_name:
            company = str(row.get(field_mapping.company, "") or "")
            status = "no_match"
            for candidate in companies:
                result = company_names_match(company, candidate, alias_groups)
                if result.status == "match":
                    status = "match"
                    break
                if result.status == "review":
                    status = "review"
            if status == "match":
                reasons.append("Suppression - company")
            elif status == "review" and not reasons:
                outcome.review[idx] = "Suppression - company name ambiguous match"

        if reasons:
            outcome.fail[idx] = "; ".join(reasons)

    return outcome
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/checks/test_suppression.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add core/checks/suppression.py tests/checks/test_suppression.py
git commit -m "feat: convert Suppression check to multi-source, CID-scoped model"
```

---

## Task 5: Dedupe List Check — Multi-Source Rewrite

**Files:**
- Modify: `core/checks/dedupe_list.py`
- Modify: `tests/checks/test_dedupe_list.py`

**Interfaces:**
- Consumes: `core.models.ReferenceSource`, `core.models.DedupeListConfig` (Task 2, now sources-based).
- Produces: `check_dedupe_list(new_leads, field_mapping, config, sources_data) -> CheckOutcome` — `sources_data: dict[str, pandas.DataFrame]` keyed by `ReferenceSource.name`, REPLACING the old single `dedupe_df` parameter.

- [ ] **Step 1: Replace `tests/checks/test_dedupe_list.py` in full**

```python
import pandas as pd

from core.checks.dedupe_list import check_dedupe_list
from core.models import FieldMapping, DedupeListConfig, ReferenceSource

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

UNIVERSAL_SOURCE = ReferenceSource(name="Global", file_path="unused.xlsx", sheet_name="Sheet1")
DEDUPE_DF = pd.DataFrame([{"Email": "delivered@acme.com"}])


def test_email_in_dedupe_list_fails():
    config = DedupeListConfig(enabled=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "delivered@acme.com", "CID": "1"}])

    outcome = check_dedupe_list(new_leads, FM, config, {"Global": DEDUPE_DF})

    assert outcome.fail[0] == "Dedupe list - email match"


def test_email_not_in_dedupe_list_passes():
    config = DedupeListConfig(enabled=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "new@acme.com", "CID": "1"}])

    outcome = check_dedupe_list(new_leads, FM, config, {"Global": DEDUPE_DF})

    assert outcome.fail == {}


def test_disabled_check_produces_no_failures():
    config = DedupeListConfig(enabled=False, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "delivered@acme.com", "CID": "1"}])

    outcome = check_dedupe_list(new_leads, FM, config, {"Global": DEDUPE_DF})

    assert outcome.fail == {}


def test_multiple_sources_are_unioned():
    df_a = pd.DataFrame([{"Email": "a@delivered.com"}])
    df_b = pd.DataFrame([{"Email": "b@delivered.com"}])
    config = DedupeListConfig(enabled=True, sources=[
        ReferenceSource(name="A", file_path="a.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="B", file_path="b.xlsx", sheet_name="Sheet1"),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "b@delivered.com", "CID": "1"}])

    outcome = check_dedupe_list(new_leads, FM, config, {"A": df_a, "B": df_b})

    assert outcome.fail[0] == "Dedupe list - email match"


def test_segment_scoped_source_only_applies_to_its_own_cids():
    df_emea = pd.DataFrame([{"Email": "delivered@emea.com"}])
    config = DedupeListConfig(enabled=True, sources=[
        ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"]),
    ])
    apac_lead = pd.DataFrame([{"emailaddress": "delivered@emea.com", "CID": "200"}])

    outcome = check_dedupe_list(apac_lead, FM, config, {"EMEA": df_emea})

    assert outcome.fail == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/checks/test_dedupe_list.py -v`
Expected: FAIL — `check_dedupe_list()` still takes a single `dedupe_df` positional argument, not `sources_data`

- [ ] **Step 3: Rewrite `core/checks/dedupe_list.py`**

```python
import pandas as pd

from core.check_result import CheckOutcome
from core.models import FieldMapping, DedupeListConfig


def _applicable_sources(cid: str, config: DedupeListConfig) -> list:
    return [s for s in config.sources if not s.cids or cid in s.cids]


def check_dedupe_list(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: DedupeListConfig,
    sources_data: dict[str, pd.DataFrame],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    for idx, row in new_leads.iterrows():
        cid = str(row.get(field_mapping.cid, "")).strip()
        applicable = _applicable_sources(cid, config)
        if not applicable:
            continue

        emails: set[str] = set()
        for source in applicable:
            df = sources_data.get(source.name)
            if df is None:
                continue
            if source.email_column in df.columns:
                emails |= set(df[source.email_column].astype(str).str.strip().str.lower())

        email = str(row.get(field_mapping.email, "") or "").strip().lower()
        if email and email in emails:
            outcome.fail[idx] = "Dedupe list - email match"

    return outcome
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/checks/test_dedupe_list.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/checks/dedupe_list.py tests/checks/test_dedupe_list.py
git commit -m "feat: convert Dedupe list check to multi-source, CID-scoped model"
```

---

## Task 6: Pipeline — Suppression/Dedupe `reference_data` Keys

**Files:**
- Modify: `core/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `check_suppression`/`check_dedupe_list`'s new `sources_data` parameter (Tasks 4, 5).
- Produces: `run_pipeline`'s `reference_data` dict now expects `"suppression_sources"` (`dict[str, DataFrame]`, replacing `"suppression_df"`) and `"dedupe_sources"` (`dict[str, DataFrame]`, replacing `"dedupe_df"`). `"purchased_reports"`, `"exclusion_sources"`, `"tal_sources"` are unchanged.

- [ ] **Step 1: Update the two affected assertions' setup in `tests/test_pipeline.py`**

The four existing tests in `tests/test_pipeline.py` don't exercise Suppression or Dedupe, so they need no changes. Add one new test proving the key rename:

```python
def test_suppression_and_dedupe_use_sources_keys():
    from core.models import SuppressionConfig, DedupeListConfig, ReferenceSource
    import pandas as pd

    profile = _profile(
        suppression=SuppressionConfig(enabled=True, check_domain=True, sources=[
            ReferenceSource(name="Sup", file_path="unused.xlsx", sheet_name="Sheet1"),
        ]),
        dedupe_list=DedupeListConfig(enabled=True, sources=[
            ReferenceSource(name="Dedupe", file_path="unused.xlsx", sheet_name="Sheet1"),
        ]),
    )
    new_leads = pd.DataFrame([{"emailaddress": "x@suppressed.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    accumulated = pd.DataFrame(columns=["emailaddress", "firstname", "lastname", "company", "CID"])
    suppression_df = pd.DataFrame([{"Domain": "suppressed.com"}])

    result = run_pipeline(
        new_leads, profile, accumulated,
        reference_data={"suppression_sources": {"Sup": suppression_df}, "dedupe_sources": {}},
        alias_groups=[],
    )

    assert result.refund_reasons[0] == "Suppression - domain"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `run_pipeline` still reads `reference_data.get("suppression_df", pd.DataFrame())`, which is now the wrong shape for `check_suppression`'s new `sources_data: dict` parameter, causing `AttributeError: 'DataFrame' object has no attribute 'get'` inside `check_suppression`

- [ ] **Step 3: Update `core/pipeline.py`**

Replace the Suppression and Dedupe blocks:

```python
    if profile.suppression.enabled:
        merge(suppression.check_suppression(new_leads, fm, profile.suppression,
                                             reference_data.get("suppression_sources", {}), alias_groups))

    if profile.dedupe_list.enabled:
        merge(dedupe_list.check_dedupe_list(new_leads, fm, profile.dedupe_list,
                                             reference_data.get("dedupe_sources", {})))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/pipeline.py tests/test_pipeline.py
git commit -m "refactor: rename pipeline reference_data keys for multi-source Suppression/Dedupe"
```

---

## Task 7: CID Auto-Detection & Native File-Browse Helper

**Files:**
- Modify: `core/excel_io.py`
- Create: `core/file_browser.py`
- Create: `tests/test_file_browser.py`
- Modify: `tests/test_excel_io_generic.py`

**Interfaces:**
- Produces: `detect_cids_from_pacing_overview(accumulated_path: str, sheet_name: str = "Pacing Overview") -> list[tuple[str, str]]` in `core/excel_io.py` — returns `(cid, campaign_name)` pairs, scanning for a header cell reading "CID" (case-insensitive) anywhere on the sheet rather than assuming row/column 1, since real Pacing Overview sheets often start their used range partway down and across (e.g. `B2:R14`).
- Produces: `browse_for_file(file_types: list[tuple[str, str]] | None = None) -> str | None` in `core/file_browser.py` — opens a native OS file-picker dialog via `tkinter.filedialog.askopenfilename`, returns the chosen path or `None` if cancelled.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_excel_io_generic.py`:

```python
def test_detect_cids_from_pacing_overview_handles_offset_layout(tmp_path):
    from core.excel_io import detect_cids_from_pacing_overview

    path = str(tmp_path / "accumulated.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pacing Overview"
    # Real sheets often have their used range start at B2, not A1 — header row 3.
    ws["B2"] = "Pacing Overview"
    ws["B3"] = "SR No"
    ws["C3"] = "CID"
    ws["D3"] = "Campaign Segment"
    ws["C4"] = "118118"
    ws["D4"] = "APAC Mgr+ Q3"
    ws["C5"] = "118119"
    ws["D5"] = "EMEA Mgr+ Q3"
    ws["C6"] = "Grand Total"
    wb.save(path)

    pairs = detect_cids_from_pacing_overview(path)

    assert pairs == [("118118", "APAC Mgr+ Q3"), ("118119", "EMEA Mgr+ Q3")]


def test_detect_cids_from_pacing_overview_raises_clear_error_when_no_cid_header(tmp_path):
    from core.excel_io import detect_cids_from_pacing_overview

    path = str(tmp_path / "accumulated.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pacing Overview"
    ws["A1"] = "Nothing relevant here"
    wb.save(path)

    try:
        detect_cids_from_pacing_overview(path)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "CID" in str(exc)


def test_detect_cids_from_pacing_overview_raises_clear_error_when_sheet_missing(tmp_path):
    from core.excel_io import detect_cids_from_pacing_overview

    path = str(tmp_path / "accumulated.xlsx")
    wb = openpyxl.Workbook()
    wb.active.title = "SomeOtherSheet"
    wb.save(path)

    try:
        detect_cids_from_pacing_overview(path)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Pacing Overview" in str(exc)
```

Create `tests/test_file_browser.py`:

```python
import pytest

pytest.importorskip("tkinter")

import core.file_browser as file_browser


class _FakeRoot:
    def withdraw(self):
        pass

    def wm_attributes(self, *args):
        pass

    def destroy(self):
        pass


def test_browse_for_file_returns_selected_path(monkeypatch):
    monkeypatch.setattr(file_browser.tk, "Tk", lambda: _FakeRoot())
    monkeypatch.setattr(file_browser.filedialog, "askopenfilename", lambda **kwargs: "/chosen/path.xlsx")

    result = file_browser.browse_for_file()

    assert result == "/chosen/path.xlsx"


def test_browse_for_file_returns_none_when_cancelled(monkeypatch):
    monkeypatch.setattr(file_browser.tk, "Tk", lambda: _FakeRoot())
    monkeypatch.setattr(file_browser.filedialog, "askopenfilename", lambda **kwargs: "")

    result = file_browser.browse_for_file()

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_excel_io_generic.py tests/test_file_browser.py -v`
Expected: FAIL — `ImportError: cannot import name 'detect_cids_from_pacing_overview' from 'core.excel_io'`, and `ModuleNotFoundError: No module named 'core.file_browser'`

- [ ] **Step 3: Add `detect_cids_from_pacing_overview` to `core/excel_io.py`**

Add this function to the end of `core/excel_io.py` (keep everything else in the file unchanged):

```python
def detect_cids_from_pacing_overview(
    accumulated_path: str,
    sheet_name: str = "Pacing Overview",
) -> list[tuple[str, str]]:
    wb = openpyxl.load_workbook(accumulated_path, read_only=True, data_only=True)
    try:
        if sheet_name not in wb.sheetnames:
            raise ValueError(f"'{accumulated_path}' has no sheet named '{sheet_name}'")
        ws = wb[sheet_name]

        header_row_idx = None
        cid_col_idx = None
        campaign_col_idx = None
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 20)):
            for cell in row:
                if isinstance(cell.value, str) and cell.value.strip().lower() == "cid":
                    header_row_idx = cell.row
                    cid_col_idx = cell.column
            if header_row_idx is not None:
                for cell in row:
                    if isinstance(cell.value, str) and cell.value.strip().lower() in (
                        "campaign segment", "campaign name", "campaign"
                    ):
                        campaign_col_idx = cell.column
                break

        if header_row_idx is None or cid_col_idx is None:
            raise ValueError(f"Could not find a 'CID' column in '{accumulated_path}' [{sheet_name}]")

        pairs: list[tuple[str, str]] = []
        seen: set[str] = set()
        for row in ws.iter_rows(min_row=header_row_idx + 1, max_row=ws.max_row):
            cid_cell = row[cid_col_idx - 1]
            if cid_cell.value is None or str(cid_cell.value).strip() == "":
                continue
            cid = str(cid_cell.value).strip()
            if cid.lower() in ("grand total", "total") or cid in seen:
                continue
            seen.add(cid)
            campaign = ""
            if campaign_col_idx is not None:
                campaign_cell = row[campaign_col_idx - 1]
                if campaign_cell.value is not None:
                    campaign = str(campaign_cell.value).strip()
            pairs.append((cid, campaign or cid))

        return pairs
    finally:
        wb.close()
```

- [ ] **Step 4: Create `core/file_browser.py`**

```python
import tkinter as tk
from tkinter import filedialog


def browse_for_file(file_types: list[tuple[str, str]] | None = None) -> str | None:
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", 1)
    path = filedialog.askopenfilename(
        filetypes=file_types or [("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
    )
    root.destroy()
    return path or None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_excel_io_generic.py tests/test_file_browser.py -v`
Expected: PASS (8 tests in test_excel_io_generic.py — 5 existing + 3 new; 2 in test_file_browser.py, unless `tkinter` isn't installed in this environment, in which case those 2 are SKIPPED, not failed — that's fine)

- [ ] **Step 6: Commit**

```bash
git add core/excel_io.py core/file_browser.py tests/test_excel_io_generic.py tests/test_file_browser.py
git commit -m "feat: add Pacing Overview CID auto-detection and native file-browse helper"
```

---

## Task 8: Client Setup — Full Page Rewrite

**Files:**
- Modify: `pages/1_Client_Setup.py` (full file)

**Interfaces:**
- Consumes: everything from Tasks 1–7 — `LeadcapConfig.check_company_name`, `ReferenceSource`'s per-source columns, `SuppressionConfig`/`DedupeListConfig`'s `sources` field, `detect_cids_from_pacing_overview`, `browse_for_file`.
- Produces: no new functions consumed by later tasks — this is a leaf UI page. Task 9 (Run Check) does NOT import anything from this file.

No automated test for this task — Streamlit pages are verified by running them, consistent with how this page has been handled throughout the project.

- [ ] **Step 1: Replace `pages/1_Client_Setup.py` in full**

```python
import uuid

import streamlit as st

from core.excel_io import list_sheet_names, read_sheet_as_dataframe, detect_cids_from_pacing_overview
from core.file_browser import browse_for_file
from core.models import (
    ClientProfile, DuplicateConfig, LeadcapConfig, LeadcapSegment,
    ExclusionConfig, TalConfig, ReferenceSource, SuppressionConfig, DedupeListConfig,
)
from core.profile_store import save_profile, load_profile, list_profile_names

st.title("Client Setup")


def _path_input_with_browse(label: str, session_key: str, current_value: str) -> str:
    col1, col2 = st.columns([5, 1])
    with col2:
        st.write("")
        if st.button("Browse...", key=f"{session_key}_browse"):
            chosen = browse_for_file()
            if chosen:
                st.session_state[session_key] = chosen
                st.rerun()
    with col1:
        return st.text_input(label, value=current_value, key=session_key)


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
    if st.button(f"Add {label} Source", key=f"{section_key}_add"):
        st.session_state[section_key].append({
            "id": str(uuid.uuid4()), "name": "", "file_path": "", "sheet_name": "", "cids": "",
            "domain_column": "Domain", "company_column": "Account Name", "email_column": "Email",
        })

    remove_id = None
    for src in st.session_state[section_key]:
        row_id = src["id"]
        st.markdown(f"**{label} Source: {src['name'] or '(unnamed)'}**")

        path_key = f"{section_key}_path_{row_id}"
        if st.button("Browse...", key=f"{section_key}_browse_{row_id}"):
            chosen = browse_for_file()
            if chosen:
                st.session_state[path_key] = chosen
                st.rerun()

        src["name"] = st.text_input("Name", value=src["name"], key=f"{section_key}_name_{row_id}")
        src["file_path"] = st.text_input("File path", value=src["file_path"], key=path_key)

        sheet_options: list[str] = []
        if src["file_path"]:
            try:
                sheet_options = list_sheet_names(src["file_path"])
            except Exception as exc:
                st.error(f"Could not read sheets from '{src['file_path']}': {exc}")
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

        if check_domain:
            src["domain_column"] = _column_picker("Domain column", "domain_column", "Domain")
        if check_company:
            src["company_column"] = _column_picker("Company column", "company_column", "Account Name")
        if check_email:
            src["email_column"] = _column_picker("Email column", "email_column", "Email")

        src["cids"] = st.text_input("CIDs this source applies to (comma-separated, blank = applies to all leads)",
                                     value=src["cids"], key=f"{section_key}_cids_{row_id}")

        if st.button("Remove this source", key=f"{section_key}_remove_{row_id}"):
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


existing = list_profile_names()
mode = st.radio("Mode", ["Create new client", "Edit existing client"])

if mode == "Edit existing client" and existing:
    selected_name = st.selectbox("Client", existing)
    profile = load_profile(selected_name)
else:
    selected_name = None
    profile = None

client_name = st.text_input("Client name", value=profile.name if profile else "")

st.header("Reference Files")
accumulated_path = _path_input_with_browse(
    "Accumulated Report path", "accumulated_path_input",
    profile.accumulated_report_path if profile else "")
accumulated_tab_name = st.text_input("Accumulated tab name",
                                      value=profile.accumulated_tab_name if profile else "Accumulated")
refund_tab_name = st.text_input("Refund tab name",
                                 value=profile.refund_tab_name if profile else "Refund")

st.header("Checks")

duplicate_enabled = st.checkbox("Enable Duplicate check", value=profile.duplicate.enabled if profile else False)

st.subheader("Leadcap")
leadcap_enabled = st.checkbox("Enable Leadcap check", value=profile.leadcap.enabled if profile else False)
leadcap_check_company = st.checkbox("Also check Leadcap by company name",
                                     value=profile.leadcap.check_company_name if profile else False)
leadcap_segmented = st.checkbox("Leadcap is segmented by CID", value=profile.leadcap.segmented if profile else False)
leadcap_flat_cap = None
leadcap_segments: list[LeadcapSegment] = []
if leadcap_enabled and not leadcap_segmented:
    leadcap_flat_cap = st.number_input("Flat lead cap", min_value=0, step=1,
                                        value=profile.leadcap.flat_cap if profile and profile.leadcap.flat_cap else 0)
if leadcap_enabled and leadcap_segmented:
    if accumulated_path and st.button("Detect CIDs from Accumulated Report"):
        try:
            detected = detect_cids_from_pacing_overview(accumulated_path)
            st.session_state["leadcap_segments_text"] = "\n".join(f"{name}|{cid}|" for cid, name in detected)
        except Exception as exc:
            st.error(f"Could not detect CIDs from '{accumulated_path}': {exc}")
    st.caption("Define segments as: name | comma-separated CIDs | cap, one per line. "
               "Merge two rows' CIDs together (comma-separated) to share one cap across them.")
    default_text = "\n".join(f"{s.name}|{','.join(s.cids)}|{s.cap}" for s in (profile.leadcap.segments if profile else []))
    segment_text = st.text_area("Leadcap segments", value=default_text, key="leadcap_segments_text")
    for line in segment_text.splitlines():
        if not line.strip():
            continue
        name, cids_str, cap_str = [p.strip() for p in line.split("|")]
        leadcap_segments.append(LeadcapSegment(name=name, cids=[c.strip() for c in cids_str.split(",")],
                                                 cap=int(cap_str) if cap_str else 0))

_profile_identity = f"{mode}::{selected_name or ''}"
if st.session_state.get("_loaded_sources_for") != _profile_identity:
    st.session_state["_loaded_sources_for"] = _profile_identity
    st.session_state["exclusion_sources"] = _sources_to_state(profile.exclusion.sources) if profile else []
    st.session_state["tal_sources"] = _sources_to_state(profile.tal.sources) if profile else []
    st.session_state["suppression_sources"] = _sources_to_state(profile.suppression.sources) if profile else []
    st.session_state["dedupe_sources"] = _sources_to_state(profile.dedupe_list.sources) if profile else []

st.subheader("Exclusion")
exclusion_enabled = st.checkbox("Enable Exclusion check", value=profile.exclusion.enabled if profile else False)
exclusion_check_company = st.checkbox("Also check Exclusion by company name",
                                       value=profile.exclusion.check_company_name if profile else False)
exclusion_sources_result: list[ReferenceSource] = []
if exclusion_enabled:
    exclusion_sources_result = _render_sources_section(
        "exclusion_sources", "Exclusion", check_domain=True, check_company=exclusion_check_company, check_email=False)
if exclusion_enabled and not exclusion_sources_result:
    st.warning("Exclusion is enabled but no sources are configured — this check will do nothing.")

st.subheader("TAL")
tal_enabled = st.checkbox("Enable TAL check", value=profile.tal.enabled if profile else False)
tal_check_company = st.checkbox("Also check TAL by company name", value=profile.tal.check_company_name if profile else False)
tal_sources_result: list[ReferenceSource] = []
if tal_enabled:
    tal_sources_result = _render_sources_section(
        "tal_sources", "TAL", check_domain=True, check_company=tal_check_company, check_email=False)
if tal_enabled and not tal_sources_result:
    st.warning("TAL is enabled but no sources are configured — this check will do nothing.")

st.subheader("Suppression")
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
if suppression_enabled and not suppression_sources_result:
    st.warning("Suppression is enabled but no sources are configured — this check will do nothing.")

st.subheader("Dedupe list")
dedupe_enabled = st.checkbox("Enable Dedupe list check", value=profile.dedupe_list.enabled if profile else False)
dedupe_sources_result: list[ReferenceSource] = []
if dedupe_enabled:
    dedupe_sources_result = _render_sources_section(
        "dedupe_sources", "Dedupe List", check_domain=False, check_company=False, check_email=True)
if dedupe_enabled and not dedupe_sources_result:
    st.warning("Dedupe list is enabled but no sources are configured — this check will do nothing.")

if st.button("Save Client Profile"):
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

    if not client_name:
        st.error("Client name is required.")
    elif _name_error:
        st.error(_name_error)
    else:
        new_profile = ClientProfile(
            name=client_name,
            accumulated_report_path=accumulated_path,
            accumulated_tab_name=accumulated_tab_name or "Accumulated",
            refund_tab_name=refund_tab_name or "Refund",
            field_mapping=profile.field_mapping if profile else None,
            duplicate=DuplicateConfig(enabled=duplicate_enabled),
            leadcap=LeadcapConfig(enabled=leadcap_enabled, segmented=leadcap_segmented,
                                   flat_cap=int(leadcap_flat_cap) if leadcap_flat_cap else None,
                                   segments=leadcap_segments, check_company_name=leadcap_check_company),
            exclusion=ExclusionConfig(enabled=exclusion_enabled, check_company_name=exclusion_check_company,
                                       sources=exclusion_sources_result),
            tal=TalConfig(enabled=tal_enabled, check_company_name=tal_check_company,
                          sources=tal_sources_result),
            suppression=SuppressionConfig(enabled=suppression_enabled, check_domain=suppression_check_domain,
                                           check_company_name=suppression_check_company,
                                           check_email=suppression_check_email,
                                           sources=suppression_sources_result),
            dedupe_list=DedupeListConfig(enabled=dedupe_enabled, sources=dedupe_sources_result),
        )
        saved_path = save_profile(new_profile)
        st.success(f"Saved profile to {saved_path}")
```

Note: `field_mapping=profile.field_mapping if profile else None` — this page never sets or changes field mapping anymore; it only ever preserves whatever the profile already has (or `None` for a brand-new profile), since mapping now happens exclusively on Run Check (Task 9).

- [ ] **Step 2: Static verification**

Run: `python -c "import ast; ast.parse(open('pages/1_Client_Setup.py').read())"`
Expected: no output

Run: `python -m pytest -v`
Expected: PASS — all tests from Tasks 1–7 (this page has no direct tests)

- [ ] **Step 3: Manual verification**

If interactive browser access is available: run the app, enable Leadcap with segmented mode, enter the real `sample_data/Basware APAC – Accumulated Report.xlsx` path, click "Detect CIDs from Accumulated Report," and confirm the segments text area populates with real CIDs and campaign names from that file's Pacing Overview sheet. Enable Exclusion, add a source pointing at `sample_data/Basware -Exclusion List.xlsx`, pick the "Exclusion" sheet, and confirm the Domain column dropdown lists that sheet's real headers (`Account Name`, `Domain`) rather than a hardcoded list. Click "Browse..." next to any file path field and confirm Windows' native file picker opens (if a display is available in this environment) and the chosen path fills the text box. If no interactive access is available, trace the code carefully by hand instead and report honestly which verification was actually performed.

- [ ] **Step 4: Commit**

```bash
git add pages/1_Client_Setup.py
git commit -m "feat: per-source column pickers, CID auto-detection, and native Browse button in Client Setup"
```

---

## Task 9: Run Check — Full Page Rewrite

**Files:**
- Modify: `pages/2_Run_Check.py` (full file)

**Interfaces:**
- Consumes: `core.models.FieldMapping`, `core.profile_store.save_profile` (existing, now also called from this page), everything from Tasks 1–6 (per-source columns, multi-source Suppression/Dedupe, leadcap company pass).

No automated test for this task — Streamlit pages are verified by running them.

- [ ] **Step 1: Replace `pages/2_Run_Check.py` in full**

```python
# pages/2_Run_Check.py
import datetime

import pandas as pd
import streamlit as st

from core.aliases_path import ALIASES_PATH
from core.checks.leadcap import validate_purchased_report_cids
from core.excel_io import read_sheet_as_dataframe, append_leads, backup_file, require_columns
from core.matching import load_alias_groups, add_alias_pair
from core.models import FieldMapping
from core.pipeline import run_pipeline
from core.profile_store import list_profile_names, load_profile, save_profile

st.title("Run Check")

profile_names = list_profile_names()
if not profile_names:
    st.warning("No client profiles found. Create one on the Client Setup page first.")
    st.stop()

client_name = st.selectbox("Client", profile_names)
profile = load_profile(client_name)

new_leads_file = st.file_uploader("New Leads file", type=["xlsx"])

new_leads_df = None
new_leads_headers: list[str] = []
if new_leads_file:
    new_leads_df = pd.read_excel(new_leads_file)
    new_leads_headers = list(new_leads_df.columns)

field_mapping = profile.field_mapping
mapping_valid = (
    field_mapping is not None
    and all(col in new_leads_headers for col in
            [field_mapping.email, field_mapping.first_name, field_mapping.last_name,
             field_mapping.company, field_mapping.cid])
)

if new_leads_file and not mapping_valid:
    st.subheader("Map New Leads columns")
    st.caption("This client's saved mapping doesn't match this file's columns (or none is saved yet) — "
               "map them once, and it'll be remembered for future runs.")

    def _idx(value: str | None) -> int:
        return new_leads_headers.index(value) if value and value in new_leads_headers else 0

    fm_email = st.selectbox("Email column", new_leads_headers, index=_idx(field_mapping.email if field_mapping else None))
    fm_first = st.selectbox("First Name column", new_leads_headers, index=_idx(field_mapping.first_name if field_mapping else None))
    fm_last = st.selectbox("Last Name column", new_leads_headers, index=_idx(field_mapping.last_name if field_mapping else None))
    fm_company = st.selectbox("Company column", new_leads_headers, index=_idx(field_mapping.company if field_mapping else None))
    fm_cid = st.selectbox("CID column", new_leads_headers, index=_idx(field_mapping.cid if field_mapping else None))

    if st.button("Save column mapping for this client"):
        profile.field_mapping = FieldMapping(email=fm_email, first_name=fm_first, last_name=fm_last,
                                              company=fm_company, cid=fm_cid)
        save_profile(profile)
        st.success("Column mapping saved for this client.")
        st.rerun()

purchased_reports: dict[str, pd.DataFrame] = {}
if profile.leadcap.enabled:
    st.subheader("Leadcap: Purchased Lead Report(s)")
    leadcap_required_cols = [profile.leadcap.purchased_report_cid_column, profile.leadcap.purchased_report_email_column]
    if profile.leadcap.check_company_name:
        leadcap_required_cols.append(profile.leadcap.purchased_report_company_column)
    if profile.leadcap.segmented:
        for segment in profile.leadcap.segments:
            uploaded = st.file_uploader(f"Purchased Lead Report for: {segment.name} — CID {', '.join(segment.cids)}",
                                         type=["csv"], key=f"purchased_{segment.name}")
            if uploaded:
                df = pd.read_csv(uploaded)
                try:
                    require_columns(df, leadcap_required_cols, segment.name)
                    unexpected = validate_purchased_report_cids(df, segment.cids, profile.leadcap.purchased_report_cid_column)
                    if unexpected:
                        st.warning(f"'{segment.name}' file contains unexpected CIDs {unexpected} — wrong file?")
                    purchased_reports[segment.name] = df
                except ValueError as exc:
                    st.error(str(exc))
    else:
        uploaded = st.file_uploader("Purchased Lead Report", type=["csv"], key="purchased_flat")
        if uploaded:
            df = pd.read_csv(uploaded)
            try:
                require_columns(df, leadcap_required_cols, "Purchased Lead Report")
                purchased_reports["_flat_"] = df
            except ValueError as exc:
                st.error(str(exc))

if st.button("Run Check") and new_leads_file:
    if not mapping_valid:
        st.error("Map the New Leads columns above before running the check.")
        st.stop()
    try:
        new_leads = new_leads_df
        accumulated_leads = read_sheet_as_dataframe(profile.accumulated_report_path, profile.accumulated_tab_name)

        reference_data: dict = {"purchased_reports": purchased_reports}
        if profile.exclusion.enabled:
            exclusion_sources_data: dict[str, pd.DataFrame] = {}
            for source in profile.exclusion.sources:
                df = read_sheet_as_dataframe(source.file_path, source.sheet_name)
                require_columns(df, [source.domain_column], f"{source.file_path} [{source.sheet_name}]")
                exclusion_sources_data[source.name] = df
            reference_data["exclusion_sources"] = exclusion_sources_data
        if profile.tal.enabled:
            tal_sources_data: dict[str, pd.DataFrame] = {}
            for source in profile.tal.sources:
                df = read_sheet_as_dataframe(source.file_path, source.sheet_name)
                require_columns(df, [source.domain_column], f"{source.file_path} [{source.sheet_name}]")
                tal_sources_data[source.name] = df
            reference_data["tal_sources"] = tal_sources_data
        if profile.suppression.enabled:
            suppression_sources_data: dict[str, pd.DataFrame] = {}
            for source in profile.suppression.sources:
                df = read_sheet_as_dataframe(source.file_path, source.sheet_name)
                required_cols = []
                if profile.suppression.check_domain:
                    required_cols.append(source.domain_column)
                if profile.suppression.check_email:
                    required_cols.append(source.email_column)
                if required_cols:
                    require_columns(df, required_cols, f"{source.file_path} [{source.sheet_name}]")
                suppression_sources_data[source.name] = df
            reference_data["suppression_sources"] = suppression_sources_data
        if profile.dedupe_list.enabled:
            dedupe_sources_data: dict[str, pd.DataFrame] = {}
            for source in profile.dedupe_list.sources:
                df = read_sheet_as_dataframe(source.file_path, source.sheet_name)
                require_columns(df, [source.email_column], f"{source.file_path} [{source.sheet_name}]")
                dedupe_sources_data[source.name] = df
            reference_data["dedupe_sources"] = dedupe_sources_data

        alias_groups = load_alias_groups(ALIASES_PATH)
        result = run_pipeline(new_leads, profile, accumulated_leads, reference_data, alias_groups)

        st.session_state["run_new_leads"] = new_leads
        st.session_state["run_result"] = result
    except Exception as exc:
        st.error(str(exc))

if "run_result" in st.session_state:
    new_leads = st.session_state["run_new_leads"]
    result = st.session_state["run_result"]

    st.subheader("Summary")
    st.write(f"{len(new_leads)} in → {len(result.valid_indices)} valid, "
             f"{len(result.refund_reasons)} refunded, {len(result.review_reasons)} needs review")

    if result.refund_reasons:
        st.subheader("Refund Reasons")
        st.dataframe(pd.DataFrame([
            {"row": idx, "reason": reason} for idx, reason in result.refund_reasons.items()
        ]))

    if result.review_reasons:
        st.subheader("Needs Review")
        for idx, reasons in list(result.review_reasons.items()):
            with st.expander(f"Row {idx}: {new_leads.loc[idx].to_dict()}"):
                st.write(reasons)
                col1, col2 = st.columns(2)
                if col1.button("Approve as valid", key=f"approve_{idx}"):
                    result.valid_indices.append(idx)
                    del result.review_reasons[idx]
                    st.rerun()
                if col2.button("Mark as refund", key=f"refund_{idx}"):
                    result.refund_reasons[idx] = "; ".join(reasons)
                    del result.review_reasons[idx]
                    st.rerun()

    if not result.review_reasons and st.button("Finalize"):
        backup_path = backup_file(profile.accumulated_report_path)
        st.info(f"Backed up Accumulated Report to {backup_path}")

        run_date = datetime.date.today().isoformat()
        if result.valid_indices:
            append_leads(profile.accumulated_report_path, profile.accumulated_tab_name,
                         new_leads.loc[result.valid_indices], profile.field_mapping, run_date)
        if result.refund_reasons:
            refund_indices = list(result.refund_reasons.keys())
            append_leads(profile.accumulated_report_path, profile.refund_tab_name,
                         new_leads.loc[refund_indices], profile.field_mapping, run_date,
                         reasons=result.refund_reasons)

        st.success("Accumulated Report updated.")
        del st.session_state["run_result"]
        del st.session_state["run_new_leads"]
```

- [ ] **Step 2: Static verification**

Run: `python -c "import ast; ast.parse(open('pages/2_Run_Check.py').read())"`
Expected: no output

Run: `python -m pytest -v`
Expected: PASS — all tests from Tasks 1–7 (this page has no direct tests)

Grep the file for `profile.exclusion.domain_column`, `profile.tal.domain_column`, `suppression_df`, `dedupe_df`, `profile.suppression.sheet_name`, `profile.dedupe_list.sheet_name` — there should be NONE (all replaced by per-source access or the renamed `reference_data` keys).

- [ ] **Step 3: Manual verification**

If interactive browser access is available: select a client whose profile has no `field_mapping` yet, upload `sample_data/Master_Output.xlsx`, confirm the "Map New Leads columns" section appears with dropdowns populated from the file's real headers, save the mapping, and confirm the page reruns with the mapping section gone and Run Check available. Click Run Check and confirm no crash. If Leadcap is enabled with `check_company_name` on, confirm the Purchased Lead Report upload's required-columns error message mentions the company column when that column is missing from an uploaded CSV. If no interactive access is available, trace the code carefully by hand and report honestly which verification was actually performed.

- [ ] **Step 4: Commit**

```bash
git add pages/2_Run_Check.py
git commit -m "feat: inline field-mapping flow, per-source columns, and multi-source Suppression/Dedupe in Run Check"
```

---

## Task 10: End-to-End Test Update & Full Regression

**Files:**
- Modify: `tests/test_end_to_end_basware.py`

**Interfaces:**
- Consumes: `core.models.ExclusionConfig`, `core.models.ReferenceSource` (unchanged shape for this test's usage — `ReferenceSource`'s new column fields default correctly for the real Basware file, which already uses "Domain"/"Account Name" headers).

- [ ] **Step 1: Verify the existing file still matches the current API**

Read the current `tests/test_end_to_end_basware.py`. Its `ExclusionConfig(enabled=True, sources=[ReferenceSource(name="Basware Exclusion", file_path=exclusion_path, sheet_name="Exclusion")])` and `reference_data={"exclusion_sources": {"Basware Exclusion": exclusion_df}}` usage already match the API after all of Tasks 1–9 (no `domain_column`/`company_column` overrides were used, and the real Basware Exclusion file's headers are "Domain"/"Account Name" — `ReferenceSource`'s defaults). No changes should be needed to this test file's logic — confirm this by running it.

- [ ] **Step 2: Run the end-to-end test**

Run: `python -m pytest tests/test_end_to_end_basware.py -v`
Expected: PASS (2 tests) — if either fails, diagnose whether it's a genuine regression from Tasks 1–9 (fix the regression) or whether this test file genuinely needs a small update to match a changed API surface (make the minimal correct update, matching the patterns established in Tasks 1–9, and note in your report exactly what changed and why).

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS — every test across all files. Count should be higher than the pre-plan baseline of 67 (Task 1 adds 5, Task 2 adds 3, Task 3 adds 2, Task 4 adds 3, Task 5 adds 3, Task 6 adds 1, Task 7 adds 5 — for a total around 89, exact count depends on how many `test_file_browser.py` tests actually run vs. skip in this environment).

- [ ] **Step 4: Commit** (only if Step 2 required an actual file change; if the file needed no changes, skip this commit — there's nothing to commit)

```bash
git add tests/test_end_to_end_basware.py
git commit -m "test: confirm end-to-end test compatibility with per-source columns and leadcap company pass"
```

---

## Post-Plan Follow-Ups (not part of this plan)

- The Leadcap segments text area's pipe-delimited format remains manual-entry-friendly but not validated (a malformed line still raises an uncaught `ValueError` mid-render) — pre-existing, not introduced or fixed by this plan.
- `browse_for_file()`'s dialog reflects the filesystem of whichever machine runs the Streamlit process, not a remote colleague's — documented as a known constraint in the design spec, not solved here.
