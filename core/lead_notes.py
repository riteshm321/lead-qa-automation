"""Pure, rule-based extraction behind the Lead Notes check
(core/checks/lead_notes.py): does a lead's narrative notes paragraph agree
with the lead's own email / phone / name / company / job title / other
column values? No Streamlit, no I/O, no AI or network calls.

Each field comes back as one of:
  MATCH          -- the lead's value is in the notes.
  MISMATCH       -- the notes hold a DIFFERENT value of that type. Only
                    emails and phone numbers can be recognized as "some
                    other value" by pattern, so only those two kinds can
                    ever be a mismatch.
  NOT_MENTIONED  -- the lead's value isn't in the notes.
  NO_LEAD_VALUE  -- the lead's own cell is blank, so there's nothing to
                    verify.
"""
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from core.custom_questions import NEAR_MISS_THRESHOLD, normalize_text
from core.matching import HIGH_THRESHOLD, normalize_company_name

MATCH = "match"
MISMATCH = "mismatch"
NOT_MENTIONED = "not_mentioned"
NO_LEAD_VALUE = "no_lead_value"

FIELD_KINDS = {
    "email": "Email", "phone": "Phone", "first_name": "First name", "last_name": "Last name",
    "company": "Company", "job_title": "Job title", "value": "Other value",
}

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
# A digit run that may contain spaces, dots, dashes and brackets -- but not
# commas or slashes, so "$10,000" and "09/20/2026" never look like phones.
_PHONE = re.compile(r"\+?\(?\d[\d\s().\-]{5,}\d")
_DATE_LIKE = re.compile(r"\d{4}[-.]\d{1,2}[-.]\d{1,2}|\d{1,2}[-.]\d{1,2}[-.]\d{2,4}")
_MIN_PHONE_DIGITS = 7
_MAX_PHONE_DIGITS = 15
# The last this-many digits decide a phone match, so a country code ("+1")
# present on one side only doesn't matter.
_PHONE_COMPARE_DIGITS = 10

_STOP_WORDS = {"of", "and", "the", "for", "at", "in", "a", "an", "to", "on"}
_TITLE_ABBREVIATIONS = {
    "vp": "vice president", "svp": "senior vice president", "evp": "executive vice president",
    "avp": "assistant vice president", "sr": "senior", "jr": "junior", "mgr": "manager",
    "dir": "director", "ops": "operations", "mktg": "marketing", "exec": "executive",
    "asst": "assistant", "assoc": "associate", "ceo": "chief executive officer",
    "cto": "chief technology officer", "cio": "chief information officer",
    "cfo": "chief financial officer", "coo": "chief operating officer", "cmo": "chief marketing officer",
    "ciso": "chief information security officer",
}


@dataclass
class FieldFinding:
    status: str
    found: str = ""          # the contradicting value seen in the notes (MISMATCH only)
    score: float | None = None


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if value != value:  # NaN
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def extract_emails(notes) -> list[str]:
    return [m.group(0).lower() for m in _EMAIL.finditer(_text(notes))]


def phone_digits(text) -> str:
    return re.sub(r"\D", "", _text(text))


def extract_phones(notes) -> list[str]:
    """Phone-number-looking text in the notes, as written. Dates and
    anything with fewer than 7 or more than 15 digits are skipped."""
    found: list[str] = []
    for m in _PHONE.finditer(_text(notes)):
        candidate = m.group(0).strip()
        digits = phone_digits(candidate)
        if not _MIN_PHONE_DIGITS <= len(digits) <= _MAX_PHONE_DIGITS:
            continue
        if _DATE_LIKE.fullmatch(candidate):
            continue
        found.append(candidate)
    return found


def _phones_match(a: str, b: str) -> bool:
    k = min(_PHONE_COMPARE_DIGITS, len(a), len(b))
    return k >= _MIN_PHONE_DIGITS and a[-k:] == b[-k:]


def _token_found(token: str, notes_tokens: set[str]) -> bool:
    if token in notes_tokens:
        return True
    # Typos only for real words; numbers and short words must be exact
    # ("10000" vs "100000" or "Al" vs "Alice" are different values).
    if len(token) < 4 or not token.isalpha():
        return False
    return any(fuzz.ratio(token, t) >= NEAR_MISS_THRESHOLD for t in notes_tokens if t.isalpha())


def _coverage(tokens: list[str], notes_tokens: set[str]) -> float:
    significant = [t for t in tokens if t not in _STOP_WORDS] or tokens
    if not significant:
        return 0.0
    return 100.0 * sum(_token_found(t, notes_tokens) for t in significant) / len(significant)


def _contains_phrase(phrase: str, text: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {text} "


def _fuzzy_phrase_score(phrase: str, text: str) -> float:
    """Best whole-word fuzzy match of `phrase` anywhere in `text` (both
    already normalized). Phrases with digits never fuzzy-match -- "$60,000"
    is not a typo of "$50,000"."""
    if not phrase or not text or any(ch.isdigit() for ch in phrase):
        return 0.0
    alignment = fuzz.partial_ratio_alignment(phrase, text)
    if alignment is None:
        return 0.0
    start, end = alignment.dest_start, alignment.dest_end
    while start > 0 and text[start - 1] != " ":
        start -= 1
    while end < len(text) and text[end] != " ":
        end += 1
    return float(fuzz.ratio(phrase, text[start:end]))


def _expand_title(text: str) -> list[str]:
    words: list[str] = []
    for word in normalize_text(text).split():
        words.extend(_TITLE_ABBREVIATIONS.get(word, word).split())
    return words


def check_email(notes, expected) -> FieldFinding:
    wanted = _text(expected).lower()
    if not wanted:
        return FieldFinding(NO_LEAD_VALUE)
    emails = extract_emails(notes)
    if wanted in emails:
        return FieldFinding(MATCH, score=100.0)
    if emails:
        return FieldFinding(MISMATCH, found=emails[0])
    return FieldFinding(NOT_MENTIONED)


def check_phone(notes, expected) -> FieldFinding:
    wanted = phone_digits(expected)
    if len(wanted) < _MIN_PHONE_DIGITS:
        return FieldFinding(NO_LEAD_VALUE)
    phones = extract_phones(notes)
    if any(_phones_match(wanted, phone_digits(p)) for p in phones):
        return FieldFinding(MATCH, score=100.0)
    if phones:
        return FieldFinding(MISMATCH, found=phones[0])
    return FieldFinding(NOT_MENTIONED)


def check_name(notes, expected) -> FieldFinding:
    tokens = normalize_text(expected).split()
    if not tokens:
        return FieldFinding(NO_LEAD_VALUE)
    notes_tokens = set(normalize_text(notes).split())
    if all(_token_found(t, notes_tokens) for t in tokens):
        return FieldFinding(MATCH, score=100.0)
    return FieldFinding(NOT_MENTIONED)


def check_company(notes, expected, alias_groups=()) -> FieldFinding:
    company = normalize_company_name(expected)
    if not company:
        return FieldFinding(NO_LEAD_VALUE)
    notes_norm = normalize_company_name(notes)
    names = [company] + [alias for group in alias_groups if company in group for alias in group
                         if alias and alias != company]
    if any(_contains_phrase(name, notes_norm) for name in names):
        return FieldFinding(MATCH, score=100.0)
    score = max(_fuzzy_phrase_score(name, notes_norm) for name in names)
    if score >= HIGH_THRESHOLD:
        return FieldFinding(MATCH, score=score)
    return FieldFinding(NOT_MENTIONED, score=score)


def check_job_title(notes, expected) -> FieldFinding:
    tokens = _expand_title(_text(expected))
    if not tokens:
        return FieldFinding(NO_LEAD_VALUE)
    score = _coverage(tokens, set(_expand_title(_text(notes))))
    return FieldFinding(MATCH if score == 100 else NOT_MENTIONED, score=score)


def check_value(notes, expected) -> FieldFinding:
    value = normalize_text(expected)
    if not value:
        return FieldFinding(NO_LEAD_VALUE)
    notes_norm = normalize_text(notes)
    if _contains_phrase(value, notes_norm):
        return FieldFinding(MATCH, score=100.0)
    score = max(_fuzzy_phrase_score(value, notes_norm), _coverage(value.split(), set(notes_norm.split())))
    if score >= 100 or (score >= NEAR_MISS_THRESHOLD and not any(ch.isdigit() for ch in value)):
        return FieldFinding(MATCH, score=score)
    return FieldFinding(NOT_MENTIONED, score=score)


def check_field(kind: str, notes, expected, alias_groups=()) -> FieldFinding:
    if kind == "email":
        return check_email(notes, expected)
    if kind == "phone":
        return check_phone(notes, expected)
    if kind in ("first_name", "last_name"):
        return check_name(notes, expected)
    if kind == "company":
        return check_company(notes, expected, alias_groups)
    if kind == "job_title":
        return check_job_title(notes, expected)
    return check_value(notes, expected)
