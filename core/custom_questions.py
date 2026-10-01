"""Pure parsing/matching logic behind the Custom Questions check
(core/checks/custom_questions.py) and Client Setup's "Detect from leadfile"
helper. No Streamlit, no I/O.

The key design point: answers are found by MATCHING the configured allowed
answers inside a cell (longest first, normalized), never by naively
splitting on the separator -- real answer options routinely contain the
separator themselves (e.g. "a) Security / Governance (Injection, leakage)").
Whatever text is left over once every matched answer is removed is an
unrecognized answer. Splitting on the separator is only the fallback when
there is no allowed list to match against.
"""
import re
from dataclasses import dataclass, field

import pandas as pd
from rapidfuzz import fuzz

from core.models import CustomQuestionRule

# Same scorer family (rapidfuzz) the rest of the app's fuzzy matching uses
# (core/matching.py, core/fuzzy_match.py). Anything at or above this is a
# "near miss" -- a likely typo or slightly reworded question/answer -- and
# goes to Needs Review; below it is a clear mismatch (Refund). Deliberately
# stricter than core.matching.LOW_THRESHOLD (70): answer options within one
# question often share most of their words, so 70 would call genuinely
# different options near misses.
NEAR_MISS_THRESHOLD = 85.0

_SMART_CHARS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", " ": " ",
})

# "1." / "2)" / "3:" / "Q1" / "Q1:" / "q 2 -" at the very start. A bare
# leading number without punctuation ("2025 budget") is NOT numbering.
_LEADING_NUMBERING = re.compile(r"^\s*(?:q\s*\d+\s*[.):\-]*|\d+\s*[.):\-]+)\s*", re.IGNORECASE)
# The same numbering left dangling at the END of a combined-cell answer
# segment, just before the next question's text ("Red | Q2 " / "Red, 2. ").
_TRAILING_NUMBERING = re.compile(r"(?:^|(?<=[\s,;|]))(?:q\s*\d+\s*[.):\-]*|\d+\s*[.)])\s*$", re.IGNORECASE)
# "a)" / "(a)" / "a." / "a:" answer-option letter codes.
_LETTER_CODE = re.compile(r"^\s*(?:\(?[a-z]\)|[a-z][.:](?=\s))\s*", re.IGNORECASE)
# Letter codes used as answer delimiters: only ")"-style, and only at the
# start of the cell or right after a separator, so "(see b) below" or
# "e.g." inside an answer is never mistaken for one.
_LETTER_CODE_SPLIT = re.compile(r"(?:^|(?<=[,;|\n]))\s*\(?[a-z]\)\s+", re.IGNORECASE)
_EDGE_JUNK = " \t\r\n,;|:?=-"


def _norm_with_map(text: str) -> tuple[str, list[int]]:
    """Lowercased, smart-quote-folded text with every run of non-alphanumeric
    characters collapsed to one space -- plus, for each output character,
    the index of the input character it came from, so a match found in the
    normalized text can be sliced back out of the original."""
    chars: list[str] = []
    index: list[int] = []
    pending_space = False
    for i, ch in enumerate(text.translate(_SMART_CHARS)):
        if ch.isalnum():
            if pending_space and chars:
                chars.append(" ")
                index.append(i - 1)
            pending_space = False
            chars.append(ch.lower())
            index.append(i)
        else:
            pending_space = True
    return "".join(chars), index


def _cell_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def normalize_text(text) -> str:
    return _norm_with_map(_cell_text(text))[0]


def strip_numbering(text: str) -> str:
    return _LEADING_NUMBERING.sub("", text, count=1)


def normalize_question(text) -> str:
    return normalize_text(strip_numbering(_cell_text(text).translate(_SMART_CHARS)))


def strip_letter_code(text: str) -> str:
    return _LETTER_CODE.sub("", text, count=1)


def normalize_answer(text) -> str:
    return normalize_text(strip_letter_code(_cell_text(text).translate(_SMART_CHARS)))


def split_answers(text, separator: str = ",") -> list[str]:
    """Best-effort split of a cell into individual answers: on "a) ... , b)
    ..." letter codes when the cell starts with one, else on `separator`.
    Used for counting when there's no allowed list, for reporting leftover
    text, and by detect_question_rules."""
    text = _cell_text(text).strip()
    if not text:
        return []
    starts = [m.start() for m in _LETTER_CODE_SPLIT.finditer(text)]
    if starts and starts[0] == 0:
        bounds = starts + [len(text)]
        pieces = [text[bounds[i]:bounds[i + 1]] for i in range(len(starts))]
    elif separator:
        pieces = text.split(separator)
    else:
        pieces = [text]
    return [p.strip(_EDGE_JUNK) for p in pieces if p.strip(_EDGE_JUNK)]


@dataclass
class AnswerMatch:
    matched: list[str] = field(default_factory=list)          # allowed answers found (configured text)
    near_misses: list[tuple[str, str, float]] = field(default_factory=list)  # (given, closest allowed, score)
    unrecognized: list[str] = field(default_factory=list)     # given text matching nothing
    # Set only when there was no allowed list: the separator-split count.
    fallback_count: int | None = None

    @property
    def count(self) -> int:
        if self.fallback_count is not None:
            return self.fallback_count
        return len(self.matched) + len(self.near_misses) + len(self.unrecognized)


def _best_fuzzy(text_norm: str, candidates: list[tuple[str, str]]) -> tuple[float, str]:
    best_score, best = 0.0, ""
    for original, norm in candidates:
        score = fuzz.ratio(text_norm, norm)
        if score > best_score:
            best_score, best = score, original
    return best_score, best


def match_answers(text, allowed_answers: list[str], separator: str = ",") -> AnswerMatch:
    text = _cell_text(text)
    result = AnswerMatch()
    allowed = [(a, normalize_answer(a)) for a in allowed_answers if normalize_answer(a)]
    if not allowed:
        # No list to match against: every separator-split piece just counts.
        result.fallback_count = len(split_answers(text, separator))
        return result

    norm, index = _norm_with_map(text)
    consumed = [False] * len(norm)
    matched_set: set[str] = set()
    # Longest first so "cloud security" wins over a bare "cloud" inside it.
    for original, a_norm in sorted(allowed, key=lambda item: len(item[1]), reverse=True):
        start = 0
        while True:
            pos = norm.find(a_norm, start)
            if pos == -1:
                break
            end = pos + len(a_norm)
            start = pos + 1
            on_word_boundary = (pos == 0 or norm[pos - 1] == " ") and (end == len(norm) or norm[end] == " ")
            if not on_word_boundary or any(consumed[pos:end]):
                continue
            # Absorb this answer's own letter code ("a) ...") just before it.
            if pos >= 2 and norm[pos - 1] == " " and norm[pos - 2].isalpha() and (pos == 2 or norm[pos - 3] == " "):
                code_idx = index[pos - 2]
                if code_idx + 1 < len(text) and text[code_idx + 1] in ").:":
                    pos -= 2
            for i in range(pos, end):
                consumed[i] = True
            if original not in matched_set:
                matched_set.add(original)
                result.matched.append(original)

    # Report matched answers in the order they appear in the configured list.
    order = {a: i for i, (a, _n) in enumerate(allowed)}
    result.matched.sort(key=lambda a: order[a])

    for chunk in _leftover_chunks(text, norm, index, consumed):
        chunk_norm = normalize_answer(chunk)
        if len(chunk_norm) <= 1:
            continue  # a stray letter code / punctuation remnant
        score, closest = _best_fuzzy(chunk_norm, allowed)
        if score >= NEAR_MISS_THRESHOLD:
            result.near_misses.append((chunk, closest, score))
            continue
        for piece in split_answers(chunk, separator):
            piece_norm = normalize_answer(piece)
            if len(piece_norm) <= 1:
                continue
            score, closest = _best_fuzzy(piece_norm, allowed)
            if score >= NEAR_MISS_THRESHOLD:
                result.near_misses.append((piece, closest, score))
            else:
                result.unrecognized.append(piece)
    return result


def _unclosed(text: str) -> bool:
    return text.count("(") > text.count(")")


def _leftover_chunks(text: str, norm: str, index: list[int], consumed: list[bool]) -> list[str]:
    chunks: list[str] = []
    i = 0
    while i < len(norm):
        if consumed[i] or norm[i] == " ":
            i += 1
            continue
        j = i
        while j < len(norm) and not consumed[j]:
            j += 1
        last = j - 1
        while norm[last] == " ":
            last -= 1
        start, end = index[i], index[last] + 1
        chunk = text[start:end]
        # Keep a closing bracket that belongs to this chunk's own text (its
        # "a)" letter code doesn't count towards the balance).
        while _unclosed(strip_letter_code(chunk)) and end < len(text) and text[end] == ")":
            end += 1
            chunk = text[start:end]
        chunks.append(chunk.strip(_EDGE_JUNK))
        i = j
    return [c for c in chunks if c]


@dataclass
class LocatedQuestion:
    segment: str   # the answer text following this question in the cell
    score: float   # 100 = exact (normalized) match; lower = fuzzy near miss
    matched_text: str = ""  # the question wording as it actually appears in the cell


def _word_end(norm: str, pos: int) -> int:
    while pos < len(norm) and norm[pos] != " ":
        pos += 1
    return pos


def _word_start(norm: str, pos: int) -> int:
    while pos > 0 and norm[pos - 1] != " ":
        pos -= 1
    return pos


def locate_questions(cell, questions: list[str]) -> dict[int, LocatedQuestion]:
    """Find each of `questions` inside one combined cell. Returns
    {question index: LocatedQuestion} for the ones found; a question that
    can't be found even approximately is simply absent. Each question's
    answer segment runs from the end of its text to the start of the next
    found question (or the end of the cell)."""
    text = _cell_text(cell)
    norm, index = _norm_with_map(text)
    spans: dict[int, tuple[int, int, float]] = {}
    taken = [False] * len(norm)

    def _claim(i: int, start: int, end: int, score: float) -> None:
        spans[i] = (start, end, score)
        for k in range(start, end):
            taken[k] = True

    normalized_qs = [(i, normalize_question(q)) for i, q in enumerate(questions)]
    for i, q_norm in sorted(normalized_qs, key=lambda item: len(item[1]), reverse=True):
        if not q_norm:
            continue
        start = 0
        while True:
            pos = norm.find(q_norm, start)
            if pos == -1:
                break
            end = pos + len(q_norm)
            start = pos + 1
            if (pos == 0 or norm[pos - 1] == " ") and (end == len(norm) or norm[end] == " ") \
                    and not any(taken[pos:end]):
                _claim(i, pos, end, 100.0)
                break

    for i, q_norm in normalized_qs:
        if i in spans or not q_norm or not norm:
            continue
        alignment = fuzz.partial_ratio_alignment(q_norm, norm)
        if alignment is None or alignment.score < NEAR_MISS_THRESHOLD:
            continue
        pos, end = _word_start(norm, alignment.dest_start), _word_end(norm, alignment.dest_end)
        # Re-score against whole words: partial_ratio scores "like" inside
        # "likee" as a perfect 100, which would hide the near miss.
        score = fuzz.ratio(q_norm, norm[pos:end])
        if score < NEAR_MISS_THRESHOLD or any(taken[pos:end]):
            continue
        _claim(i, pos, end, min(float(score), 99.0))

    ordered = sorted(spans.items(), key=lambda item: item[1][0])
    located: dict[int, LocatedQuestion] = {}
    for n, (i, (start, end, score)) in enumerate(ordered):
        seg_start = index[end - 1] + 1
        seg_end = index[ordered[n + 1][1][0]] if n + 1 < len(ordered) else len(text)
        segment = text[seg_start:seg_end].strip(_EDGE_JUNK)
        if n + 1 < len(ordered):
            segment = _TRAILING_NUMBERING.sub("", segment).strip(_EDGE_JUNK)
        matched_text = text[index[start]:index[end - 1] + 1]
        located[i] = LocatedQuestion(segment=segment, score=score, matched_text=matched_text)
    return located


def looks_like_question(header) -> bool:
    text = _cell_text(header).strip()
    if not text:
        return False
    return text.endswith("?") or bool(re.match(r"^\s*(?:q\s*\d+|\d+\s*[.):\-])", text, re.IGNORECASE))


def _guess_separator(values: list[str]) -> str:
    counts = {sep: sum(v.count(sep) for v in values) for sep in (";", "|", ",")}
    best = max(counts, key=lambda sep: counts[sep])
    return best if counts[best] else ","


def detect_question_rules(df: pd.DataFrame) -> list[CustomQuestionRule]:
    """Propose one "header"-format rule per leadfile column whose header
    looks like a question (ends with "?" or starts with "1." / "Q1"-style
    numbering), pre-filled with the distinct answer options seen in that
    column, a guessed separator, and the largest number of answers any one
    lead gave as an "at most" count. Meant to be reviewed and edited before
    saving, not trusted blindly."""
    rules: list[CustomQuestionRule] = []
    for column in df.columns:
        if not looks_like_question(column):
            continue
        values = [_cell_text(v).strip() for v in df[column].tolist()]
        values = [v for v in values if v]
        separator = _guess_separator(values)
        options: dict[str, str] = {}
        max_count = 0
        for value in values:
            pieces = split_answers(value, separator)
            max_count = max(max_count, len(pieces))
            for piece in pieces:
                options.setdefault(normalize_answer(piece), piece)
        rules.append(CustomQuestionRule(
            format="header", column=str(column), question_text=str(column), mode="full",
            allowed_answers=sorted(options.values(), key=lambda a: a.lower()),
            count_rule="at_most" if max_count else "any", count=max(max_count, 1),
            separator=separator,
        ))
    return rules
