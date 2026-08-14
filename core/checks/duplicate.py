import pandas as pd

from core.check_result import CheckOutcome, ReviewDetail
from core.matching import extract_domain, normalize_company_name
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
                # Same first+last name as an existing lead. Company decides
                # everything from here: a different (or unknown/blank)
                # company means it's just two different people who share a
                # name, so the lead passes through untouched. Only when the
                # company also matches does the email domain decide whether
                # this is a confirmed duplicate (same domain — someone reused
                # the same person under a different email) or one that needs
                # a human look (same company, but a different email domain).
                domain = extract_domain(email)
                hard_match_other = None
                soft_match_other = None
                for other in candidates:
                    other_company = str(other.get(fm.company, "") or "")
                    same_company = (
                        normalize_company_name(company) != ""
                        and normalize_company_name(company) == normalize_company_name(other_company)
                    )
                    if not same_company:
                        continue
                    other_email = _norm(other.get(fm.email, ""))
                    if domain and domain == extract_domain(other_email):
                        hard_match_other = other
                        break
                    if soft_match_other is None:
                        soft_match_other = other

                if hard_match_other is not None:
                    outcome.fail[idx] = "Duplicate - same name, company, and email domain"
                elif soft_match_other is not None:
                    other_email = str(soft_match_other.get(fm.email, "") or "")
                    other_domain = extract_domain(_norm(soft_match_other.get(fm.email, "")))
                    outcome.review[idx] = ReviewDetail(
                        check="Duplicate", message="Same name & company, different email domain",
                        lead_value=domain or "(blank)", candidate_value=other_domain or "(blank)",
                        candidate_context="existing lead with the same name & company"
                                          + (f" ({other_email})" if other_email else ""),
                    )
                # else: same name, but no candidate shares the company —
                # different people, let it pass.

        if email:
            seen_emails.setdefault(email, idx)
        if key != ("", ""):
            seen_by_name.setdefault(key, []).append(idx)

    return outcome
