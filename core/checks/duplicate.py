import pandas as pd

from core.check_result import CheckOutcome, ReviewDetail
from core.matching import extract_domain, normalize_company_name
from core.models import FieldMapping


def _norm(value) -> str:
    return str(value).strip().lower() if value is not None and str(value) != "nan" else ""


def _name_key(row: dict, fm: FieldMapping) -> tuple[str, str]:
    return (_norm(row.get(fm.first_name, "")), _norm(row.get(fm.last_name, "")))


def _first3(value: str) -> str:
    return value[:3]


def _prefix3_key(row: dict, fm: FieldMapping, third_field: str) -> tuple[str, str, str] | None:
    # third_field is a value (company name or email domain), already
    # extracted/normalized by the caller — this only handles the shared
    # first-name/last-name-prefix part.
    first3 = _first3(_norm(row.get(fm.first_name, "")))
    last3 = _first3(_norm(row.get(fm.last_name, "")))
    third3 = _first3(_norm(third_field))
    if not first3 or not last3 or not third3:
        return None
    return (first3, last3, third3)


def check_duplicates(
    new_leads: pd.DataFrame, accumulated_leads: pd.DataFrame, field_mapping: FieldMapping,
    accumulated_field_mapping: FieldMapping | None = None,
) -> CheckOutcome:
    outcome = CheckOutcome()
    fm = field_mapping
    # The Accumulated Report frequently uses different header text than the
    # New Leads file (e.g. "Email Add." vs "emailaddress") — that's what
    # accumulated_field_mapping is for. Reading accumulated rows with the
    # New Leads mapping silently returns "" for every field when the
    # headers differ, so the duplicate check would never match anything.
    acc_fm = accumulated_field_mapping or field_mapping

    acc_emails: set[str] = set()
    # Each candidate carries the FieldMapping it was read with alongside the
    # row, so downstream lookups (company, email) always use the header
    # names that actually exist on that particular row — accumulated rows
    # use acc_fm, new-batch rows use fm, and the two can differ.
    acc_by_name: dict[tuple[str, str], list[tuple[dict, FieldMapping]]] = {}
    # Coarse "first 3 letters" indices for Rules 5/6 below — same
    # accumulated-vs-in-batch split as acc_by_name/seen_by_name: accumulated
    # entries are fixed from the start, so every matching new lead is
    # flagged (an accumulated lead already counts as delivered); the
    # in-batch "seen so far" indices start empty and grow, so of several
    # mutually-matching new leads only the first passes through clean and
    # the rest are flagged against it.
    acc_by_company_prefix: dict[tuple[str, str, str], list[tuple[dict, FieldMapping]]] = {}
    acc_by_domain_prefix: dict[tuple[str, str, str], list[tuple[dict, FieldMapping]]] = {}
    for _, row in accumulated_leads.iterrows():
        row_dict = row.to_dict()
        email = _norm(row_dict.get(acc_fm.email, ""))
        if email:
            acc_emails.add(email)
        key = _name_key(row_dict, acc_fm)
        if key != ("", ""):
            acc_by_name.setdefault(key, []).append((row_dict, acc_fm))
        company_prefix_key = _prefix3_key(row_dict, acc_fm, str(row_dict.get(acc_fm.company, "") or ""))
        if company_prefix_key is not None:
            acc_by_company_prefix.setdefault(company_prefix_key, []).append((row_dict, acc_fm))
        domain_prefix_key = _prefix3_key(row_dict, acc_fm, extract_domain(email))
        if domain_prefix_key is not None:
            acc_by_domain_prefix.setdefault(domain_prefix_key, []).append((row_dict, acc_fm))

    seen_emails: dict[str, int] = {}
    seen_by_name: dict[tuple[str, str], list[int]] = {}
    seen_by_company_prefix: dict[tuple[str, str, str], list[int]] = {}
    seen_by_domain_prefix: dict[tuple[str, str, str], list[int]] = {}

    for idx, row in new_leads.iterrows():
        row_dict = row.to_dict()
        email = _norm(row_dict.get(fm.email, ""))
        company = str(row_dict.get(fm.company, "") or "")
        domain = extract_domain(email)
        key = _name_key(row_dict, fm)
        company_prefix_key = _prefix3_key(row_dict, fm, company)
        domain_prefix_key = _prefix3_key(row_dict, fm, domain)

        if email and (email in acc_emails or email in seen_emails):
            outcome.fail[idx] = "Duplicate - exact email"
        else:
            candidates = list(acc_by_name.get(key, []))
            for other_idx in seen_by_name.get(key, []):
                candidates.append((new_leads.loc[other_idx].to_dict(), fm))

            if key != ("", "") and candidates:
                # Same first+last name as an existing lead. Company decides
                # everything from here: a different (or unknown/blank)
                # company means it's just two different people who share a
                # name, so the lead passes through untouched. Only when the
                # company also matches does the email domain decide whether
                # this is a confirmed duplicate (same domain — someone reused
                # the same person under a different email) or one that needs
                # a human look (same company, but a different email domain).
                hard_match_other = None
                soft_match_other = None
                for other, other_fm in candidates:
                    other_company = str(other.get(other_fm.company, "") or "")
                    same_company = (
                        normalize_company_name(company) != ""
                        and normalize_company_name(company) == normalize_company_name(other_company)
                    )
                    if not same_company:
                        continue
                    other_email = _norm(other.get(other_fm.email, ""))
                    if domain and domain == extract_domain(other_email):
                        hard_match_other = other
                        break
                    if soft_match_other is None:
                        soft_match_other = (other, other_fm)

                if hard_match_other is not None:
                    outcome.fail[idx] = "Duplicate - same name, company, and email domain"
                elif soft_match_other is not None:
                    other, other_fm = soft_match_other
                    other_email = str(other.get(other_fm.email, "") or "")
                    other_domain = extract_domain(_norm(other.get(other_fm.email, "")))
                    outcome.review[idx] = ReviewDetail(
                        check="Duplicate", message="Same name & company, different email domain",
                        lead_value=domain or "(blank)", candidate_value=other_domain or "(blank)",
                        candidate_context="existing lead with the same name & company"
                                          + (f" ({other_email})" if other_email else ""),
                    )
                # else: same name, but no candidate shares the company —
                # different people, let it pass.

            # Rules 5/6: a full name/email match can miss near-duplicates —
            # typos, nicknames, a maiden/married name change — that still
            # share the first 3 letters of the first name, last name, and
            # either the company or the email domain. Deliberately coarse,
            # so it only ever sends to review, never auto-fails. Skipped
            # once this lead already has a stronger verdict above.
            if idx not in outcome.fail and idx not in outcome.review:
                company_match = None
                if company_prefix_key is not None:
                    company_candidates = list(acc_by_company_prefix.get(company_prefix_key, []))
                    for other_idx in seen_by_company_prefix.get(company_prefix_key, []):
                        company_candidates.append((new_leads.loc[other_idx].to_dict(), fm))
                    if company_candidates:
                        company_match = company_candidates[0]

                domain_match = None
                if domain_prefix_key is not None:
                    domain_candidates = list(acc_by_domain_prefix.get(domain_prefix_key, []))
                    for other_idx in seen_by_domain_prefix.get(domain_prefix_key, []):
                        domain_candidates.append((new_leads.loc[other_idx].to_dict(), fm))
                    if domain_candidates:
                        domain_match = domain_candidates[0]

                if company_match is not None:
                    other, other_fm = company_match
                    other_company = str(other.get(other_fm.company, "") or "")
                    outcome.review[idx] = ReviewDetail(
                        check="Duplicate",
                        message="Name & company prefix (first 3 letters) matches another lead",
                        lead_value=f"{row_dict.get(fm.first_name, '')} {row_dict.get(fm.last_name, '')} "
                                   f"@ {company}".strip(),
                        candidate_value=f"{other.get(other_fm.first_name, '')} {other.get(other_fm.last_name, '')} "
                                        f"@ {other_company}".strip(),
                        candidate_context="existing/earlier lead with a matching first-3-letter "
                                          "name & company prefix",
                    )
                elif domain_match is not None:
                    other, other_fm = domain_match
                    other_email = str(other.get(other_fm.email, "") or "")
                    outcome.review[idx] = ReviewDetail(
                        check="Duplicate",
                        message="Name & email domain prefix (first 3 letters) matches another lead",
                        lead_value=f"{row_dict.get(fm.first_name, '')} {row_dict.get(fm.last_name, '')} "
                                   f"<{email}>".strip(),
                        candidate_value=f"{other.get(other_fm.first_name, '')} {other.get(other_fm.last_name, '')} "
                                        f"<{other_email}>".strip(),
                        candidate_context="existing/earlier lead with a matching first-3-letter "
                                          "name & domain prefix",
                    )

        if email:
            seen_emails.setdefault(email, idx)
        if key != ("", ""):
            seen_by_name.setdefault(key, []).append(idx)
        if company_prefix_key is not None:
            seen_by_company_prefix.setdefault(company_prefix_key, []).append(idx)
        if domain_prefix_key is not None:
            seen_by_domain_prefix.setdefault(domain_prefix_key, []).append(idx)

    return outcome
