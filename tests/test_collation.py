import io

import pandas as pd

from core.collation import collate_uploaded_files, extract_cid_from_filename, flag_duplicate_emails


def _upload(name: str, content: bytes) -> io.BytesIO:
    f = io.BytesIO(content)
    f.name = name
    return f


def test_extract_cid_from_filename_takes_the_last_5_or_6_digit_run():
    assert extract_cid_from_filename("Leads_Export_118741.csv") == "118741"
    assert extract_cid_from_filename("2026-08-17_Campaign_118741_Final.xlsx") == "118741"
    assert extract_cid_from_filename("no_cid_here.csv") is None


def test_extract_cid_from_filename_prefers_the_last_match():
    # A date-like number earlier in the name shouldn't be mistaken for the
    # CID when a real CID also appears later.
    assert extract_cid_from_filename("202608_leads_118741.csv") == "118741"


def test_flag_duplicate_emails_marks_rows_sharing_an_email_across_files():
    df = pd.DataFrame([
        {"Email": "a@x.com"}, {"Email": "a@x.com"}, {"Email": "b@x.com"},
    ])
    count, col = flag_duplicate_emails(df)
    assert count == 2
    assert list(df[col]) == [True, True, False]


def test_flag_duplicate_emails_none_when_no_email_column():
    df = pd.DataFrame([{"Name": "A"}])
    assert flag_duplicate_emails(df) == (None, None)


def test_flag_duplicate_emails_uses_a_different_column_name_if_taken():
    df = pd.DataFrame([{"Email": "a@x.com", "duplicate_email": "existing data"}])
    _, col = flag_duplicate_emails(df)
    assert col == "Duplicate Email Flag"


def test_collate_uploaded_files_stacks_and_tags_cid_from_filename():
    file1 = _upload("Campaign_118741.csv", b"Email,First\na@x.com,A\n")
    file2 = _upload("Campaign_118743.csv", b"Email,First\nb@x.com,B\n")

    master_df, results, skipped, notes = collate_uploaded_files([file1, file2])

    assert list(master_df["CID"]) == ["118741", "118743"]
    assert set(master_df["Email"]) == {"a@x.com", "b@x.com"}
    assert results == [("Campaign_118741.csv", "118741", 1), ("Campaign_118743.csv", "118743", 1)]
    assert skipped == []
    assert notes == []


def test_collate_uploaded_files_normalizes_headers_across_files():
    # "Email" in one file and "email address" in another must line up
    # under one column, keeping the FIRST file's own header text.
    file1 = _upload("a_118741.csv", b"Email,First Name\na@x.com,A\n")
    file2 = _upload("b_118743.csv", b"email,firstname\nb@x.com,B\n")

    master_df, *_ = collate_uploaded_files([file1, file2])

    assert list(master_df.columns) == ["CID", "Email", "First Name", "duplicate_email"]
    assert set(master_df["Email"]) == {"a@x.com", "b@x.com"}


def test_collate_uploaded_files_no_cid_for_a_filename_without_one():
    file1 = _upload("no_cid_here.csv", b"Email\na@x.com\n")

    master_df, results, _, _ = collate_uploaded_files([file1])

    assert "CID" not in master_df.columns
    assert results == [("no_cid_here.csv", None, 1)]


def test_collate_uploaded_files_uses_from_filename_suffix_when_cid_column_already_exists():
    file1 = _upload("real_118741.csv", b"CID,Email\n999,a@x.com\n")

    master_df, results, _, _ = collate_uploaded_files([file1])

    assert master_df.loc[0, "CID"] == 999  # the leadfile's own CID column, untouched
    assert master_df.loc[0, "CID (from filename)"] == "118741"
    assert results == [("real_118741.csv", "118741", 1)]


def test_collate_uploaded_files_flags_duplicate_emails_across_files():
    file1 = _upload("a_118741.csv", b"Email\na@x.com\n")
    file2 = _upload("b_118743.csv", b"Email\na@x.com\n")

    master_df, *_ = collate_uploaded_files([file1, file2])

    assert list(master_df["duplicate_email"]) == [True, True]


def test_collate_uploaded_files_skips_unreadable_files_but_keeps_the_rest():
    good = _upload("good_118741.csv", b"Email\na@x.com\n")
    bad = _upload("bad_118743.csv", b"not,valid\xff\xfebytes")
    bad.name = "bad_118743.xlsx"  # forces the openpyxl path, which will reject this content

    master_df, results, skipped, _ = collate_uploaded_files([good, bad])

    assert len(master_df) == 1
    assert [r[0] for r in results] == ["good_118741.csv"]
    assert len(skipped) == 1
    assert skipped[0][0] == "bad_118743.xlsx"


def test_collate_uploaded_files_reports_column_differences():
    file1 = _upload("a_118741.csv", b"Email,First\na@x.com,A\n")
    file2 = _upload("b_118743.csv", b"Email,Phone\nb@x.com,123\n")

    _, _, _, notes = collate_uploaded_files([file1, file2])

    assert len(notes) == 1
    filename, new_cols, missing_cols = notes[0]
    assert filename == "b_118743.csv"
    assert new_cols == {"Phone"}
    assert missing_cols == {"First"}


def test_collate_uploaded_files_empty_list_returns_empty_dataframe():
    master_df, results, skipped, notes = collate_uploaded_files([])
    assert master_df.empty
    assert results == []
    assert skipped == []
    assert notes == []
