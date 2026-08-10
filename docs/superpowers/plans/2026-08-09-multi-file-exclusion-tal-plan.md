# Multi-File Exclusion & TAL Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a client's Exclusion List and TAL each be split across any number of files and/or sheets, optionally scoped to specific CIDs, replacing today's single-file assumption for both checks.

**Architecture:** Introduce a shared `ReferenceSource` dataclass (name, file_path, sheet_name, cids) used by both `ExclusionConfig.sources` and `TalConfig.sources`. Check logic resolves, per lead, every source whose `cids` is empty (applies to all) or contains that lead's CID, then matches against the union of those sources' data. The Client Setup UI grows a dynamic "Add Source" list (with a live sheet-name dropdown per source) for both checks; the Run Check page reads every configured source into a `{name: DataFrame}` dict before running the pipeline.

**Tech Stack:** Python 3, Streamlit, pandas, openpyxl (unchanged from the existing project).

## Global Constraints

- No network calls anywhere in the app — fully local/offline (existing project constraint, unaffected by this change).
- A source with an empty `cids` list applies to every lead regardless of CID; a source with a non-empty `cids` list applies only to leads whose CID is in that list.
- Exclusion fails a lead if it matches ANY applicable source; TAL passes a lead if it matches ANY applicable source (fails with `"TAL - not found"` otherwise) — union semantics, not intersection.
- `domain_column`/`company_column` remain single per-check settings shared across all of a client's sources (not per-source) — explicitly out of scope to make these per-source.
- Leadcap's existing segment mechanism (`LeadcapConfig.segments`, `LeadcapSegment`) is untouched by this plan.
- No migration path is needed for existing saved profiles — none currently exist in `clients/` (git-ignored, and the only prior test profile was already deleted).
- Full test suite must pass after every task (`python -m pytest -v`), and after the final task the count must be higher than the current 60 (new sources tests added, no tests removed except the ones this plan explicitly replaces).

---

## Task 1: Data Model — `ReferenceSource` and Config Changes

**Files:**
- Modify: `core/models.py`
- Modify: `core/profile_store.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_profile_store.py`

**Interfaces:**
- Produces: `ReferenceSource(name: str, file_path: str, sheet_name: str, cids: list[str] = [])` in `core/models.py`.
- Produces: `ExclusionConfig(enabled: bool = False, check_company_name: bool = False, sources: list[ReferenceSource] = [], domain_column: str = "Domain", company_column: str = "Account Name")` — `sheet_name` field removed.
- Produces: `TalConfig(enabled: bool = False, check_company_name: bool = False, sources: list[ReferenceSource] = [], domain_column: str = "Domain", company_column: str = "Account Name")` — `segmented`, `flat_sheet_name`, `segments` fields removed; `TalSegment` dataclass removed entirely.
- Produces: `ClientProfile` with `tal_path` and `exclusion_path` fields removed (file paths now live inside each `ReferenceSource`).
- Consumes/Produces: `core.profile_store.save_profile`/`load_profile`/`list_profile_names` — signatures unchanged, but `load_profile` now reconstructs `ExclusionConfig.sources` and `TalConfig.sources` as lists of `ReferenceSource` from JSON, the same pattern already used for `LeadcapConfig.segments`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_models.py (full replacement)
from core.models import (
    FieldMapping, LeadcapSegment, LeadcapConfig, TalConfig,
    ExclusionConfig, ReferenceSource, SuppressionConfig, DuplicateConfig, DedupeListConfig,
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
    assert profile.field_mapping.email == "emailaddress"


def test_leadcap_segment_equality():
    a = LeadcapSegment(name="AU Geo", cids=["114578"], cap=8)
    b = LeadcapSegment(name="AU Geo", cids=["114578"], cap=8)
    assert a == b


def test_reference_source_defaults_to_applying_everywhere():
    source = ReferenceSource(name="Global", file_path="x.xlsx", sheet_name="Sheet1")
    assert source.cids == []


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

```python
# tests/test_profile_store.py (full replacement)
from core.models import (
    ClientProfile, FieldMapping, LeadcapConfig, LeadcapSegment,
    TalConfig, ExclusionConfig, ReferenceSource,
)
from core.profile_store import save_profile, load_profile, list_profile_names


def _sample_profile() -> ClientProfile:
    return ClientProfile(
        name="Basware",
        accumulated_report_path="sample_data/Basware APAC – Accumulated Report.xlsx",
        field_mapping=FieldMapping(email="emailaddress", first_name="firstname",
                                    last_name="lastname", company="company", cid="CID"),
        leadcap=LeadcapConfig(enabled=True, segmented=True, segments=[
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
                             sheet_name="Sheet1", cids=["114578", "114579"]),
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
Expected: FAIL — `ImportError: cannot import name 'ReferenceSource' from 'core.models'` (and `ClientProfile.exclusion_path`/`tal_path` no longer accepted once Task's implementation removes them, but at this point the old model still has them, so the failure is specifically the missing `ReferenceSource` import and the `TalConfig(sources=...)`/`ExclusionConfig(sources=...)` keyword not existing yet)

- [ ] **Step 3: Update `core/models.py`**

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
    purchased_report_cid_column: str = "Campaign ID"
    purchased_report_email_column: str = "Email"


@dataclass
class ReferenceSource:
    name: str
    file_path: str
    sheet_name: str
    cids: list[str] = field(default_factory=list)


@dataclass
class TalConfig:
    enabled: bool = False
    check_company_name: bool = False
    sources: list[ReferenceSource] = field(default_factory=list)
    domain_column: str = "Domain"
    company_column: str = "Account Name"


@dataclass
class ExclusionConfig:
    enabled: bool = False
    check_company_name: bool = False
    sources: list[ReferenceSource] = field(default_factory=list)
    domain_column: str = "Domain"
    company_column: str = "Account Name"


@dataclass
class SuppressionConfig:
    enabled: bool = False
    check_domain: bool = False
    check_company_name: bool = False
    check_email: bool = False
    sheet_name: str = "Sheet1"
    domain_column: str = "Domain"
    company_column: str = "Account Name"
    email_column: str = "Email"


@dataclass
class DuplicateConfig:
    enabled: bool = False


@dataclass
class DedupeListConfig:
    enabled: bool = False
    sheet_name: str = "Sheet1"
    email_column: str = "Email"


@dataclass
class ClientProfile:
    name: str
    accumulated_report_path: str
    accumulated_tab_name: str = "Accumulated"
    refund_tab_name: str = "Refund"
    suppression_path: Optional[str] = None
    dedupe_list_path: Optional[str] = None
    field_mapping: Optional[FieldMapping] = None
    duplicate: DuplicateConfig = field(default_factory=DuplicateConfig)
    leadcap: LeadcapConfig = field(default_factory=LeadcapConfig)
    exclusion: ExclusionConfig = field(default_factory=ExclusionConfig)
    tal: TalConfig = field(default_factory=TalConfig)
    suppression: SuppressionConfig = field(default_factory=SuppressionConfig)
    dedupe_list: DedupeListConfig = field(default_factory=DedupeListConfig)
```

- [ ] **Step 4: Update `core/profile_store.py`**

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

    return ClientProfile(
        name=data["name"],
        accumulated_report_path=data["accumulated_report_path"],
        accumulated_tab_name=data.get("accumulated_tab_name", "Accumulated"),
        refund_tab_name=data.get("refund_tab_name", "Refund"),
        suppression_path=data.get("suppression_path"),
        dedupe_list_path=data.get("dedupe_list_path"),
        field_mapping=field_mapping,
        duplicate=DuplicateConfig(**(data.get("duplicate") or {})),
        leadcap=LeadcapConfig(**leadcap),
        exclusion=ExclusionConfig(**exclusion),
        tal=TalConfig(**tal),
        suppression=SuppressionConfig(**(data.get("suppression") or {})),
        dedupe_list=DedupeListConfig(**(data.get("dedupe_list") or {})),
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
Expected: PASS (7 tests: 5 in test_models.py, 2 in test_profile_store.py)

Note: this task's changes to `core/models.py` will break `core/checks/exclusion.py`, `core/checks/tal.py`, `core/pipeline.py`, `pages/1_Client_Setup.py`, `pages/2_Run_Check.py`, and `tests/checks/test_exclusion.py`/`test_tal.py`/`tests/test_pipeline.py`/`tests/test_end_to_end_basware.py` (they reference removed fields). This is expected — later tasks fix each of those. Do not attempt to fix them in this task; running the FULL suite now will show failures in those other files, which is fine.

- [ ] **Step 6: Commit**

```bash
git add core/models.py core/profile_store.py tests/test_models.py tests/test_profile_store.py
git commit -m "feat: add ReferenceSource for multi-file Exclusion/TAL config"
```

---

## Task 2: Exclusion Check — Multi-Source Logic

**Files:**
- Modify: `core/checks/exclusion.py`
- Modify: `tests/checks/test_exclusion.py`

**Interfaces:**
- Consumes: `core.models.ReferenceSource`, `core.models.ExclusionConfig` (from Task 1).
- Produces: `check_exclusion(new_leads: pandas.DataFrame, field_mapping: FieldMapping, config: ExclusionConfig, sources_data: dict[str, pandas.DataFrame], alias_groups: list[list[str]]) -> CheckOutcome` — `sources_data` is keyed by `ReferenceSource.name`, replacing the old single `exclusion_df` parameter.

- [ ] **Step 1: Write the failing tests**

```python
# tests/checks/test_exclusion.py (full replacement)
import pandas as pd

from core.checks.exclusion import check_exclusion
from core.models import FieldMapping, ExclusionConfig, ReferenceSource

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

EXCLUSION_DF = pd.DataFrame([
    {"Account Name": "Adecco UK Ltd", "Domain": "adecco.co.uk"},
    {"Account Name": "Enerpac Tool Group, Inc.", "Domain": "enerpactoolgroup.com"},
])

UNIVERSAL_SOURCE = ReferenceSource(name="Global", file_path="unused.xlsx", sheet_name="Exclusion")


def test_domain_match_fails():
    config = ExclusionConfig(enabled=True, check_company_name=False, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@adecco.co.uk", "company": "Someone Else", "CID": "1"}])

    outcome = check_exclusion(new_leads, FM, config, {"Global": EXCLUSION_DF}, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - domain"


def test_no_match_passes():
    config = ExclusionConfig(enabled=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@scania.com", "company": "Scania", "CID": "1"}])

    outcome = check_exclusion(new_leads, FM, config, {"Global": EXCLUSION_DF}, alias_groups=[])

    assert outcome.fail == {}
    assert outcome.review == {}


def test_company_name_match_fails_when_toggled_on():
    config = ExclusionConfig(enabled=True, check_company_name=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@unrelated-domain.com", "company": "Enerpac Tool Group", "CID": "1"}])

    outcome = check_exclusion(new_leads, FM, config, {"Global": EXCLUSION_DF}, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - company"


def test_disabled_check_produces_no_failures():
    config = ExclusionConfig(enabled=False, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@adecco.co.uk", "company": "Adecco", "CID": "1"}])

    outcome = check_exclusion(new_leads, FM, config, {"Global": EXCLUSION_DF}, alias_groups=[])

    assert outcome.fail == {}


def test_multiple_universal_sources_are_unioned():
    df_a = pd.DataFrame([{"Account Name": "A Co", "Domain": "a.com"}])
    df_b = pd.DataFrame([{"Account Name": "B Co", "Domain": "b.com"}])
    config = ExclusionConfig(enabled=True, sources=[
        ReferenceSource(name="A", file_path="a.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="B", file_path="b.xlsx", sheet_name="Sheet1"),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@b.com", "company": "B Co", "CID": "1"}])

    outcome = check_exclusion(new_leads, FM, config, {"A": df_a, "B": df_b}, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - domain"


def test_segment_scoped_source_only_applies_to_its_own_cids():
    df_emea = pd.DataFrame([{"Account Name": "EMEA Excluded Co", "Domain": "emea-excluded.com"}])
    config = ExclusionConfig(enabled=True, sources=[
        ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"]),
    ])
    apac_lead = pd.DataFrame([{"emailaddress": "x@emea-excluded.com", "company": "X", "CID": "200"}])

    outcome = check_exclusion(apac_lead, FM, config, {"EMEA": df_emea}, alias_groups=[])

    assert outcome.fail == {}


def test_universal_and_segment_scoped_sources_combine_for_in_scope_lead():
    universal_df = pd.DataFrame([{"Account Name": "Global Bad Co", "Domain": "globalbad.com"}])
    emea_df = pd.DataFrame([{"Account Name": "EMEA Bad Co", "Domain": "emeabad.com"}])
    config = ExclusionConfig(enabled=True, sources=[
        ReferenceSource(name="Global", file_path="global.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"]),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@emeabad.com", "company": "X", "CID": "100"}])

    outcome = check_exclusion(new_leads, FM, config, {"Global": universal_df, "EMEA": emea_df}, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - domain"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/checks/test_exclusion.py -v`
Expected: FAIL — `TypeError: ExclusionConfig.__init__() got an unexpected keyword argument 'sources'` (Task 1 already removed `sheet_name` and hasn't been told `sources` exists on `ExclusionConfig` until this task's implementation step, but per Task 1 `sources` DOES already exist on the dataclass — so more precisely this fails because `check_exclusion` in `core/checks/exclusion.py` still has the old signature (`exclusion_df` positional, not `sources_data`) and its body reads `config.domain_column`/`sheet_name`-less usage that doesn't yet resolve sources)

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
            if config.domain_column in df.columns:
                domains |= set(df[config.domain_column].astype(str).str.strip().str.lower())
            if config.check_company_name and config.company_column in df.columns:
                companies.extend(list(df[config.company_column].astype(str)))

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/checks/test_exclusion.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add core/checks/exclusion.py tests/checks/test_exclusion.py
git commit -m "feat: support multiple CID-scoped Exclusion sources"
```

---

## Task 3: TAL Check — Multi-Source Logic

**Files:**
- Modify: `core/checks/tal.py`
- Modify: `tests/checks/test_tal.py`

**Interfaces:**
- Consumes: `core.models.ReferenceSource`, `core.models.TalConfig` (from Task 1).
- Produces: `check_tal(new_leads: pandas.DataFrame, field_mapping: FieldMapping, config: TalConfig, sources_data: dict[str, pandas.DataFrame], alias_groups: list[list[str]]) -> CheckOutcome` — `sources_data` is keyed by `ReferenceSource.name`, replacing the old `tal_sheets` parameter keyed by sheet name.

- [ ] **Step 1: Write the failing tests**

```python
# tests/checks/test_tal.py (full replacement)
import pandas as pd

from core.checks.tal import check_tal
from core.models import FieldMapping, TalConfig, ReferenceSource

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

TAL_SHEET1 = pd.DataFrame([
    {"Account Name": "Severn Trent Water Limited", "Domain": "stwater.co.uk"},
])

TAL_SHEET_ACME = pd.DataFrame([
    {"Account Name": "Acme Industrial Supply", "Domain": "acme.com"},
])

UNIVERSAL_SOURCE = ReferenceSource(name="Global TAL", file_path="tal.xlsx", sheet_name="Sheet1")


def test_flat_tal_domain_found_passes():
    config = TalConfig(enabled=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Severn Trent", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Global TAL": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail == {}


def test_flat_tal_domain_not_found_fails():
    config = TalConfig(enabled=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@notlisted.com", "company": "Not Listed", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Global TAL": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail[0] == "TAL - not found"


def test_segmented_tal_resolves_correct_source_by_cid():
    config = TalConfig(enabled=True, sources=[
        ReferenceSource(name="UK Geo", file_path="tal_uk.xlsx", sheet_name="UKTab", cids=["114578"]),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Severn Trent", "CID": "114578"}])

    outcome = check_tal(new_leads, FM, config, {"UK Geo": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail == {}


def test_lead_outside_any_segment_cids_is_skipped_not_failed():
    config = TalConfig(enabled=True, sources=[
        ReferenceSource(name="UK Geo", file_path="tal_uk.xlsx", sheet_name="UKTab", cids=["114578"]),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@notlisted.com", "company": "X", "CID": "999999"}])

    outcome = check_tal(new_leads, FM, config, {"UK Geo": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail == {}


def test_universal_and_segment_scoped_sources_combine_for_in_scope_lead():
    universal_df = pd.DataFrame([{"Account Name": "Global Partner", "Domain": "globalpartner.com"}])
    config = TalConfig(enabled=True, sources=[
        ReferenceSource(name="Global", file_path="global.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="UK Geo", file_path="tal_uk.xlsx", sheet_name="UKTab", cids=["114578"]),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Severn Trent", "CID": "114578"}])

    outcome = check_tal(new_leads, FM, config, {"Global": universal_df, "UK Geo": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail == {}


def test_company_name_required_and_not_found_fails_even_with_domain_match():
    config = TalConfig(enabled=True, sources=[UNIVERSAL_SOURCE], check_company_name=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Totally Different Co", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Global TAL": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail[0] == "TAL - company not found"


def test_disabled_check_produces_no_failures():
    config = TalConfig(enabled=False)
    new_leads = pd.DataFrame([{"emailaddress": "x@notlisted.com", "company": "X", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {}, alias_groups=[])

    assert outcome.fail == {}


def test_company_name_gray_zone_fuzzy_match_goes_to_review():
    config = TalConfig(enabled=True, sources=[
        ReferenceSource(name="Acme Source", file_path="acme.xlsx", sheet_name="Sheet1"),
    ], check_company_name=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@acme.com", "company": "Acme Industries", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Acme Source": TAL_SHEET_ACME}, alias_groups=[])

    assert 0 not in outcome.fail, "Lead should not fail when company name is a gray-zone match"
    assert outcome.review[0] == "TAL - company name ambiguous match"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/checks/test_tal.py -v`
Expected: FAIL — `TypeError: TalConfig.__init__() got an unexpected keyword argument 'sources'` is already resolved by Task 1's model change, so more precisely: `check_tal`'s current implementation still references `config.segmented`/`config.flat_sheet_name`/`config.segments`, which no longer exist on `TalConfig` after Task 1 — `AttributeError: 'TalConfig' object has no attribute 'segmented'`

- [ ] **Step 3: Update `core/checks/tal.py`**

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
            if config.domain_column in df.columns:
                domains |= set(df[config.domain_column].astype(str).str.strip().str.lower())
            if config.check_company_name and config.company_column in df.columns:
                companies.extend(list(df[config.company_column].astype(str)))

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/checks/test_tal.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add core/checks/tal.py tests/checks/test_tal.py
git commit -m "feat: support multiple CID-scoped TAL sources"
```

---

## Task 4: Pipeline — Rename `reference_data` Keys

**Files:**
- Modify: `core/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `check_exclusion`/`check_tal`'s new `sources_data` parameter (Tasks 2, 3).
- Produces: `run_pipeline`'s `reference_data` dict now expects keys `"exclusion_sources"` (`dict[str, DataFrame]`, replacing `"exclusion_df"`) and `"tal_sources"` (`dict[str, DataFrame]`, replacing `"tal_sheets"`). `"purchased_reports"`, `"suppression_df"`, `"dedupe_df"` are unchanged.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline.py (full replacement)
import pandas as pd

from core.pipeline import run_pipeline
from core.models import (
    ClientProfile, FieldMapping, DuplicateConfig, ExclusionConfig, ReferenceSource,
)

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")


def _profile(**overrides) -> ClientProfile:
    base = dict(
        name="Test",
        accumulated_report_path="unused.xlsx",
        field_mapping=FM,
    )
    base.update(overrides)
    return ClientProfile(**base)


def test_valid_lead_passes_through_with_no_checks_enabled():
    profile = _profile()
    new_leads = pd.DataFrame([{"emailaddress": "a@x.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    accumulated = pd.DataFrame(columns=["emailaddress", "firstname", "lastname", "company", "CID"])

    result = run_pipeline(new_leads, profile, accumulated, reference_data={}, alias_groups=[])

    assert result.valid_indices == [0]
    assert result.refund_reasons == {}
    assert result.review_reasons == {}


def test_lead_failing_duplicate_and_exclusion_lists_both_reasons():
    profile = _profile(
        duplicate=DuplicateConfig(enabled=True),
        exclusion=ExclusionConfig(enabled=True, sources=[
            ReferenceSource(name="Global", file_path="unused.xlsx", sheet_name="Exclusion"),
        ]),
    )
    new_leads = pd.DataFrame([{"emailaddress": "a@excluded.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    accumulated = pd.DataFrame([{"emailaddress": "a@excluded.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    exclusion_df = pd.DataFrame([{"Account Name": "Excluded Co", "Domain": "excluded.com"}])

    result = run_pipeline(
        new_leads, profile, accumulated,
        reference_data={"exclusion_sources": {"Global": exclusion_df}},
        alias_groups=[],
    )

    assert result.valid_indices == []
    assert "Duplicate - exact email" in result.refund_reasons[0]
    assert "Exclusion - domain" in result.refund_reasons[0]


def test_review_item_excluded_from_valid_and_refund():
    profile = _profile(duplicate=DuplicateConfig(enabled=True))
    new_leads = pd.DataFrame([{"emailaddress": "andy@unrelated.com", "firstname": "Andy", "lastname": "Jones", "company": "Unrelated", "CID": "1"}])
    accumulated = pd.DataFrame([{"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": "1"}])

    result = run_pipeline(new_leads, profile, accumulated, reference_data={}, alias_groups=[])

    assert result.valid_indices == []
    assert result.refund_reasons == {}
    assert 0 in result.review_reasons


def test_fail_takes_precedence_over_review_for_same_lead():
    profile = _profile(
        duplicate=DuplicateConfig(enabled=True),
        exclusion=ExclusionConfig(enabled=True, sources=[
            ReferenceSource(name="Global", file_path="unused.xlsx", sheet_name="Exclusion"),
        ]),
    )
    new_leads = pd.DataFrame([{"emailaddress": "andy@excluded.com", "firstname": "Andy", "lastname": "Jones", "company": "Unrelated", "CID": "1"}])
    accumulated = pd.DataFrame([{"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": "1"}])
    exclusion_df = pd.DataFrame([{"Account Name": "Excluded Co", "Domain": "excluded.com"}])

    result = run_pipeline(
        new_leads, profile, accumulated,
        reference_data={"exclusion_sources": {"Global": exclusion_df}},
        alias_groups=[],
    )

    assert 0 in result.refund_reasons
    assert 0 not in result.review_reasons
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL on `test_lead_failing_duplicate_and_exclusion_lists_both_reasons` and `test_fail_takes_precedence_over_review_for_same_lead` — the exclusion check doesn't fail the lead, since `core/pipeline.py` is still passing `reference_data.get("exclusion_df", ...)` (looking for the old key, never finding `"exclusion_sources"`) into `check_exclusion`, which now expects `sources_data` but receives an empty default `DataFrame()` instead of `{}`, causing a `sources_data.get(...)` call to fail with `AttributeError: 'DataFrame' object has no attribute 'get'`

- [ ] **Step 3: Update `core/pipeline.py`**

```python
from dataclasses import dataclass, field

import pandas as pd

from core.check_result import CheckOutcome
from core.checks import duplicate, leadcap, exclusion, tal, suppression, dedupe_list
from core.models import ClientProfile


@dataclass
class PipelineResult:
    valid_indices: list = field(default_factory=list)
    refund_reasons: dict = field(default_factory=dict)
    review_reasons: dict = field(default_factory=dict)


def run_pipeline(
    new_leads: pd.DataFrame,
    profile: ClientProfile,
    accumulated_leads: pd.DataFrame,
    reference_data: dict,
    alias_groups: list[list[str]],
) -> PipelineResult:
    fm = profile.field_mapping
    fail: dict[int, list[str]] = {}
    review: dict[int, list[str]] = {}

    def merge(outcome: CheckOutcome) -> None:
        for idx, reason in outcome.fail.items():
            fail.setdefault(idx, []).append(reason)
        for idx, reason in outcome.review.items():
            review.setdefault(idx, []).append(reason)

    if profile.duplicate.enabled:
        merge(duplicate.check_duplicates(new_leads, accumulated_leads, fm))

    if profile.leadcap.enabled:
        merge(leadcap.check_leadcap(new_leads, fm, profile.leadcap, reference_data.get("purchased_reports", {})))

    if profile.exclusion.enabled:
        merge(exclusion.check_exclusion(new_leads, fm, profile.exclusion,
                                         reference_data.get("exclusion_sources", {}), alias_groups))

    if profile.tal.enabled:
        merge(tal.check_tal(new_leads, fm, profile.tal,
                             reference_data.get("tal_sources", {}), alias_groups))

    if profile.suppression.enabled:
        merge(suppression.check_suppression(new_leads, fm, profile.suppression,
                                             reference_data.get("suppression_df", pd.DataFrame()), alias_groups))

    if profile.dedupe_list.enabled:
        merge(dedupe_list.check_dedupe_list(new_leads, fm, profile.dedupe_list,
                                             reference_data.get("dedupe_df", pd.DataFrame())))

    refund_reasons = {idx: "; ".join(reasons) for idx, reasons in fail.items()}
    review_reasons = {idx: reasons for idx, reasons in review.items() if idx not in fail}
    valid_indices = [idx for idx in new_leads.index if idx not in fail and idx not in review_reasons]

    return PipelineResult(valid_indices=valid_indices, refund_reasons=refund_reasons, review_reasons=review_reasons)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/pipeline.py tests/test_pipeline.py
git commit -m "refactor: rename pipeline reference_data keys for multi-source Exclusion/TAL"
```

---

## Task 5: Client Setup UI — Exclusion Sources

**Files:**
- Modify: `pages/1_Client_Setup.py`

**Interfaces:**
- Consumes: `core.excel_io.list_sheet_names` (existing), `core.models.ReferenceSource`, `core.models.ExclusionConfig` (Task 1).
- Produces: a session-state-backed dynamic list of Exclusion sources, converted to `list[ReferenceSource]` and assigned to `ExclusionConfig.sources` on Save.

No automated test for this task — Streamlit pages are verified by running them, consistent with how the original Client Setup page (Task 13 of the prior plan) was verified. Steps below build and verify manually.

- [ ] **Step 1: Replace the Exclusion section**

In `pages/1_Client_Setup.py`, remove the old single `exclusion_path`/`exclusion_sheet` block. Remove the `exclusion_path` text input from the "Reference Files" section entirely (line 33 in the current file: `exclusion_path = st.text_input("Exclusion List path", ...)`), since each Exclusion source now carries its own file path. Replace the existing `st.subheader("Exclusion")` block (current lines 89–101) with:

```python
st.subheader("Exclusion")
exclusion_enabled = st.checkbox("Enable Exclusion check", value=profile.exclusion.enabled if profile else False)
exclusion_check_company = st.checkbox("Also check Exclusion by company name",
                                       value=profile.exclusion.check_company_name if profile else False)

if "exclusion_sources" not in st.session_state:
    st.session_state["exclusion_sources"] = (
        [{"name": s.name, "file_path": s.file_path, "sheet_name": s.sheet_name, "cids": ",".join(s.cids)}
         for s in profile.exclusion.sources]
        if profile else []
    )

exclusion_sources_result: list[ReferenceSource] = []
if exclusion_enabled:
    if st.button("Add Exclusion Source"):
        st.session_state["exclusion_sources"].append({"name": "", "file_path": "", "sheet_name": "", "cids": ""})

    remove_exclusion_idx = None
    for i, src in enumerate(st.session_state["exclusion_sources"]):
        st.markdown(f"**Exclusion Source {i + 1}**")
        src["name"] = st.text_input("Name", value=src["name"], key=f"excl_src_name_{i}")
        src["file_path"] = st.text_input("File path", value=src["file_path"], key=f"excl_src_path_{i}")
        sheet_options: list[str] = []
        if src["file_path"]:
            try:
                sheet_options = list_sheet_names(src["file_path"])
            except Exception as exc:
                st.error(f"Could not read sheets from '{src['file_path']}': {exc}")
        if sheet_options:
            sheet_idx = sheet_options.index(src["sheet_name"]) if src["sheet_name"] in sheet_options else 0
            src["sheet_name"] = st.selectbox("Sheet", sheet_options, index=sheet_idx, key=f"excl_src_sheet_{i}")
        else:
            src["sheet_name"] = st.text_input("Sheet name (enter a valid file path above to pick from a list)",
                                               value=src["sheet_name"], key=f"excl_src_sheet_text_{i}")
        src["cids"] = st.text_input("CIDs this source applies to (comma-separated, blank = applies to all leads)",
                                     value=src["cids"], key=f"excl_src_cids_{i}")
        if st.button("Remove this source", key=f"excl_src_remove_{i}"):
            remove_exclusion_idx = i
        exclusion_sources_result.append(ReferenceSource(
            name=src["name"], file_path=src["file_path"], sheet_name=src["sheet_name"],
            cids=[c.strip() for c in src["cids"].split(",") if c.strip()],
        ))
    if remove_exclusion_idx is not None:
        st.session_state["exclusion_sources"].pop(remove_exclusion_idx)
        st.rerun()
```

- [ ] **Step 2: Update the import line**

Change the `core.models` import at the top of the file to include `ReferenceSource`:

```python
from core.models import (
    ClientProfile, FieldMapping, DuplicateConfig, LeadcapConfig, LeadcapSegment,
    ExclusionConfig, TalConfig, ReferenceSource, SuppressionConfig, DedupeListConfig,
)
```

(Note: `TalSegment` is removed from this import — it no longer exists per Task 1. Task 6 handles the TAL section's own use of `ReferenceSource`, already imported here.)

- [ ] **Step 3: Update the Save button's `ExclusionConfig` construction**

In the `if st.button("Save Client Profile"):` block, replace the `exclusion=ExclusionConfig(...)` line with:

```python
            exclusion=ExclusionConfig(enabled=exclusion_enabled, check_company_name=exclusion_check_company,
                                       sources=exclusion_sources_result),
```

Also remove `exclusion_path=exclusion_path or None,` from the `ClientProfile(...)` construction (the field no longer exists on `ClientProfile` per Task 1).

- [ ] **Step 4: Static verification**

Run: `python -c "import ast; ast.parse(open('pages/1_Client_Setup.py').read())"`
Expected: no output (no syntax error)

Run: `python -m pytest -v` (full suite — this page has no direct tests, but this confirms Tasks 1–4's changes are still solid and nothing in the page-adjacent code broke)
Expected: PASS (all tests from Tasks 1–4)

- [ ] **Step 5: Manual verification**

Run: `python -m streamlit run pages/1_Client_Setup.py --server.headless true --server.port 8503` (or use `run.bat` once Task 7 restores full app wiring), then in a browser: enable Exclusion, click "Add Exclusion Source" twice, enter `sample_data/Basware -Exclusion List.xlsx` as the file path for the first source and confirm the Sheet dropdown populates with the file's real sheet names (`TAL`, `Persona titles `, `Expanded Job Titles`, `Exclusion`); enter a CIDs value for the second source and leave the first blank; click "Remove this source" on the second and confirm it disappears; click Save Client Profile and confirm no crash.

- [ ] **Step 6: Commit**

```bash
git add pages/1_Client_Setup.py
git commit -m "feat: support multiple Exclusion sources in Client Setup"
```

---

## Task 6: Client Setup UI — TAL Sources

**Files:**
- Modify: `pages/1_Client_Setup.py`

**Interfaces:**
- Consumes: `core.excel_io.list_sheet_names`, `core.models.ReferenceSource` (already imported per Task 5), `core.models.TalConfig` (Task 1).
- Produces: a session-state-backed dynamic list of TAL sources, converted to `list[ReferenceSource]` and assigned to `TalConfig.sources` on Save.

No automated test for this task, same rationale as Task 5.

- [ ] **Step 1: Replace the TAL section**

Remove the old `tal_path` text input from the "Reference Files" section (current line 32: `tal_path = st.text_input("TAL file path", ...)`). Replace the existing `st.subheader("TAL")` block (current lines 103–128) with:

```python
st.subheader("TAL")
tal_enabled = st.checkbox("Enable TAL check", value=profile.tal.enabled if profile else False)
tal_check_company = st.checkbox("Also check TAL by company name", value=profile.tal.check_company_name if profile else False)

if "tal_sources" not in st.session_state:
    st.session_state["tal_sources"] = (
        [{"name": s.name, "file_path": s.file_path, "sheet_name": s.sheet_name, "cids": ",".join(s.cids)}
         for s in profile.tal.sources]
        if profile else []
    )

tal_sources_result: list[ReferenceSource] = []
if tal_enabled:
    if st.button("Add TAL Source"):
        st.session_state["tal_sources"].append({"name": "", "file_path": "", "sheet_name": "", "cids": ""})

    remove_tal_idx = None
    for i, src in enumerate(st.session_state["tal_sources"]):
        st.markdown(f"**TAL Source {i + 1}**")
        src["name"] = st.text_input("Name", value=src["name"], key=f"tal_src_name_{i}")
        src["file_path"] = st.text_input("File path", value=src["file_path"], key=f"tal_src_path_{i}")
        sheet_options: list[str] = []
        if src["file_path"]:
            try:
                sheet_options = list_sheet_names(src["file_path"])
            except Exception as exc:
                st.error(f"Could not read sheets from '{src['file_path']}': {exc}")
        if sheet_options:
            sheet_idx = sheet_options.index(src["sheet_name"]) if src["sheet_name"] in sheet_options else 0
            src["sheet_name"] = st.selectbox("Sheet", sheet_options, index=sheet_idx, key=f"tal_src_sheet_{i}")
        else:
            src["sheet_name"] = st.text_input("Sheet name (enter a valid file path above to pick from a list)",
                                               value=src["sheet_name"], key=f"tal_src_sheet_text_{i}")
        src["cids"] = st.text_input("CIDs this source applies to (comma-separated, blank = applies to all leads)",
                                     value=src["cids"], key=f"tal_src_cids_{i}")
        if st.button("Remove this source", key=f"tal_src_remove_{i}"):
            remove_tal_idx = i
        tal_sources_result.append(ReferenceSource(
            name=src["name"], file_path=src["file_path"], sheet_name=src["sheet_name"],
            cids=[c.strip() for c in src["cids"].split(",") if c.strip()],
        ))
    if remove_tal_idx is not None:
        st.session_state["tal_sources"].pop(remove_tal_idx)
        st.rerun()
```

- [ ] **Step 2: Update the Save button's `TalConfig` construction**

Replace the `tal=TalConfig(...)` line with:

```python
            tal=TalConfig(enabled=tal_enabled, check_company_name=tal_check_company,
                          sources=tal_sources_result),
```

Also remove `tal_path=tal_path or None,` from the `ClientProfile(...)` construction.

- [ ] **Step 3: Static verification**

Run: `python -c "import ast; ast.parse(open('pages/1_Client_Setup.py').read())"`
Expected: no output

Run: `python -m pytest -v`
Expected: PASS (all tests from Tasks 1–4; this page still has no direct tests)

- [ ] **Step 4: Manual verification**

Same pattern as Task 5 Step 5, but for TAL: add two TAL sources, one with `sample_data/Basware_Updated TAL_22nd June.xlsx` and confirm its Sheet dropdown shows `Sheet1` (the file's only real sheet), assign it a CIDs value, add a second source with blank CIDs, remove one, and Save without crashing.

- [ ] **Step 5: Commit**

```bash
git add pages/1_Client_Setup.py
git commit -m "feat: support multiple TAL sources in Client Setup"
```

---

## Task 7: Run Check Page — Read All Configured Sources

**Files:**
- Modify: `pages/2_Run_Check.py`

**Interfaces:**
- Consumes: `core.excel_io.read_sheet_as_dataframe`, `core.excel_io.require_columns` (existing), `profile.exclusion.sources`/`profile.tal.sources` (`list[ReferenceSource]`, Task 1).
- Produces: `reference_data["exclusion_sources"]` and `reference_data["tal_sources"]`, each a `dict[str, pandas.DataFrame]` keyed by source name, matching what `run_pipeline` now expects (Task 4).

No automated test for this task, same rationale as Tasks 5–6 (Streamlit page, verified by running).

- [ ] **Step 1: Replace the Exclusion and TAL reference-data blocks**

In the `try:` block under `if st.button("Run Check") and new_leads_file:`, replace:

```python
        if profile.exclusion.enabled:
            exclusion_df = read_sheet_as_dataframe(profile.exclusion_path, profile.exclusion.sheet_name)
            require_columns(exclusion_df, [profile.exclusion.domain_column], profile.exclusion_path)
            reference_data["exclusion_df"] = exclusion_df
        if profile.tal.enabled:
            if profile.tal.segmented:
                tal_sheets = {}
                for seg in profile.tal.segments:
                    df = read_sheet_as_dataframe(profile.tal_path, seg.sheet_name)
                    require_columns(df, [profile.tal.domain_column], f"{profile.tal_path} [{seg.sheet_name}]")
                    tal_sheets[seg.sheet_name] = df
                reference_data["tal_sheets"] = tal_sheets
            else:
                df = read_sheet_as_dataframe(profile.tal_path, profile.tal.flat_sheet_name)
                require_columns(df, [profile.tal.domain_column], f"{profile.tal_path} [{profile.tal.flat_sheet_name}]")
                reference_data["tal_sheets"] = {profile.tal.flat_sheet_name: df}
```

with:

```python
        if profile.exclusion.enabled:
            exclusion_sources_data: dict[str, pd.DataFrame] = {}
            for source in profile.exclusion.sources:
                df = read_sheet_as_dataframe(source.file_path, source.sheet_name)
                require_columns(df, [profile.exclusion.domain_column], f"{source.file_path} [{source.sheet_name}]")
                exclusion_sources_data[source.name] = df
            reference_data["exclusion_sources"] = exclusion_sources_data
        if profile.tal.enabled:
            tal_sources_data: dict[str, pd.DataFrame] = {}
            for source in profile.tal.sources:
                df = read_sheet_as_dataframe(source.file_path, source.sheet_name)
                require_columns(df, [profile.tal.domain_column], f"{source.file_path} [{source.sheet_name}]")
                tal_sources_data[source.name] = df
            reference_data["tal_sources"] = tal_sources_data
```

- [ ] **Step 2: Static verification**

Run: `python -c "import ast; ast.parse(open('pages/2_Run_Check.py').read())"`
Expected: no output

- [ ] **Step 3: Manual verification**

Run the app (`run.bat`, or `python -m streamlit run pages/2_Run_Check.py --server.headless true --server.port 8504`), select a client profile with at least one Exclusion source and one TAL source configured (from Tasks 5–6's manual verification), upload `sample_data/Master_Output.xlsx` as the New Leads file, click Run Check, and confirm no crash and a sensible summary (leads matching the configured sources' domains show up in refund reasons).

- [ ] **Step 4: Commit**

```bash
git add pages/2_Run_Check.py
git commit -m "feat: read all configured Exclusion/TAL sources in Run Check"
```

---

## Task 8: End-to-End Test Update & Full Regression

**Files:**
- Modify: `tests/test_end_to_end_basware.py`

**Interfaces:**
- Consumes: `core.models.ExclusionConfig`, `core.models.ReferenceSource` (Task 1), `run_pipeline`'s renamed `reference_data` key (Task 4).

- [ ] **Step 1: Update the end-to-end test**

```python
# tests/test_end_to_end_basware.py (full replacement)
import shutil

import pandas as pd
import pytest

from core.excel_io import read_sheet_as_dataframe, append_leads, backup_file
from core.models import ClientProfile, FieldMapping, DuplicateConfig, ExclusionConfig, ReferenceSource
from core.pipeline import run_pipeline

SAMPLE_DIR = "sample_data"


@pytest.fixture
def accumulated_copy(tmp_path):
    source = f"{SAMPLE_DIR}/Basware APAC – Accumulated Report.xlsx"
    dest = tmp_path / "Basware APAC – Accumulated Report.xlsx"
    shutil.copy2(source, dest)
    return str(dest)


def test_master_output_leads_are_flagged_as_duplicates_against_accumulated(accumulated_copy):
    fm = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                       company="company", cid="CID")
    exclusion_path = f"{SAMPLE_DIR}/Basware -Exclusion List.xlsx"
    profile = ClientProfile(
        name="Basware",
        accumulated_report_path=accumulated_copy,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
        exclusion=ExclusionConfig(enabled=True, sources=[
            ReferenceSource(name="Basware Exclusion", file_path=exclusion_path, sheet_name="Exclusion"),
        ]),
    )

    new_leads = pd.read_excel(f"{SAMPLE_DIR}/Master_Output.xlsx")
    accumulated_leads = read_sheet_as_dataframe(accumulated_copy, "Accumulated")
    exclusion_df = read_sheet_as_dataframe(exclusion_path, "Exclusion")

    result = run_pipeline(
        new_leads, profile, accumulated_leads,
        reference_data={"exclusion_sources": {"Basware Exclusion": exclusion_df}},
        alias_groups=[],
    )

    # Master_Output.xlsx leads are already in Accumulated (per user's note) — expect most/all flagged.
    assert len(result.refund_reasons) > 0
    assert all("Duplicate" in reason or "Exclusion" in reason for reason in result.refund_reasons.values())


def test_finalize_writes_refund_rows_with_reason(accumulated_copy):
    fm = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                       company="company", cid="CID")
    profile = ClientProfile(
        name="Basware",
        accumulated_report_path=accumulated_copy,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
    )

    new_leads = pd.read_excel(f"{SAMPLE_DIR}/Master_Output.xlsx")
    accumulated_leads = read_sheet_as_dataframe(accumulated_copy, "Accumulated")

    result = run_pipeline(new_leads, profile, accumulated_leads, reference_data={}, alias_groups=[])
    assert result.refund_reasons

    backup_path = backup_file(accumulated_copy)
    refund_indices = list(result.refund_reasons.keys())
    append_leads(accumulated_copy, "Refund", new_leads.loc[refund_indices], fm,
                 run_date="2026-08-08", reasons=result.refund_reasons)

    refund_after = read_sheet_as_dataframe(accumulated_copy, "Refund")
    assert len(refund_after) >= len(refund_indices)
    assert "Reason" in refund_after.columns
    assert backup_path != accumulated_copy
```

- [ ] **Step 2: Run the updated end-to-end test**

Run: `python -m pytest tests/test_end_to_end_basware.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS — every test across all files (models, profile_store, matching, excel_io generic + append, all six checks including the new multi-source Exclusion/TAL cases, pipeline, end-to-end). Count should be higher than the pre-change baseline of 60, since Task 2 adds 3 new Exclusion tests and Task 3 adds 1 new TAL test beyond the prior counts.

- [ ] **Step 4: Commit**

```bash
git add tests/test_end_to_end_basware.py
git commit -m "test: update end-to-end test for multi-source Exclusion config"
```

---

## Post-Plan Follow-Ups (not part of this plan)

- Per-source `domain_column`/`company_column` overrides, if a client's own multiple exclusion/TAL files ever use inconsistent column names (explicitly out of scope per the design spec).
- Applying the same multi-source pattern to Suppression or Dedupe list, if that need ever arises (not requested).
