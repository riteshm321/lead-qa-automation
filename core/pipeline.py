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
