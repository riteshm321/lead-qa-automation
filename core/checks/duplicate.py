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
