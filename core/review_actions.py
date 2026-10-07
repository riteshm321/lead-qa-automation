"""Moves Needs Review leads to valid or refund -- shared by Run Check's
bulk select-and-act buttons and its per-row Action column so the two can
never disagree. Page-level review resolution only; no check logic lives
here (see core/pipeline.py / core/checks/)."""
from collections.abc import Iterable, Sequence

from core.pipeline import PipelineResult

REVIEW_ACTION_APPROVE = "Approve as valid"
REVIEW_ACTION_REFUND = "Mark as refund"
REVIEW_ACTIONS = (REVIEW_ACTION_APPROVE, REVIEW_ACTION_REFUND)


def approve_review_leads(result: PipelineResult, indices: Iterable[int]) -> list[int]:
    """Moves the given Needs Review leads to valid, except any blank in a
    mandatory Lead Template column (result.mandatory_blank_indices) - those
    stay in Needs Review and are returned, so a mandatory column is never
    written blank."""
    locked = getattr(result, "mandatory_blank_indices", set())
    indices = list(indices)
    blocked = [idx for idx in indices if idx in locked]
    for idx in indices:
        if idx in locked:
            continue
        result.valid_indices.append(idx)
        del result.review_reasons[idx]
    return blocked


def refund_review_leads(result: PipelineResult, indices: Iterable[int]) -> None:
    for idx in indices:
        result.refund_reasons[idx] = "; ".join(str(d) for d in result.review_reasons[idx])
        del result.review_reasons[idx]


def split_row_actions(indices: Sequence[int], actions: Iterable[object]) -> tuple[list[int], list[int]]:
    """(approve_indices, refund_indices) from the Needs Review table's
    edited Action cells, paired positionally with `indices`. A blank cell
    comes back from st.data_editor as None/NaN/pd.NA -- anything that isn't
    exactly one of REVIEW_ACTIONS means "no decision for this row"."""
    approve: list[int] = []
    refund: list[int] = []
    for idx, action in zip(indices, actions):
        if not isinstance(action, str):
            continue
        if action == REVIEW_ACTION_APPROVE:
            approve.append(idx)
        elif action == REVIEW_ACTION_REFUND:
            refund.append(idx)
    return approve, refund
