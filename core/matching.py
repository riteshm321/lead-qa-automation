import json
import os
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

LEGAL_SUFFIXES = {"inc", "llc", "corp", "corporation", "ltd", "co", "company", "plc", "oy"}

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
