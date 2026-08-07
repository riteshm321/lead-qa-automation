# Lead QA & Upload Automation Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Streamlit tool that runs six configurable lead-QA checks (Duplicate, Leadcap, Exclusion, TAL, Suppression, Dedupe list) against a client's new-leads batch, and appends the results into that client's persistent Accumulated Report (valid → Accumulated tab, invalid → Refund tab with a Reason column).

**Architecture:** Python 3 + Streamlit UI, pandas/openpyxl for all Excel I/O. Per-client configuration (file paths, which checks are on, segment/CID mappings, column headers) is stored as JSON under `clients/`. Each check is a pure function over pandas DataFrames, independent of Streamlit and of file I/O, so it can be unit tested without touching Excel.

**Tech Stack:** Python 3.11+, streamlit, pandas, openpyxl, rapidfuzz, pytest.

## Global Constraints

- No network calls anywhere in the app — fully local/offline (per spec's Architecture section).
- Nothing is written to disk until the user clicks Finalize in the Run Check page (per spec's Run Workflow section).
- A timestamped backup of the Accumulated Report is always written before it is overwritten (per spec's Error Handling section).
- A lead runs through **all** enabled checks regardless of an earlier failure, so its Reason lists every failed check (per spec's Check Logic & Order section).
- Check order is fixed: Duplicate → Leadcap → Exclusion → TAL → Suppression → Dedupe list (per spec's Check Logic & Order section).
- Domain matching is always exact; company-name matching always goes through normalize → alias table → fuzzy, in that order (per spec's Company-name matching pipeline section).
- The Accumulated Report's existing header row is the source of truth for output columns — the tool never invents new columns, matching by header name only (per spec's Accumulated Report Structure & Write Rules section).
- Reference file paths in this plan use the real sample data already inspected: `sample_data/Basware -Exclusion List.xlsx` (sheet `Exclusion`, columns `Account Name`, `Domain`), `sample_data/Basware_Updated TAL_22nd June.xlsx` (sheet `Sheet1`, columns `DUNS Primary Country`, `Account Name`, `Domain`), `sample_data/Basware APAC – Accumulated Report.xlsx` (tabs `Pacing Overview`, `Accumulated`, `Refund`), `sample_data/Master_Output.xlsx` (new leads, columns `CID`, `firstname`, `lastname`, `emailaddress`, `company`, ...), `sample_data/PurchasedLeadsReport_2026-08-06T19_48_09.936Z (2).csv` (columns `Campaign ID`, `First Name`, `Last Name`, `Email`, `Company`, ...).

---

## Task 1: Project Scaffolding & Core Data Models

**Files:**
- Create: `requirements.txt`
- Create: `run.bat`
- Create: `core/__init__.py`
- Create: `core/models.py`
- Create: `core/check_result.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `FieldMapping(email, first_name, last_name, company, cid)`, `LeadcapSegment(name, cids, cap)`, `LeadcapConfig(enabled, segmented, flat_cap, segments, purchased_report_cid_column)`, `TalSegment(name, cids, sheet_name)`, `TalConfig(enabled, check_company_name, segmented, flat_sheet_name, segments, domain_column, company_column)`, `ExclusionConfig(enabled, check_company_name, sheet_name, domain_column, company_column)`, `SuppressionConfig(enabled, check_domain, check_company_name, check_email, sheet_name, domain_column, company_column, email_column)`, `DuplicateConfig(enabled)`, `DedupeListConfig(enabled, sheet_name, email_column)`, `ClientProfile(name, accumulated_report_path, tal_path, exclusion_path, suppression_path, dedupe_list_path, field_mapping, duplicate, leadcap, exclusion, tal, suppression, dedupe_list)` — all in `core/models.py`.
- Produces: `CheckOutcome(fail: dict[int, str], review: dict[int, str])` in `core/check_result.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from core.models import (
    FieldMapping, LeadcapSegment, LeadcapConfig, TalSegment, TalConfig,
    ExclusionConfig, SuppressionConfig, DuplicateConfig, DedupeListConfig,
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
    assert profile.tal.segments == []
    assert profile.field_mapping.email == "emailaddress"


def test_leadcap_segment_equality():
    a = LeadcapSegment(name="AU Geo", cids=["114578"], cap=8)
    b = LeadcapSegment(name="AU Geo", cids=["114578"], cap=8)
    assert a == b


def test_check_outcome_defaults_are_independent():
    a = CheckOutcome()
    b = CheckOutcome()
    a.fail[1] = "x"
    assert b.fail == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core'` (or similar — `core/models.py` does not exist yet)

- [ ] **Step 3: Write minimal implementation**

```python
# core/__init__.py
```

```python
# core/models.py
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


@dataclass
class TalSegment:
    name: str
    cids: list[str]
    sheet_name: str


@dataclass
class TalConfig:
    enabled: bool = False
    check_company_name: bool = False
    segmented: bool = False
    flat_sheet_name: Optional[str] = None
    segments: list[TalSegment] = field(default_factory=list)
    domain_column: str = "Domain"
    company_column: str = "Account Name"


@dataclass
class ExclusionConfig:
    enabled: bool = False
    check_company_name: bool = False
    sheet_name: str = "Exclusion"
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
    tal_path: Optional[str] = None
    exclusion_path: Optional[str] = None
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

```python
# core/check_result.py
from dataclasses import dataclass, field


@dataclass
class CheckOutcome:
    fail: dict[int, str] = field(default_factory=dict)
    review: dict[int, str] = field(default_factory=dict)
```

```
# requirements.txt
streamlit>=1.38
pandas>=2.2
openpyxl>=3.1
rapidfuzz>=3.9
pytest>=8.0
```

```bat
:: run.bat
@echo off
cd /d "%~dp0"
streamlit run app.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add requirements.txt run.bat core/__init__.py core/models.py core/check_result.py tests/test_models.py
git commit -m "feat: scaffold project and core data models"
```

---

## Task 2: Client Profile Store (save/load JSON)

**Files:**
- Create: `core/profile_store.py`
- Test: `tests/test_profile_store.py`

**Interfaces:**
- Consumes: all dataclasses from `core/models.py` (Task 1).
- Produces: `save_profile(profile: ClientProfile, clients_dir: str = "clients") -> str` (returns saved file path), `load_profile(name: str, clients_dir: str = "clients") -> ClientProfile`, `list_profile_names(clients_dir: str = "clients") -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_store.py
from core.models import (
    ClientProfile, FieldMapping, LeadcapConfig, LeadcapSegment,
    TalConfig, TalSegment, ExclusionConfig,
)
from core.profile_store import save_profile, load_profile, list_profile_names


def _sample_profile() -> ClientProfile:
    return ClientProfile(
        name="Basware",
        accumulated_report_path="sample_data/Basware APAC – Accumulated Report.xlsx",
        exclusion_path="sample_data/Basware -Exclusion List.xlsx",
        field_mapping=FieldMapping(email="emailaddress", first_name="firstname",
                                    last_name="lastname", company="company", cid="CID"),
        leadcap=LeadcapConfig(enabled=True, segmented=True, segments=[
            LeadcapSegment(name="AU Geo", cids=["114578"], cap=8),
            LeadcapSegment(name="IN Geo", cids=["114568"], cap=5),
        ]),
        tal=TalConfig(enabled=True, segmented=False, flat_sheet_name="Sheet1"),
        exclusion=ExclusionConfig(enabled=True, sheet_name="Exclusion"),
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

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_profile_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.profile_store'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/profile_store.py
import dataclasses
import json
import os

from core.models import (
    ClientProfile, FieldMapping, LeadcapConfig, LeadcapSegment,
    TalConfig, TalSegment, ExclusionConfig, SuppressionConfig,
    DuplicateConfig, DedupeListConfig,
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

    tal = data.get("tal") or {}
    tal["segments"] = [TalSegment(**s) for s in tal.get("segments", [])]

    return ClientProfile(
        name=data["name"],
        accumulated_report_path=data["accumulated_report_path"],
        tal_path=data.get("tal_path"),
        exclusion_path=data.get("exclusion_path"),
        suppression_path=data.get("suppression_path"),
        dedupe_list_path=data.get("dedupe_list_path"),
        field_mapping=field_mapping,
        duplicate=DuplicateConfig(**(data.get("duplicate") or {})),
        leadcap=LeadcapConfig(**leadcap),
        exclusion=ExclusionConfig(**(data.get("exclusion") or {})),
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

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_profile_store.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add core/profile_store.py tests/test_profile_store.py
git commit -m "feat: add client profile JSON save/load"
```

---

## Task 3: Matching Utilities (domain extraction, company-name normalization, alias table, fuzzy scoring)

**Files:**
- Create: `core/matching.py`
- Test: `tests/test_matching.py`

**Interfaces:**
- Produces: `extract_domain(email: str) -> str`, `normalize_company_name(name: str) -> str`, `MatchResult(status: str, score: float)`, `load_alias_groups(path: str) -> list[list[str]]`, `save_alias_groups(groups: list[list[str]], path: str) -> None`, `add_alias_pair(name_a: str, name_b: str, path: str) -> None`, `company_names_match(name_a: str, name_b: str, alias_groups: list[list[str]]) -> MatchResult`, `domain_is_company_variant(domain: str, company_name: str) -> bool`.
- `MatchResult.status` is one of `"match"`, `"no_match"`, `"review"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_matching.py
from core.matching import (
    extract_domain, normalize_company_name, company_names_match,
    domain_is_company_variant, load_alias_groups, save_alias_groups, add_alias_pair,
)


def test_extract_domain():
    assert extract_domain("Andy@Google.com") == "google.com"
    assert extract_domain("") == ""
    assert extract_domain("not-an-email") == ""


def test_normalize_company_name_strips_suffixes_and_punctuation():
    assert normalize_company_name("Google, Inc.") == "google"
    assert normalize_company_name("Enerpac Tool Group, Inc.") == "enerpac tool group"
    assert normalize_company_name("") == ""


def test_company_names_match_exact_after_normalization():
    result = company_names_match("Google Inc", "Google, Inc.", alias_groups=[])
    assert result.status == "match"


def test_company_names_match_via_alias_table():
    aliases = [["facebook", "meta"]]
    result = company_names_match("Facebook", "Meta", alias_groups=aliases)
    assert result.status == "match"


def test_company_names_match_no_match_for_unrelated_names():
    result = company_names_match("Danone", "Scania", alias_groups=[])
    assert result.status == "no_match"


def test_company_names_match_review_for_gray_zone():
    result = company_names_match("Basware Corp", "Basware Oy", alias_groups=[])
    assert result.status in ("match", "review")  # never a hard no_match for near-identical roots


def test_domain_is_company_variant_true_for_typo_domain():
    assert domain_is_company_variant("gooooogle.com", "Google") is True


def test_domain_is_company_variant_false_for_unrelated_domain():
    assert domain_is_company_variant("scania.com", "Google") is False


def test_alias_table_round_trip(tmp_path):
    path = str(tmp_path / "aliases.json")
    save_alias_groups([["facebook", "meta"]], path)
    assert load_alias_groups(path) == [["facebook", "meta"]]

    add_alias_pair("Google", "Alphabet", path)
    groups = load_alias_groups(path)
    assert any("google" in g and "alphabet" in g for g in groups)


def test_load_alias_groups_missing_file_returns_empty(tmp_path):
    path = str(tmp_path / "does_not_exist.json")
    assert load_alias_groups(path) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_matching.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.matching'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/matching.py
import json
import os
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

LEGAL_SUFFIXES = {"inc", "llc", "corp", "corporation", "ltd", "co", "company", "group", "plc", "oy"}

HIGH_THRESHOLD = 90.0
LOW_THRESHOLD = 70.0


@dataclass
class MatchResult:
    status: str
    score: float


def extract_domain(email: str) -> str:
    if not email or "@" not in email:
        return ""
    return email.strip().lower().split("@")[-1]


def normalize_company_name(name: str) -> str:
    if not name:
        return ""
    lowered = re.sub(r"[^\w\s]", " ", name.lower())
    words = [w for w in lowered.split() if w not in LEGAL_SUFFIXES]
    return " ".join(words).strip()


def load_alias_groups(path: str) -> list[list[str]]:
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_alias_groups(groups: list[list[str]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(groups, f, indent=2)


def add_alias_pair(name_a: str, name_b: str, path: str) -> None:
    a, b = normalize_company_name(name_a), normalize_company_name(name_b)
    groups = load_alias_groups(path)
    target = None
    for group in groups:
        if a in group or b in group:
            target = group
            break
    if target is None:
        groups.append([a, b])
    else:
        if a not in target:
            target.append(a)
        if b not in target:
            target.append(b)
    save_alias_groups(groups, path)


def _alias_match(a: str, b: str, alias_groups: list[list[str]]) -> bool:
    return any(a in group and b in group for group in alias_groups)


def company_names_match(name_a: str, name_b: str, alias_groups: list[list[str]]) -> MatchResult:
    a, b = normalize_company_name(name_a), normalize_company_name(name_b)
    if a == "" or b == "":
        return MatchResult(status="no_match", score=0.0)
    if a == b:
        return MatchResult(status="match", score=100.0)
    if _alias_match(a, b, alias_groups):
        return MatchResult(status="match", score=100.0)

    score = fuzz.token_sort_ratio(a, b)
    if score >= HIGH_THRESHOLD:
        return MatchResult(status="match", score=score)
    if score < LOW_THRESHOLD:
        return MatchResult(status="no_match", score=score)
    return MatchResult(status="review", score=score)


def domain_is_company_variant(domain: str, company_name: str) -> bool:
    if not domain or not company_name:
        return False
    label = domain.split(".")[0]
    company_norm = normalize_company_name(company_name).replace(" ", "")
    if not company_norm:
        return False
    return fuzz.ratio(label, company_norm) >= LOW_THRESHOLD
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pip install -r requirements.txt` then `python -m pytest tests/test_matching.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add core/matching.py tests/test_matching.py
git commit -m "feat: add domain/company-name matching utilities with alias table"
```

---

## Task 4: Excel I/O — Generic Sheet Reading & Backup

**Files:**
- Create: `core/excel_io.py`
- Test: `tests/test_excel_io_generic.py`

**Interfaces:**
- Produces: `list_sheet_names(path: str) -> list[str]`, `read_sheet_as_dataframe(path: str, sheet_name: str) -> pandas.DataFrame`, `backup_file(path: str) -> str` (returns backup file path), `require_columns(df: pandas.DataFrame, columns: list[str], file_label: str) -> None` (raises `ValueError` naming the file and the missing column(s) if any are absent).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_excel_io_generic.py
import os
import openpyxl
import pytest

from core.excel_io import list_sheet_names, read_sheet_as_dataframe, backup_file, require_columns


def _make_workbook(path: str) -> None:
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Exclusion"
    ws1.append(["Account Name", "Domain"])
    ws1.append(["Adecco UK Ltd", "adecco.co.uk"])
    ws2 = wb.create_sheet("Persona titles ")
    ws2.append(["AUDIENCE : CSUITE"])
    wb.save(path)


def test_list_sheet_names(tmp_path):
    path = str(tmp_path / "exclusion.xlsx")
    _make_workbook(path)
    assert list_sheet_names(path) == ["Exclusion", "Persona titles "]


def test_read_sheet_as_dataframe(tmp_path):
    path = str(tmp_path / "exclusion.xlsx")
    _make_workbook(path)
    df = read_sheet_as_dataframe(path, "Exclusion")
    assert list(df.columns) == ["Account Name", "Domain"]
    assert df.iloc[0]["Domain"] == "adecco.co.uk"


def test_backup_file_creates_timestamped_copy(tmp_path):
    path = str(tmp_path / "accumulated.xlsx")
    _make_workbook(path)

    backup_path = backup_file(path)

    assert os.path.isfile(backup_path)
    assert backup_path != path
    assert "accumulated_backup_" in os.path.basename(backup_path)
    assert list_sheet_names(backup_path) == list_sheet_names(path)


def test_require_columns_passes_when_all_present(tmp_path):
    path = str(tmp_path / "exclusion.xlsx")
    _make_workbook(path)
    df = read_sheet_as_dataframe(path, "Exclusion")

    require_columns(df, ["Account Name", "Domain"], file_label=path)  # should not raise


def test_require_columns_raises_clear_error_naming_file_and_column(tmp_path):
    path = str(tmp_path / "exclusion.xlsx")
    _make_workbook(path)
    df = read_sheet_as_dataframe(path, "Exclusion")

    with pytest.raises(ValueError) as exc_info:
        require_columns(df, ["Account Name", "Email"], file_label=path)

    message = str(exc_info.value)
    assert path in message
    assert "Email" in message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_excel_io_generic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.excel_io'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/excel_io.py
import datetime
import shutil
from pathlib import Path

import openpyxl
import pandas as pd


def list_sheet_names(path: str) -> list[str]:
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        return wb.sheetnames
    finally:
        wb.close()


def read_sheet_as_dataframe(path: str, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet_name)


def backup_file(path: str) -> str:
    source = Path(path)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = source.with_name(f"{source.stem}_backup_{timestamp}{source.suffix}")
    shutil.copy2(source, backup_path)
    return str(backup_path)


def require_columns(df: pd.DataFrame, columns: list[str], file_label: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(
            f"'{file_label}' is missing expected column(s): {', '.join(missing)}. "
            f"Found columns: {', '.join(str(c) for c in df.columns)}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_excel_io_generic.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/excel_io.py tests/test_excel_io_generic.py
git commit -m "feat: add generic Excel sheet reading and backup helpers"
```

---

## Task 5: Excel I/O — Accumulated Report Append Logic

**Files:**
- Modify: `core/excel_io.py`
- Test: `tests/test_excel_io_append.py`

**Interfaces:**
- Consumes: `core.models.FieldMapping` (Task 1).
- Produces: `append_leads(accumulated_path: str, tab_name: str, leads_df: pandas.DataFrame, field_mapping: FieldMapping, run_date: str, reasons: dict[int, str] | None = None) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_excel_io_append.py
import openpyxl
import pandas as pd

from core.excel_io import append_leads
from core.models import FieldMapping


def _make_accumulated_workbook(path: str) -> None:
    wb = openpyxl.Workbook()
    lookup = wb.active
    lookup.title = "Lookup"
    lookup.append(["CID", "Name"])
    lookup.append([100, "Campaign A"])
    lookup.append([200, "Campaign B"])

    accumulated = wb.create_sheet("Accumulated")
    accumulated.append(["Date", "CID", "Campaign Name", "Comment", "emailaddress", "firstname", "lastname", "company"])
    accumulated.append(["2026-01-01", 100, "=VLOOKUP(B2,Lookup!A:B,2,0)", "Delivered", "a@x.com", "A", "B", "X"])

    refund = wb.create_sheet("Refund")
    refund.append(["Date", "CID", "Campaign Name", "Comment", "emailaddress", "firstname", "lastname", "company", "Reason"])

    wb.save(path)


def _field_mapping() -> FieldMapping:
    return FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                         company="company", cid="CID")


def test_append_leads_to_accumulated_fills_by_header_and_shifts_formula(tmp_path):
    path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_workbook(path)

    leads_df = pd.DataFrame([
        {"CID": 200, "emailaddress": "c@y.com", "firstname": "C", "lastname": "D", "company": "Y"},
    ])

    append_leads(path, "Accumulated", leads_df, _field_mapping(), run_date="2026-08-08")

    wb = openpyxl.load_workbook(path)
    ws = wb["Accumulated"]

    assert ws.max_row == 3
    new_row = {cell.value for cell in ws[1]}
    assert new_row == {"Date", "CID", "Campaign Name", "Comment", "emailaddress", "firstname", "lastname", "company"}

    values = {ws.cell(row=1, column=c).value: ws.cell(row=3, column=c).value for c in range(1, 9)}
    assert values["Date"] == "2026-08-08"
    assert values["CID"] == 200
    assert values["Campaign Name"] == "=VLOOKUP(B3,Lookup!A:B,2,0)"
    assert values["Comment"] is None
    assert values["emailaddress"] == "c@y.com"
    assert values["firstname"] == "C"
    assert values["lastname"] == "D"
    assert values["company"] == "Y"


def test_append_leads_to_refund_fills_reason_column(tmp_path):
    path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_workbook(path)

    leads_df = pd.DataFrame([
        {"CID": 200, "emailaddress": "c@y.com", "firstname": "C", "lastname": "D", "company": "Y"},
    ], index=[42])

    append_leads(path, "Refund", leads_df, _field_mapping(), run_date="2026-08-08",
                 reasons={42: "Exclusion - domain; TAL - not found"})

    wb = openpyxl.load_workbook(path)
    ws = wb["Refund"]
    values = {ws.cell(row=1, column=c).value: ws.cell(row=2, column=c).value for c in range(1, 10)}
    assert values["Reason"] == "Exclusion - domain; TAL - not found"
    assert values["CID"] == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_excel_io_append.py -v`
Expected: FAIL with `ImportError: cannot import name 'append_leads' from 'core.excel_io'`

- [ ] **Step 3: Write minimal implementation**

```python
# Append to core/excel_io.py
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter

from core.models import FieldMapping

_FIELD_SYNONYMS = {
    "email": ["email", "emailaddress", "email address"],
    "first_name": ["firstname", "first name"],
    "last_name": ["lastname", "last name"],
    "company": ["company", "companyname", "company name"],
    "cid": ["cid"],
}


def _resolve_field_attr(header_norm: str) -> str | None:
    for attr, synonyms in _FIELD_SYNONYMS.items():
        if header_norm in synonyms:
            return attr
    return None


def append_leads(
    accumulated_path: str,
    tab_name: str,
    leads_df: pd.DataFrame,
    field_mapping: FieldMapping,
    run_date: str,
    reasons: dict[int, str] | None = None,
) -> None:
    wb = openpyxl.load_workbook(accumulated_path)
    ws = wb[tab_name]

    headers = [cell.value for cell in ws[1]]
    lead_headers_norm = {str(h).strip().lower(): h for h in leads_df.columns}

    formula_template: dict[str, tuple[str, str]] = {}
    if ws.max_row >= 2:
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=2, column=col_idx)
            if isinstance(cell.value, str) and cell.value.startswith("="):
                formula_template[header] = (cell.value, cell.coordinate)

    next_row = ws.max_row + 1
    for row_offset, (idx, lead_row) in enumerate(leads_df.iterrows()):
        excel_row = next_row + row_offset
        for col_idx, header in enumerate(headers, start=1):
            if header is None:
                continue
            header_norm = str(header).strip().lower()
            cell = ws.cell(row=excel_row, column=col_idx)

            if header_norm == "date":
                cell.value = run_date
            elif header in formula_template:
                formula, origin_ref = formula_template[header]
                col_letter = get_column_letter(col_idx)
                cell.value = Translator(formula, origin=origin_ref).translate_formula(f"{col_letter}{excel_row}")
            elif header_norm in ("comment", "status"):
                cell.value = None
            elif header_norm == "reason":
                cell.value = (reasons or {}).get(idx, "")
            else:
                attr = _resolve_field_attr(header_norm)
                if attr:
                    source_col = getattr(field_mapping, attr)
                    cell.value = lead_row.get(source_col, "")
                elif header_norm in lead_headers_norm:
                    cell.value = lead_row.get(lead_headers_norm[header_norm], "")
                else:
                    cell.value = None

    wb.save(accumulated_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_excel_io_append.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add core/excel_io.py tests/test_excel_io_append.py
git commit -m "feat: append leads to Accumulated/Refund tabs by header-name match"
```

---

## Task 6: Duplicate Check

**Files:**
- Create: `core/checks/__init__.py`
- Create: `core/checks/duplicate.py`
- Test: `tests/checks/test_duplicate.py`

**Interfaces:**
- Consumes: `core.models.FieldMapping`, `core.matching.extract_domain`, `core.matching.normalize_company_name`, `core.matching.domain_is_company_variant`, `core.check_result.CheckOutcome`.
- Produces: `check_duplicates(new_leads: pandas.DataFrame, accumulated_leads: pandas.DataFrame, field_mapping: FieldMapping) -> CheckOutcome`.

- [ ] **Step 1: Write the failing test**

```python
# tests/checks/test_duplicate.py
import pandas as pd

from core.checks.duplicate import check_duplicates
from core.models import FieldMapping

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")


def test_exact_email_match_against_accumulated_fails():
    new_leads = pd.DataFrame([
        {"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail[0] == "Duplicate - exact email"


def test_exact_email_match_within_new_batch_fails():
    new_leads = pd.DataFrame([
        {"emailaddress": "a@x.com", "firstname": "A", "lastname": "B", "company": "X", "CID": 1},
        {"emailaddress": "a@x.com", "firstname": "A", "lastname": "B", "company": "X", "CID": 1},
    ])
    accumulated = pd.DataFrame(columns=["emailaddress", "firstname", "lastname", "company", "CID"])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail[1] == "Duplicate - exact email"
    assert 0 not in outcome.fail


def test_same_name_same_company_variant_domain_fails():
    new_leads = pd.DataFrame([
        {"emailaddress": "andy@gooooogle.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google Inc", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail[0] == "Duplicate - name/company match"


def test_same_name_different_unrelated_company_goes_to_review():
    new_leads = pd.DataFrame([
        {"emailaddress": "andy@unrelatedco.com", "firstname": "Andy", "lastname": "Jones", "company": "Unrelated Co", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert 0 not in outcome.fail
    assert 0 in outcome.review


def test_no_match_for_distinct_leads():
    new_leads = pd.DataFrame([
        {"emailaddress": "ida@scania.com", "firstname": "Ida", "lastname": "Ekendahl", "company": "Scania", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "alexey@danone.com", "firstname": "Alexey", "lastname": "Pavlov", "company": "Danone", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail == {}
    assert outcome.review == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/checks/test_duplicate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.checks'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/checks/__init__.py
```

```python
# core/checks/duplicate.py
import pandas as pd

from core.check_result import CheckOutcome
from core.matching import extract_domain, normalize_company_name, domain_is_company_variant
from core.models import FieldMapping


def _norm(value) -> str:
    return str(value).strip().lower() if value is not None and str(value) != "nan" else ""


def _name_key(row: dict, fm: FieldMapping) -> tuple[str, str]:
    return (_norm(row.get(fm.first_name, "")), _norm(row.get(fm.last_name, "")))


def check_duplicates(new_leads: pd.DataFrame, accumulated_leads: pd.DataFrame, field_mapping: FieldMapping) -> CheckOutcome:
    outcome = CheckOutcome()
    fm = field_mapping

    acc_emails: set[str] = set()
    acc_by_name: dict[tuple[str, str], list[dict]] = {}
    for _, row in accumulated_leads.iterrows():
        row_dict = row.to_dict()
        email = _norm(row_dict.get(fm.email, ""))
        if email:
            acc_emails.add(email)
        key = _name_key(row_dict, fm)
        if key != ("", ""):
            acc_by_name.setdefault(key, []).append(row_dict)

    seen_emails: dict[str, int] = {}
    seen_by_name: dict[tuple[str, str], list[int]] = {}

    for idx, row in new_leads.iterrows():
        row_dict = row.to_dict()
        email = _norm(row_dict.get(fm.email, ""))
        company = str(row_dict.get(fm.company, "") or "")
        key = _name_key(row_dict, fm)

        if email and (email in acc_emails or email in seen_emails):
            outcome.fail[idx] = "Duplicate - exact email"
        else:
            candidates = list(acc_by_name.get(key, []))
            for other_idx in seen_by_name.get(key, []):
                candidates.append(new_leads.loc[other_idx].to_dict())

            if key != ("", "") and candidates:
                hard_match = False
                for other in candidates:
                    other_company = str(other.get(fm.company, "") or "")
                    domain = extract_domain(email)
                    same_company = (
                        normalize_company_name(company) != ""
                        and normalize_company_name(company) == normalize_company_name(other_company)
                    )
                    if same_company or domain_is_company_variant(domain, other_company):
                        hard_match = True
                        break
                if hard_match:
                    outcome.fail[idx] = "Duplicate - name/company match"
                else:
                    outcome.review[idx] = "Duplicate - same name, ambiguous company match"

        if email:
            seen_emails.setdefault(email, idx)
        if key != ("", ""):
            seen_by_name.setdefault(key, []).append(idx)

    return outcome
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/checks/test_duplicate.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/checks/__init__.py core/checks/duplicate.py tests/checks/test_duplicate.py
git commit -m "feat: add duplicate lead check"
```

---

## Task 7: Leadcap Check

**Files:**
- Create: `core/checks/leadcap.py`
- Test: `tests/checks/test_leadcap.py`

**Interfaces:**
- Consumes: `core.models.FieldMapping`, `core.models.LeadcapConfig`, `core.models.LeadcapSegment`, `core.check_result.CheckOutcome`.
- Produces: `check_leadcap(new_leads: pandas.DataFrame, field_mapping: FieldMapping, config: LeadcapConfig, purchased_reports: dict[str, pandas.DataFrame]) -> CheckOutcome` (flat mode uses key `"_flat_"` in `purchased_reports`), `validate_purchased_report_cids(report: pandas.DataFrame, expected_cids: list[str], cid_column: str) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/checks/test_leadcap.py
import pandas as pd

from core.checks.leadcap import check_leadcap, validate_purchased_report_cids
from core.models import FieldMapping, LeadcapConfig, LeadcapSegment

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")


def test_flat_leadcap_fails_when_count_meets_cap():
    config = LeadcapConfig(enabled=True, segmented=False, flat_cap=2)
    new_leads = pd.DataFrame([{"CID": "118118", "emailaddress": "a@x.com"}])
    purchased = pd.DataFrame({"Campaign ID": ["118118", "118118"]})

    outcome = check_leadcap(new_leads, FM, config, {"_flat_": purchased})

    assert outcome.fail[0] == "Leadcap exceeded"


def test_flat_leadcap_passes_when_under_cap():
    config = LeadcapConfig(enabled=True, segmented=False, flat_cap=5)
    new_leads = pd.DataFrame([{"CID": "118118", "emailaddress": "a@x.com"}])
    purchased = pd.DataFrame({"Campaign ID": ["118118", "118118"]})

    outcome = check_leadcap(new_leads, FM, config, {"_flat_": purchased})

    assert outcome.fail == {}


def test_segmented_leadcap_pools_cap_across_cids_in_segment():
    config = LeadcapConfig(enabled=True, segmented=True, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778", "98779"], cap=5),
    ])
    new_leads = pd.DataFrame([{"CID": "98779", "emailaddress": "a@x.com"}])
    purchased = pd.DataFrame({"Campaign ID": ["98778", "98778", "98778", "98779", "98779"]})

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert outcome.fail[0] == "Leadcap exceeded"


def test_leadcap_disabled_produces_no_failures():
    config = LeadcapConfig(enabled=False)
    new_leads = pd.DataFrame([{"CID": "118118", "emailaddress": "a@x.com"}])

    outcome = check_leadcap(new_leads, FM, config, {})

    assert outcome.fail == {}


def test_cid_not_in_any_segment_is_skipped():
    config = LeadcapConfig(enabled=True, segmented=True, segments=[
        LeadcapSegment(name="AU Geo", cids=["114578"], cap=8),
    ])
    new_leads = pd.DataFrame([{"CID": "999999", "emailaddress": "a@x.com"}])

    outcome = check_leadcap(new_leads, FM, config, {"AU Geo": pd.DataFrame({"Campaign ID": []})})

    assert outcome.fail == {}


def test_validate_purchased_report_cids_flags_unexpected():
    report = pd.DataFrame({"Campaign ID": ["114578", "114568"]})
    unexpected = validate_purchased_report_cids(report, expected_cids=["114578"], cid_column="Campaign ID")
    assert unexpected == ["114568"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/checks/test_leadcap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.checks.leadcap'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/checks/leadcap.py
import pandas as pd

from core.check_result import CheckOutcome
from core.models import FieldMapping, LeadcapConfig


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

        if config.segmented:
            segment = next((s for s in config.segments if cid in s.cids), None)
            if segment is None:
                continue
            report = purchased_reports.get(segment.name)
            cap = segment.cap
            relevant_cids = segment.cids
        else:
            report = purchased_reports.get("_flat_")
            cap = config.flat_cap
            relevant_cids = None

        if report is None or cap is None or config.purchased_report_cid_column not in report.columns:
            continue

        cid_col = report[config.purchased_report_cid_column].astype(str).str.strip()
        count = cid_col.isin(relevant_cids).sum() if relevant_cids is not None else (cid_col == cid).sum()

        if count >= cap:
            outcome.fail[idx] = "Leadcap exceeded"

    return outcome


def validate_purchased_report_cids(report: pd.DataFrame, expected_cids: list[str], cid_column: str) -> list[str]:
    actual = set(report[cid_column].astype(str).str.strip().unique())
    expected = set(expected_cids)
    return sorted(actual - expected)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/checks/test_leadcap.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add core/checks/leadcap.py tests/checks/test_leadcap.py
git commit -m "feat: add leadcap check with flat and segmented-pooled modes"
```

---

## Task 8: Exclusion Check

**Files:**
- Create: `core/checks/exclusion.py`
- Test: `tests/checks/test_exclusion.py`

**Interfaces:**
- Consumes: `core.models.FieldMapping`, `core.models.ExclusionConfig`, `core.matching.extract_domain`, `core.matching.company_names_match`, `core.check_result.CheckOutcome`.
- Produces: `check_exclusion(new_leads: pandas.DataFrame, field_mapping: FieldMapping, config: ExclusionConfig, exclusion_df: pandas.DataFrame, alias_groups: list[list[str]]) -> CheckOutcome`.

- [ ] **Step 1: Write the failing test**

```python
# tests/checks/test_exclusion.py
import pandas as pd

from core.checks.exclusion import check_exclusion
from core.models import FieldMapping, ExclusionConfig

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

EXCLUSION_DF = pd.DataFrame([
    {"Account Name": "Adecco UK Ltd", "Domain": "adecco.co.uk"},
    {"Account Name": "Enerpac Tool Group, Inc.", "Domain": "enerpactoolgroup.com"},
])


def test_domain_match_fails():
    config = ExclusionConfig(enabled=True, check_company_name=False)
    new_leads = pd.DataFrame([{"emailaddress": "x@adecco.co.uk", "company": "Someone Else"}])

    outcome = check_exclusion(new_leads, FM, config, EXCLUSION_DF, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - domain"


def test_no_match_passes():
    config = ExclusionConfig(enabled=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@scania.com", "company": "Scania"}])

    outcome = check_exclusion(new_leads, FM, config, EXCLUSION_DF, alias_groups=[])

    assert outcome.fail == {}
    assert outcome.review == {}


def test_company_name_match_fails_when_toggled_on():
    config = ExclusionConfig(enabled=True, check_company_name=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@unrelated-domain.com", "company": "Enerpac Tool Group"}])

    outcome = check_exclusion(new_leads, FM, config, EXCLUSION_DF, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - company"


def test_disabled_check_produces_no_failures():
    config = ExclusionConfig(enabled=False)
    new_leads = pd.DataFrame([{"emailaddress": "x@adecco.co.uk", "company": "Adecco"}])

    outcome = check_exclusion(new_leads, FM, config, EXCLUSION_DF, alias_groups=[])

    assert outcome.fail == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/checks/test_exclusion.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.checks.exclusion'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/checks/exclusion.py
import pandas as pd

from core.check_result import CheckOutcome
from core.matching import extract_domain, company_names_match
from core.models import FieldMapping, ExclusionConfig


def check_exclusion(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: ExclusionConfig,
    exclusion_df: pd.DataFrame,
    alias_groups: list[list[str]],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    domains = set()
    if config.domain_column in exclusion_df.columns:
        domains = set(exclusion_df[config.domain_column].astype(str).str.strip().str.lower())

    companies: list[str] = []
    if config.check_company_name and config.company_column in exclusion_df.columns:
        companies = list(exclusion_df[config.company_column].astype(str))

    for idx, row in new_leads.iterrows():
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

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/checks/test_exclusion.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/checks/exclusion.py tests/checks/test_exclusion.py
git commit -m "feat: add exclusion list check"
```

---

## Task 9: TAL Check

**Files:**
- Create: `core/checks/tal.py`
- Test: `tests/checks/test_tal.py`

**Interfaces:**
- Consumes: `core.models.FieldMapping`, `core.models.TalConfig`, `core.models.TalSegment`, `core.matching.extract_domain`, `core.matching.company_names_match`, `core.check_result.CheckOutcome`.
- Produces: `check_tal(new_leads: pandas.DataFrame, field_mapping: FieldMapping, config: TalConfig, tal_sheets: dict[str, pandas.DataFrame], alias_groups: list[list[str]]) -> CheckOutcome` (flat mode reads `tal_sheets[config.flat_sheet_name]`).

- [ ] **Step 1: Write the failing test**

```python
# tests/checks/test_tal.py
import pandas as pd

from core.checks.tal import check_tal
from core.models import FieldMapping, TalConfig, TalSegment

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

TAL_SHEET1 = pd.DataFrame([
    {"Account Name": "Severn Trent Water Limited", "Domain": "stwater.co.uk"},
])


def test_flat_tal_domain_found_passes():
    config = TalConfig(enabled=True, segmented=False, flat_sheet_name="Sheet1")
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Severn Trent", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Sheet1": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail == {}


def test_flat_tal_domain_not_found_fails():
    config = TalConfig(enabled=True, segmented=False, flat_sheet_name="Sheet1")
    new_leads = pd.DataFrame([{"emailaddress": "x@notlisted.com", "company": "Not Listed", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Sheet1": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail[0] == "TAL - not found"


def test_segmented_tal_resolves_correct_sheet_by_cid():
    config = TalConfig(enabled=True, segmented=True, segments=[
        TalSegment(name="UK Geo", cids=["114578"], sheet_name="UKTab"),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Severn Trent", "CID": "114578"}])

    outcome = check_tal(new_leads, FM, config, {"UKTab": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail == {}


def test_company_name_required_and_not_found_fails_even_with_domain_match():
    config = TalConfig(enabled=True, segmented=False, flat_sheet_name="Sheet1", check_company_name=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Totally Different Co", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Sheet1": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail[0] == "TAL - company not found"


def test_disabled_check_produces_no_failures():
    config = TalConfig(enabled=False)
    new_leads = pd.DataFrame([{"emailaddress": "x@notlisted.com", "company": "X", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {}, alias_groups=[])

    assert outcome.fail == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/checks/test_tal.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.checks.tal'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/checks/tal.py
import pandas as pd

from core.check_result import CheckOutcome
from core.matching import extract_domain, company_names_match
from core.models import FieldMapping, TalConfig


def _resolve_tal_df(cid: str, config: TalConfig, tal_sheets: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    if config.segmented:
        segment = next((s for s in config.segments if cid in s.cids), None)
        if segment is None:
            return None
        return tal_sheets.get(segment.sheet_name)
    return tal_sheets.get(config.flat_sheet_name)


def check_tal(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: TalConfig,
    tal_sheets: dict[str, pd.DataFrame],
    alias_groups: list[list[str]],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    for idx, row in new_leads.iterrows():
        cid = str(row.get(field_mapping.cid, "")).strip()
        tal_df = _resolve_tal_df(cid, config, tal_sheets)
        if tal_df is None:
            continue

        domains = set()
        if config.domain_column in tal_df.columns:
            domains = set(tal_df[config.domain_column].astype(str).str.strip().str.lower())

        email = str(row.get(field_mapping.email, "") or "")
        domain = extract_domain(email)
        domain_found = domain in domains

        if not domain_found:
            outcome.fail[idx] = "TAL - not found"
            continue

        if config.check_company_name:
            company = str(row.get(field_mapping.company, "") or "")
            companies = list(tal_df[config.company_column].astype(str)) if config.company_column in tal_df.columns else []
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

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/checks/test_tal.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/checks/tal.py tests/checks/test_tal.py
git commit -m "feat: add TAL check with flat and segmented modes"
```

---

## Task 10: Suppression Check

**Files:**
- Create: `core/checks/suppression.py`
- Test: `tests/checks/test_suppression.py`

**Interfaces:**
- Consumes: `core.models.FieldMapping`, `core.models.SuppressionConfig`, `core.matching.extract_domain`, `core.matching.company_names_match`, `core.check_result.CheckOutcome`.
- Produces: `check_suppression(new_leads: pandas.DataFrame, field_mapping: FieldMapping, config: SuppressionConfig, suppression_df: pandas.DataFrame, alias_groups: list[list[str]]) -> CheckOutcome`.

- [ ] **Step 1: Write the failing test**

```python
# tests/checks/test_suppression.py
import pandas as pd

from core.checks.suppression import check_suppression
from core.models import FieldMapping, SuppressionConfig

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

SUPPRESSION_DF = pd.DataFrame([
    {"Account Name": "Acme Corp", "Domain": "acme.com", "Email": "known@acme.com"},
])


def test_domain_check_fails():
    config = SuppressionConfig(enabled=True, check_domain=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@acme.com", "company": "Someone"}])

    outcome = check_suppression(new_leads, FM, config, SUPPRESSION_DF, alias_groups=[])

    assert outcome.fail[0] == "Suppression - domain"


def test_email_check_fails():
    config = SuppressionConfig(enabled=True, check_email=True)
    new_leads = pd.DataFrame([{"emailaddress": "known@acme.com", "company": "Someone"}])

    outcome = check_suppression(new_leads, FM, config, SUPPRESSION_DF, alias_groups=[])

    assert outcome.fail[0] == "Suppression - email"


def test_company_check_fails_when_toggled_on():
    config = SuppressionConfig(enabled=True, check_company_name=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@other.com", "company": "Acme Corp"}])

    outcome = check_suppression(new_leads, FM, config, SUPPRESSION_DF, alias_groups=[])

    assert outcome.fail[0] == "Suppression - company"


def test_no_toggles_enabled_produces_no_failures_even_if_row_matches():
    config = SuppressionConfig(enabled=True, check_domain=False, check_company_name=False, check_email=False)
    new_leads = pd.DataFrame([{"emailaddress": "known@acme.com", "company": "Acme Corp"}])

    outcome = check_suppression(new_leads, FM, config, SUPPRESSION_DF, alias_groups=[])

    assert outcome.fail == {}


def test_disabled_check_produces_no_failures():
    config = SuppressionConfig(enabled=False, check_domain=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@acme.com", "company": "Someone"}])

    outcome = check_suppression(new_leads, FM, config, SUPPRESSION_DF, alias_groups=[])

    assert outcome.fail == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/checks/test_suppression.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.checks.suppression'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/checks/suppression.py
import pandas as pd

from core.check_result import CheckOutcome
from core.matching import extract_domain, company_names_match
from core.models import FieldMapping, SuppressionConfig


def check_suppression(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: SuppressionConfig,
    suppression_df: pd.DataFrame,
    alias_groups: list[list[str]],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    domains = set()
    if config.check_domain and config.domain_column in suppression_df.columns:
        domains = set(suppression_df[config.domain_column].astype(str).str.strip().str.lower())

    emails = set()
    if config.check_email and config.email_column in suppression_df.columns:
        emails = set(suppression_df[config.email_column].astype(str).str.strip().str.lower())

    companies: list[str] = []
    if config.check_company_name and config.company_column in suppression_df.columns:
        companies = list(suppression_df[config.company_column].astype(str))

    for idx, row in new_leads.iterrows():
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

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/checks/test_suppression.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/checks/suppression.py tests/checks/test_suppression.py
git commit -m "feat: add suppression list check"
```

---

## Task 11: Dedupe List Check

**Files:**
- Create: `core/checks/dedupe_list.py`
- Test: `tests/checks/test_dedupe_list.py`

**Interfaces:**
- Consumes: `core.models.FieldMapping`, `core.models.DedupeListConfig`, `core.check_result.CheckOutcome`.
- Produces: `check_dedupe_list(new_leads: pandas.DataFrame, field_mapping: FieldMapping, config: DedupeListConfig, dedupe_df: pandas.DataFrame) -> CheckOutcome`.

- [ ] **Step 1: Write the failing test**

```python
# tests/checks/test_dedupe_list.py
import pandas as pd

from core.checks.dedupe_list import check_dedupe_list
from core.models import FieldMapping, DedupeListConfig

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

DEDUPE_DF = pd.DataFrame([{"Email": "delivered@acme.com"}])


def test_email_in_dedupe_list_fails():
    config = DedupeListConfig(enabled=True)
    new_leads = pd.DataFrame([{"emailaddress": "delivered@acme.com"}])

    outcome = check_dedupe_list(new_leads, FM, config, DEDUPE_DF)

    assert outcome.fail[0] == "Dedupe list - email match"


def test_email_not_in_dedupe_list_passes():
    config = DedupeListConfig(enabled=True)
    new_leads = pd.DataFrame([{"emailaddress": "new@acme.com"}])

    outcome = check_dedupe_list(new_leads, FM, config, DEDUPE_DF)

    assert outcome.fail == {}


def test_disabled_check_produces_no_failures():
    config = DedupeListConfig(enabled=False)
    new_leads = pd.DataFrame([{"emailaddress": "delivered@acme.com"}])

    outcome = check_dedupe_list(new_leads, FM, config, DEDUPE_DF)

    assert outcome.fail == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/checks/test_dedupe_list.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.checks.dedupe_list'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/checks/dedupe_list.py
import pandas as pd

from core.check_result import CheckOutcome
from core.models import FieldMapping, DedupeListConfig


def check_dedupe_list(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: DedupeListConfig,
    dedupe_df: pd.DataFrame,
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    emails = set()
    if config.email_column in dedupe_df.columns:
        emails = set(dedupe_df[config.email_column].astype(str).str.strip().str.lower())

    for idx, row in new_leads.iterrows():
        email = str(row.get(field_mapping.email, "") or "").strip().lower()
        if email and email in emails:
            outcome.fail[idx] = "Dedupe list - email match"

    return outcome
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/checks/test_dedupe_list.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add core/checks/dedupe_list.py tests/checks/test_dedupe_list.py
git commit -m "feat: add dedupe list check"
```

---

## Task 12: Pipeline Orchestration

**Files:**
- Create: `core/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `core.models.ClientProfile` and all six check functions from Task 6–11.
- Produces: `PipelineResult(valid_indices: list[int], refund_reasons: dict[int, str], review_reasons: dict[int, list[str]])` and `run_pipeline(new_leads: pandas.DataFrame, profile: ClientProfile, accumulated_leads: pandas.DataFrame, reference_data: dict, alias_groups: list[list[str]]) -> PipelineResult`.
  `reference_data` keys used: `"exclusion_df"`, `"tal_sheets"`, `"suppression_df"`, `"dedupe_df"`, `"purchased_reports"` — each optional, only read when the corresponding check is enabled.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py
import pandas as pd

from core.pipeline import run_pipeline
from core.models import (
    ClientProfile, FieldMapping, DuplicateConfig, ExclusionConfig, LeadcapConfig,
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
        exclusion=ExclusionConfig(enabled=True, sheet_name="Exclusion"),
    )
    new_leads = pd.DataFrame([{"emailaddress": "a@excluded.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    accumulated = pd.DataFrame([{"emailaddress": "a@excluded.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    exclusion_df = pd.DataFrame([{"Account Name": "Excluded Co", "Domain": "excluded.com"}])

    result = run_pipeline(
        new_leads, profile, accumulated,
        reference_data={"exclusion_df": exclusion_df},
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
        exclusion=ExclusionConfig(enabled=True, sheet_name="Exclusion"),
    )
    new_leads = pd.DataFrame([{"emailaddress": "andy@excluded.com", "firstname": "Andy", "lastname": "Jones", "company": "Unrelated", "CID": "1"}])
    accumulated = pd.DataFrame([{"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": "1"}])
    exclusion_df = pd.DataFrame([{"Account Name": "Excluded Co", "Domain": "excluded.com"}])

    result = run_pipeline(
        new_leads, profile, accumulated,
        reference_data={"exclusion_df": exclusion_df},
        alias_groups=[],
    )

    assert 0 in result.refund_reasons
    assert 0 not in result.review_reasons
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.pipeline'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/pipeline.py
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
                                         reference_data.get("exclusion_df", pd.DataFrame()), alias_groups))

    if profile.tal.enabled:
        merge(tal.check_tal(new_leads, fm, profile.tal,
                             reference_data.get("tal_sheets", {}), alias_groups))

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

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/pipeline.py tests/test_pipeline.py
git commit -m "feat: add pipeline orchestration across all six checks"
```

---

## Task 13: Streamlit Client Setup Page

**Files:**
- Create: `pages/1_Client_Setup.py`
- Create: `core/aliases_path.py`

**Interfaces:**
- Consumes: `core.profile_store.{save_profile, load_profile, list_profile_names}`, `core.excel_io.list_sheet_names`, all model dataclasses from Task 1.
- Produces: `core/aliases_path.py` exposes `ALIASES_PATH = "aliases/company_aliases.json"`, imported by this page and by Task 14, so both agree on one location.

No automated test for this task — Streamlit pages are verified by running the app. Steps below build the page incrementally and verify each part in the browser.

- [ ] **Step 1: Create the shared aliases path constant**

```python
# core/aliases_path.py
ALIASES_PATH = "aliases/company_aliases.json"
```

- [ ] **Step 2: Write the Client Setup page**

```python
# pages/1_Client_Setup.py
import streamlit as st

from core.aliases_path import ALIASES_PATH
from core.excel_io import list_sheet_names
from core.models import (
    ClientProfile, FieldMapping, DuplicateConfig, LeadcapConfig, LeadcapSegment,
    ExclusionConfig, TalConfig, TalSegment, SuppressionConfig, DedupeListConfig,
)
from core.profile_store import save_profile, load_profile, list_profile_names

st.title("Client Setup")

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
accumulated_path = st.text_input("Accumulated Report path",
                                  value=profile.accumulated_report_path if profile else "")
tal_path = st.text_input("TAL file path", value=(profile.tal_path if profile else "") or "")
exclusion_path = st.text_input("Exclusion List path", value=(profile.exclusion_path if profile else "") or "")
suppression_path = st.text_input("Suppression List path", value=(profile.suppression_path if profile else "") or "")
dedupe_list_path = st.text_input("Dedupe List path (optional)", value=(profile.dedupe_list_path if profile else "") or "")

st.header("Field Mapping (from a sample New Leads file)")
sample_leads_path = st.text_input("Path to a sample New Leads file, to read its column headers")
lead_headers: list[str] = []
if sample_leads_path:
    try:
        from core.excel_io import read_sheet_as_dataframe
        sheet = list_sheet_names(sample_leads_path)[0]
        lead_headers = list(read_sheet_as_dataframe(sample_leads_path, sheet).columns)
    except Exception as exc:
        st.error(f"Could not read headers from '{sample_leads_path}': {exc}")

if lead_headers:
    fm_email = st.selectbox("Email column", lead_headers)
    fm_first = st.selectbox("First Name column", lead_headers)
    fm_last = st.selectbox("Last Name column", lead_headers)
    fm_company = st.selectbox("Company column", lead_headers)
    fm_cid = st.selectbox("CID column", lead_headers)
else:
    st.info("Enter a sample New Leads file path above to map its columns.")
    fm_email = fm_first = fm_last = fm_company = fm_cid = ""

st.header("Checks")

duplicate_enabled = st.checkbox("Enable Duplicate check", value=profile.duplicate.enabled if profile else False)

st.subheader("Leadcap")
leadcap_enabled = st.checkbox("Enable Leadcap check", value=profile.leadcap.enabled if profile else False)
leadcap_segmented = st.checkbox("Leadcap is segmented by CID", value=profile.leadcap.segmented if profile else False)
leadcap_flat_cap = None
leadcap_segments: list[LeadcapSegment] = []
if leadcap_enabled and not leadcap_segmented:
    leadcap_flat_cap = st.number_input("Flat lead cap", min_value=0, step=1,
                                        value=profile.leadcap.flat_cap if profile and profile.leadcap.flat_cap else 0)
if leadcap_enabled and leadcap_segmented:
    st.caption("Define segments as: name | comma-separated CIDs | cap, one per line")
    default_text = "\n".join(f"{s.name}|{','.join(s.cids)}|{s.cap}" for s in (profile.leadcap.segments if profile else []))
    segment_text = st.text_area("Leadcap segments", value=default_text, key="leadcap_segments_text")
    for line in segment_text.splitlines():
        if not line.strip():
            continue
        name, cids_str, cap_str = [p.strip() for p in line.split("|")]
        leadcap_segments.append(LeadcapSegment(name=name, cids=[c.strip() for c in cids_str.split(",")], cap=int(cap_str)))

st.subheader("Exclusion")
exclusion_enabled = st.checkbox("Enable Exclusion check", value=profile.exclusion.enabled if profile else False)
exclusion_check_company = st.checkbox("Also check Exclusion by company name",
                                       value=profile.exclusion.check_company_name if profile else False)
exclusion_sheet = None
if exclusion_enabled and exclusion_path:
    try:
        sheets = list_sheet_names(exclusion_path)
        exclusion_sheet = st.selectbox("Which sheet holds the exclusion data?", sheets)
    except Exception as exc:
        st.error(f"Could not read sheets from '{exclusion_path}': {exc}")

st.subheader("TAL")
tal_enabled = st.checkbox("Enable TAL check", value=profile.tal.enabled if profile else False)
tal_check_company = st.checkbox("Also check TAL by company name", value=profile.tal.check_company_name if profile else False)
tal_segmented = st.checkbox("TAL is segmented by CID (different tabs per segment)",
                             value=profile.tal.segmented if profile else False)
tal_flat_sheet = None
tal_segments: list[TalSegment] = []
if tal_enabled and tal_path:
    try:
        tal_sheets = list_sheet_names(tal_path)
    except Exception as exc:
        st.error(f"Could not read sheets from '{tal_path}': {exc}")
        tal_sheets = []
    if tal_enabled and not tal_segmented and tal_sheets:
        tal_flat_sheet = st.selectbox("TAL sheet", tal_sheets)
    if tal_enabled and tal_segmented and tal_sheets:
        st.caption("Define segments as: name | comma-separated CIDs | sheet name, one per line")
        default_text = "\n".join(f"{s.name}|{','.join(s.cids)}|{s.sheet_name}" for s in (profile.tal.segments if profile else []))
        tal_segment_text = st.text_area("TAL segments", value=default_text, key="tal_segments_text")
        for line in tal_segment_text.splitlines():
            if not line.strip():
                continue
            name, cids_str, sheet_name = [p.strip() for p in line.split("|")]
            tal_segments.append(TalSegment(name=name, cids=[c.strip() for c in cids_str.split(",")], sheet_name=sheet_name))

st.subheader("Suppression")
suppression_enabled = st.checkbox("Enable Suppression check", value=profile.suppression.enabled if profile else False)
suppression_check_domain = st.checkbox("Check Suppression by domain", value=profile.suppression.check_domain if profile else True)
suppression_check_company = st.checkbox("Check Suppression by company name", value=profile.suppression.check_company_name if profile else False)
suppression_check_email = st.checkbox("Check Suppression by email", value=profile.suppression.check_email if profile else False)
suppression_sheet = None
if suppression_enabled and suppression_path:
    try:
        sheets = list_sheet_names(suppression_path)
        suppression_sheet = st.selectbox("Which sheet holds the suppression data?", sheets, key="suppression_sheet")
    except Exception as exc:
        st.error(f"Could not read sheets from '{suppression_path}': {exc}")

st.subheader("Dedupe list")
dedupe_enabled = st.checkbox("Enable Dedupe list check", value=profile.dedupe_list.enabled if profile else False)
dedupe_sheet = None
if dedupe_enabled and dedupe_list_path:
    try:
        sheets = list_sheet_names(dedupe_list_path)
        dedupe_sheet = st.selectbox("Which sheet holds the dedupe list data?", sheets, key="dedupe_sheet")
    except Exception as exc:
        st.error(f"Could not read sheets from '{dedupe_list_path}': {exc}")

if st.button("Save Client Profile"):
    if not client_name:
        st.error("Client name is required.")
    else:
        new_profile = ClientProfile(
            name=client_name,
            accumulated_report_path=accumulated_path,
            tal_path=tal_path or None,
            exclusion_path=exclusion_path or None,
            suppression_path=suppression_path or None,
            dedupe_list_path=dedupe_list_path or None,
            field_mapping=FieldMapping(email=fm_email, first_name=fm_first, last_name=fm_last,
                                        company=fm_company, cid=fm_cid) if fm_email else None,
            duplicate=DuplicateConfig(enabled=duplicate_enabled),
            leadcap=LeadcapConfig(enabled=leadcap_enabled, segmented=leadcap_segmented,
                                   flat_cap=int(leadcap_flat_cap) if leadcap_flat_cap else None,
                                   segments=leadcap_segments),
            exclusion=ExclusionConfig(enabled=exclusion_enabled, check_company_name=exclusion_check_company,
                                       sheet_name=exclusion_sheet or "Exclusion"),
            tal=TalConfig(enabled=tal_enabled, check_company_name=tal_check_company, segmented=tal_segmented,
                          flat_sheet_name=tal_flat_sheet, segments=tal_segments),
            suppression=SuppressionConfig(enabled=suppression_enabled, check_domain=suppression_check_domain,
                                           check_company_name=suppression_check_company,
                                           check_email=suppression_check_email,
                                           sheet_name=suppression_sheet or "Sheet1"),
            dedupe_list=DedupeListConfig(enabled=dedupe_enabled, sheet_name=dedupe_sheet or "Sheet1"),
        )
        saved_path = save_profile(new_profile)
        st.success(f"Saved profile to {saved_path}")
```

- [ ] **Step 3: Verify manually in the browser**

Run: `streamlit run app.py` (app.py is created in Task 15 — for now, run `streamlit run pages/1_Client_Setup.py` directly to verify this page in isolation)
In the browser: fill in `sample_data/Master_Output.xlsx` as the sample New Leads file, confirm the field-mapping dropdowns populate with `CID`, `firstname`, `lastname`, `emailaddress`, `company`, etc.; fill in `sample_data/Basware -Exclusion List.xlsx` as Exclusion path, enable Exclusion, and confirm the sheet dropdown lists `TAL`, `Persona titles `, `Expanded Job Titles`, `Exclusion`; select `Exclusion`; click Save Client Profile; confirm a success message and that `clients/<name>.json` is created on disk.

- [ ] **Step 4: Commit**

```bash
git add pages/1_Client_Setup.py core/aliases_path.py
git commit -m "feat: add Streamlit Client Setup page"
```

---

## Task 14: Streamlit Run Check Page

**Files:**
- Create: `pages/2_Run_Check.py`

**Interfaces:**
- Consumes: `core.profile_store.{load_profile, list_profile_names}`, `core.excel_io.{read_sheet_as_dataframe, append_leads, backup_file}`, `core.pipeline.run_pipeline`, `core.matching.{load_alias_groups, add_alias_pair}`, `core.checks.leadcap.validate_purchased_report_cids`, `core.aliases_path.ALIASES_PATH`.

No automated test — verified in the browser, following the same pattern as Task 13.

- [ ] **Step 1: Write the Run Check page**

```python
# pages/2_Run_Check.py
import datetime

import pandas as pd
import streamlit as st

from core.aliases_path import ALIASES_PATH
from core.checks.leadcap import validate_purchased_report_cids
from core.excel_io import read_sheet_as_dataframe, append_leads, backup_file, require_columns
from core.matching import load_alias_groups, add_alias_pair
from core.pipeline import run_pipeline
from core.profile_store import list_profile_names, load_profile

st.title("Run Check")

profile_names = list_profile_names()
if not profile_names:
    st.warning("No client profiles found. Create one on the Client Setup page first.")
    st.stop()

client_name = st.selectbox("Client", profile_names)
profile = load_profile(client_name)

new_leads_file = st.file_uploader("New Leads file", type=["xlsx"])

purchased_reports: dict[str, pd.DataFrame] = {}
if profile.leadcap.enabled:
    st.subheader("Leadcap: Purchased Lead Report(s)")
    if profile.leadcap.segmented:
        for segment in profile.leadcap.segments:
            uploaded = st.file_uploader(f"Purchased Lead Report for: {segment.name} — CID {', '.join(segment.cids)}",
                                         type=["csv"], key=f"purchased_{segment.name}")
            if uploaded:
                df = pd.read_csv(uploaded)
                unexpected = validate_purchased_report_cids(df, segment.cids, profile.leadcap.purchased_report_cid_column)
                if unexpected:
                    st.warning(f"'{segment.name}' file contains unexpected CIDs {unexpected} — wrong file?")
                purchased_reports[segment.name] = df
    else:
        uploaded = st.file_uploader("Purchased Lead Report", type=["csv"], key="purchased_flat")
        if uploaded:
            purchased_reports["_flat_"] = pd.read_csv(uploaded)

if st.button("Run Check") and new_leads_file:
    try:
        new_leads = pd.read_excel(new_leads_file)
        accumulated_leads = read_sheet_as_dataframe(profile.accumulated_report_path, "Accumulated")

        reference_data: dict = {"purchased_reports": purchased_reports}
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
        if profile.suppression.enabled:
            suppression_df = read_sheet_as_dataframe(profile.suppression_path, profile.suppression.sheet_name)
            reference_data["suppression_df"] = suppression_df
        if profile.dedupe_list.enabled:
            dedupe_df = read_sheet_as_dataframe(profile.dedupe_list_path, profile.dedupe_list.sheet_name)
            require_columns(dedupe_df, [profile.dedupe_list.email_column], profile.dedupe_list_path)
            reference_data["dedupe_df"] = dedupe_df

        alias_groups = load_alias_groups(ALIASES_PATH)
        result = run_pipeline(new_leads, profile, accumulated_leads, reference_data, alias_groups)

        st.session_state["run_new_leads"] = new_leads
        st.session_state["run_result"] = result
    except ValueError as exc:
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
            append_leads(profile.accumulated_report_path, "Accumulated",
                         new_leads.loc[result.valid_indices], profile.field_mapping, run_date)
        if result.refund_reasons:
            refund_indices = list(result.refund_reasons.keys())
            append_leads(profile.accumulated_report_path, "Refund",
                         new_leads.loc[refund_indices], profile.field_mapping, run_date,
                         reasons=result.refund_reasons)

        st.success("Accumulated Report updated.")
        del st.session_state["run_result"]
        del st.session_state["run_new_leads"]
```

- [ ] **Step 2: Verify manually in the browser**

Run: `streamlit run pages/2_Run_Check.py`
In the browser: select the Basware client profile created in Task 13; upload `sample_data/Master_Output.xlsx` as the New Leads file; click Run Check; confirm the summary shows a large refund count (since these leads are intentional duplicates of the Accumulated tab per the user's note) and that refund reasons include `Duplicate - exact email`; click Finalize; confirm a backup file appears next to the Accumulated Report and that its Refund tab gained new rows.

- [ ] **Step 3: Commit**

```bash
git add pages/2_Run_Check.py
git commit -m "feat: add Streamlit Run Check page with review and finalize flow"
```

---

## Task 15: App Entry Point & End-to-End Test with Real Sample Data

**Files:**
- Create: `app.py`
- Create: `aliases/company_aliases.json`
- Test: `tests/test_end_to_end_basware.py`

**Interfaces:**
- Consumes: everything from Tasks 1–12 plus the real files under `sample_data/`.

- [ ] **Step 1: Write the failing end-to-end test**

```python
# tests/test_end_to_end_basware.py
import shutil

import pandas as pd
import pytest

from core.excel_io import read_sheet_as_dataframe, append_leads, backup_file
from core.models import ClientProfile, FieldMapping, DuplicateConfig, ExclusionConfig
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
    profile = ClientProfile(
        name="Basware",
        accumulated_report_path=accumulated_copy,
        exclusion_path=f"{SAMPLE_DIR}/Basware -Exclusion List.xlsx",
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
        exclusion=ExclusionConfig(enabled=True, sheet_name="Exclusion"),
    )

    new_leads = pd.read_excel(f"{SAMPLE_DIR}/Master_Output.xlsx")
    accumulated_leads = read_sheet_as_dataframe(accumulated_copy, "Accumulated")
    exclusion_df = read_sheet_as_dataframe(profile.exclusion_path, "Exclusion")

    result = run_pipeline(
        new_leads, profile, accumulated_leads,
        reference_data={"exclusion_df": exclusion_df},
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

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_end_to_end_basware.py -v`
Expected: FAIL — at this point all imports exist from prior tasks, so this should actually mostly pass already once Tasks 1–12 are done; if it fails, the failure will point at a genuine gap (e.g. a column-name mismatch between the real sample file and the check logic) rather than a missing module. Treat any such failure as a real bug to fix in the relevant check/excel_io module, not a plan defect.

- [ ] **Step 3: Create app.py and the aliases seed file**

```python
# app.py
import streamlit as st

st.set_page_config(page_title="Lead QA Automation", layout="wide")
st.title("Lead QA & Upload Automation")
st.write("Use the sidebar to open **Client Setup** or **Run Check**.")
```

```json
// aliases/company_aliases.json
[]
```

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest -v`
Expected: PASS — all tests from Tasks 1–15 pass together

- [ ] **Step 5: Manual smoke test of the full app**

Run: `run.bat` (or `streamlit run app.py`)
In the browser: navigate to Client Setup, create/verify the Basware profile as in Task 13; navigate to Run Check, upload `sample_data/Master_Output.xlsx`, run the check, resolve any Needs Review items, click Finalize; confirm the Accumulated Report on disk was updated and a backup file sits alongside it.

- [ ] **Step 6: Commit**

```bash
git add app.py aliases/company_aliases.json tests/test_end_to_end_basware.py
git commit -m "feat: add app entry point and end-to-end test against real Basware sample data"
```

---

## Post-Plan Follow-Ups (not part of this plan)

- Lead QA output-template dump and portal-upload template mapping (explicitly out of scope per spec).
- Wiring the alias-table "add alias" action directly into the Needs Review UI (Task 14 leaves `add_alias_pair` available in `core/matching.py` but the Run Check page doesn't yet call it from the review buttons — worth adding once the core flow is validated with real runs).
