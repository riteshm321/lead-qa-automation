import math

import pandas as pd

from core.check_result import ReviewDetail
from core.pipeline import PipelineResult
from core.review_actions import (
    REVIEW_ACTION_APPROVE, REVIEW_ACTION_REFUND, REVIEW_ACTIONS,
    approve_review_leads, refund_review_leads, split_row_actions,
)


def _result():
    return PipelineResult(valid_indices=[5], refund_reasons={}, review_reasons={
        0: [ReviewDetail(check="Duplicate", message="reason a")],
        1: [ReviewDetail(check="Duplicate", message="reason b"), ReviewDetail(check="TAL", message="fuzzy")],
    })


def test_action_labels():
    assert REVIEW_ACTIONS == ("Approve as valid", "Mark as refund")


def test_approve_review_leads_moves_to_valid_in_order():
    result = _result()
    approve_review_leads(result, [1, 0])
    assert result.valid_indices == [5, 1, 0]
    assert result.review_reasons == {}
    assert result.refund_reasons == {}


def test_refund_review_leads_joins_every_detail_as_the_reason():
    result = _result()
    refund_review_leads(result, [1])
    assert result.refund_reasons == {1: "Duplicate - reason b; TAL - fuzzy"}
    assert list(result.review_reasons) == [0]
    assert result.valid_indices == [5]


def test_empty_indices_are_a_no_op():
    result = _result()
    approve_review_leads(result, [])
    refund_review_leads(result, [])
    assert list(result.review_reasons) == [0, 1]


def test_split_row_actions_ignores_blank_and_unknown_cells():
    approve, refund = split_row_actions(
        [10, 11, 12, 13, 14, 15],
        [REVIEW_ACTION_APPROVE, None, REVIEW_ACTION_REFUND, pd.NA, math.nan, "something else"],
    )
    assert approve == [10]
    assert refund == [12]


def test_split_row_actions_accepts_a_pandas_string_series():
    actions = pd.Series([REVIEW_ACTION_REFUND, None], dtype="string")
    assert split_row_actions([3, 4], actions) == ([], [3])


def test_split_row_actions_with_no_action_column_means_no_decisions():
    assert split_row_actions([0, 1], []) == ([], [])
