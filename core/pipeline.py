from dataclasses import dataclass, field
from typing import Callable

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
    on_progress: Callable[[str], None] | None = None,
) -> PipelineResult:
    fm = profile.field_mapping
    fail: dict[int, list[str]] = {}
    review: dict[int, list[str]] = {}

    def merge(outcome: CheckOutcome) -> None:
        for idx, reason in outcome.fail.items():
            fail.setdefault(idx, []).append(reason)
        for idx, reason in outcome.review.items():
            review.setdefault(idx, []).append(reason)

    def report(label: str) -> None:
        if on_progress is not None:
            on_progress(label)

    if profile.duplicate.enabled:
        report("Checking Duplicates")
        merge(duplicate.check_duplicates(new_leads, accumulated_leads, fm, profile.accumulated_field_mapping))

    if profile.leadcap.enabled:
        report("Checking Leadcap")
        merge(leadcap.check_leadcap(new_leads, fm, profile.leadcap, reference_data.get("purchased_reports", {})))

    if profile.exclusion.enabled:
        report("Checking Exclusion List")
        merge(exclusion.check_exclusion(new_leads, fm, profile.exclusion,
                                         reference_data.get("exclusion_sources", {}), alias_groups))

    if profile.tal.enabled:
        report("Checking TAL")
        merge(tal.check_tal(new_leads, fm, profile.tal,
                             reference_data.get("tal_sources", {}), alias_groups))

    if profile.suppression.enabled:
        report("Checking Suppression List")
        merge(suppression.check_suppression(new_leads, fm, profile.suppression,
                                             reference_data.get("suppression_sources", {}), alias_groups))

    if profile.dedupe_list.enabled:
        report("Checking Dedupe List")
        merge(dedupe_list.check_dedupe_list(new_leads, fm, profile.dedupe_list,
                                             reference_data.get("dedupe_sources", {})))

    refund_reasons = {idx: "; ".join(reasons) for idx, reasons in fail.items()}
    review_reasons = {idx: reasons for idx, reasons in review.items() if idx not in fail}
    valid_indices = [idx for idx in new_leads.index if idx not in fail and idx not in review_reasons]

    return PipelineResult(valid_indices=valid_indices, refund_reasons=refund_reasons, review_reasons=review_reasons)


def apply_refund_overrides(
    result: PipelineResult, approved_refund_indices: list[int]
) -> tuple[list[int], dict[int, str]]:
    """Split auto-flagged refund leads by manual override.

    A refund lead the user ticks "approve as valid" for joins the same
    valid bucket as everything the tool already recognized as valid (so it
    gets appended to the Accumulated Report and Lead Template); anything
    left unticked stays refund-only, unchanged from the tool's original
    call. Returns (final_valid_indices, final_refund_reasons).
    """
    final_valid_indices = list(result.valid_indices) + list(approved_refund_indices)
    final_refund_reasons = {
        idx: reason for idx, reason in result.refund_reasons.items()
        if idx not in approved_refund_indices
    }
    return final_valid_indices, final_refund_reasons
