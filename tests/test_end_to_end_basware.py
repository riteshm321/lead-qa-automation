import shutil

import pandas as pd
import pytest

from core.excel_io import read_sheet_as_dataframe, append_leads, backup_file
from core.models import ClientProfile, FieldMapping, DuplicateConfig, ExclusionConfig, ReferenceSource
from core.pipeline import run_pipeline

SAMPLE_DIR = "sample_data"


@pytest.fixture
def accumulated_copy(tmp_path):
    source = f"{SAMPLE_DIR}/Basware APAC – Accumulated Report.xlsx"
    dest = tmp_path / "Basware APAC – Accumulated Report.xlsx"
    shutil.copy2(source, dest)
    return str(dest)


def test_master_output_leads_are_flagged_as_duplicates_against_accumulated(accumulated_copy):
    fm = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                       company="company", cid="CID")
    exclusion_path = f"{SAMPLE_DIR}/Basware -Exclusion List.xlsx"
    profile = ClientProfile(
        name="Basware",
        accumulated_report_path=accumulated_copy,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
        exclusion=ExclusionConfig(enabled=True, sources=[
            ReferenceSource(name="Basware Exclusion", file_path=exclusion_path, sheet_name="Exclusion"),
        ]),
    )

    new_leads = pd.read_excel(f"{SAMPLE_DIR}/Master_Output.xlsx")
    accumulated_leads = read_sheet_as_dataframe(accumulated_copy, "Accumulated")
    exclusion_df = read_sheet_as_dataframe(exclusion_path, "Exclusion")

    result = run_pipeline(
        new_leads, profile, accumulated_leads,
        reference_data={"exclusion_sources": {"Basware Exclusion": exclusion_df}},
        alias_groups=[],
    )

    # Master_Output.xlsx leads are already in Accumulated (per user's note) — expect most/all flagged.
    assert len(result.refund_reasons) > 0
    assert all("Duplicate" in reason or "Exclusion" in reason for reason in result.refund_reasons.values())


def test_finalize_writes_refund_rows_with_reason(accumulated_copy):
    fm = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                       company="company", cid="CID")
    profile = ClientProfile(
        name="Basware",
        accumulated_report_path=accumulated_copy,
        field_mapping=fm,
        duplicate=DuplicateConfig(enabled=True),
    )

    new_leads = pd.read_excel(f"{SAMPLE_DIR}/Master_Output.xlsx")
    accumulated_leads = read_sheet_as_dataframe(accumulated_copy, "Accumulated")

    result = run_pipeline(new_leads, profile, accumulated_leads, reference_data={}, alias_groups=[])
    assert result.refund_reasons

    backup_path = backup_file(accumulated_copy)
    refund_indices = list(result.refund_reasons.keys())
    append_leads(accumulated_copy, "Refund", new_leads.loc[refund_indices], fm,
                 run_date="2026-08-08", reasons=result.refund_reasons)

    refund_after = read_sheet_as_dataframe(accumulated_copy, "Refund")
    assert len(refund_after) >= len(refund_indices)
    assert "Refund Reason" in refund_after.columns
    assert backup_path != accumulated_copy
