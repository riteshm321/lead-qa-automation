import datetime

from core.upload_batches import (
    BATCH_KEY, batch_display_time, new_batch_id, partition_by_latest_batch, split_rows_and_batches, tag_rows,
)


def test_new_batch_ids_sort_in_upload_order():
    first = new_batch_id(datetime.datetime(2026, 10, 1, 9, 5, 0, 1))
    second = new_batch_id(datetime.datetime(2026, 10, 1, 9, 5, 0, 2))
    third = new_batch_id(datetime.datetime(2026, 10, 2, 8, 0, 0))
    assert first < second < third


def test_batch_display_time_is_readable_and_tolerates_garbage():
    assert batch_display_time(new_batch_id(datetime.datetime(2026, 10, 1, 14, 30, 5))) == "01 Oct 2026 14:30"
    assert batch_display_time("not-a-batch") == "not-a-batch"


def test_tag_rows_and_split_round_trip_without_mutating_input():
    rows = {"1": {"Email": "a@x.com"}}
    tagged = tag_rows(rows, "B1")
    assert tagged == {"1": {"Email": "a@x.com", BATCH_KEY: "B1"}}
    assert rows == {"1": {"Email": "a@x.com"}}

    clean, batches = split_rows_and_batches({**tagged, "2": {"Email": "legacy@x.com"}})
    assert clean == {"1": {"Email": "a@x.com"}, "2": {"Email": "legacy@x.com"}}
    assert batches == {"1": "B1", "2": ""}


def test_tag_rows_with_blank_batch_leaves_rows_untagged():
    assert tag_rows({"1": {"Email": "a@x.com"}}, "") == {"1": {"Email": "a@x.com"}}


def test_partition_picks_only_the_latest_batch_and_treats_untagged_as_earlier():
    latest, latest_ids, earlier_ids = partition_by_latest_batch(
        {"1": "20261001T090000000000", "2": "20261002T090000000000", "3": "", "4": "20261002T090000000000"})
    assert latest == "20261002T090000000000"
    assert latest_ids == ["2", "4"]
    assert earlier_ids == ["1", "3"]


def test_partition_with_only_untagged_leads_has_no_latest_batch():
    assert partition_by_latest_batch({"1": "", "2": ""}) == ("", [], ["1", "2"])
    assert partition_by_latest_batch({}) == ("", [], [])
