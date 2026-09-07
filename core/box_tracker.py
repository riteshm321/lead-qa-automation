"""Automation for IBM APAC's Box-hosted lead-approval tracker workbook.

This app has no Box API access (see docs/superpowers/plans/
2026-09-07-ibm-apac-box-tracker-automation.md for why), so every function
here reads from or writes to a LOCAL MIRROR workbook that the user
maintains with the same tab/column shape as the real Box file, copying
ranges between the two by hand. Nothing in this module ever talks to Box.
"""
import datetime

import openpyxl
import pandas as pd

_PACING_SUMMARY_LABEL_ROW_OFFSET = {"Pending": 1, "Delivered": 2, "Diff": 3}


def current_week_label(today: datetime.date) -> str:
    """The Pacing tab's week columns are labeled "Week of {N}", where N is
    the day-of-month of that week's Monday. Resolves which label
    corresponds to "this week" for a given date.
    """
    monday = today - datetime.timedelta(days=today.weekday())
    return f"Week of {monday.day}"


def read_pacing_diffs(mirror_path: str, pacing_tab: str = "Pacing") -> dict[str, int]:
    """Reads the Pacing tab's Pending/Delivered/Diff summary block into
    {campaign_name: diff}, for however many campaign columns currently
    exist there -- this must stay dynamic (not a hardcoded campaign list),
    since the user adds new campaign columns to this block as new
    campaigns go live, and picking must pick those up automatically.

    Locates the block by searching column A for a "Diff" label rather
    than hardcoding a fixed row, since the row it lands on can drift as
    more campaign rows get added elsewhere in the sheet above it.
    """
    wb = openpyxl.load_workbook(mirror_path, read_only=True, data_only=True)
    try:
        ws = wb[pacing_tab]
        diff_row = None
        for row in ws.iter_rows(min_row=1, max_col=1):
            cell = row[0]
            if str(cell.value or "").strip().lower() == "diff":
                diff_row = cell.row
                break
        if diff_row is None:
            return {}
        header_row = diff_row - _PACING_SUMMARY_LABEL_ROW_OFFSET["Diff"]

        diffs: dict[str, int] = {}
        col = 2  # column B -- column A holds the row labels (Pending/Delivered/Diff)
        while True:
            campaign = ws.cell(row=header_row, column=col).value
            if not campaign:
                break
            diff_value = ws.cell(row=diff_row, column=col).value
            diffs[str(campaign).strip()] = int(diff_value) if diff_value is not None else 0
            col += 1
        return diffs
    finally:
        wb.close()


def sent_for_approval_label(today: datetime.date) -> str:
    return f"Sent for Approval - {today.strftime('%d-%b')}"


def pick_leads_for_approval(
    accumulated_df: pd.DataFrame, cid_column: str, status_column: str,
    cid_campaign_map: dict[str, str], diffs: dict[str, int], buffer: int = 5,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Picks which blank-Status Accumulated leads go to the client for
    approval this cycle: for every CID with a known campaign mapping AND
    a Diff value for that campaign, picks (diff + buffer) leads with that
    CID and a blank status_column value.

    A CID with no entry in cid_campaign_map, or whose campaign has no
    entry in diffs (that campaign column doesn't exist in the Pacing
    summary block yet), is skipped entirely -- there's no target count to
    pick towards, so picking arbitrarily would be a guess, not a decision.

    Returns (picked_df, shortfall) where shortfall is {cid: amount_short}
    for every CID that had fewer than its target available -- picking
    still proceeds with whatever was available, this is purely a report
    for the caller to surface, never a reason to stop.
    """
    picked_frames = []
    shortfall: dict[str, int] = {}
    is_blank_status = accumulated_df[status_column].fillna("").astype(str).str.strip() == ""

    for cid, campaign in cid_campaign_map.items():
        if campaign not in diffs:
            continue
        target = diffs[campaign] + buffer
        candidates = accumulated_df[is_blank_status & (accumulated_df[cid_column].astype(str) == cid)]
        picked = candidates.head(target)
        if len(picked) < target:
            shortfall[cid] = target - len(picked)
        if not picked.empty:
            picked_frames.append(picked)

    if not picked_frames:
        return accumulated_df.iloc[0:0], shortfall
    return pd.concat(picked_frames), shortfall


def append_mirror_rows(mirror_path: str, tab_name: str, rows: list[dict], header_row: int = 1) -> None:
    """Appends rows to a mirror workbook tab, matching each dict's keys to
    that tab's header cells by exact text (case/whitespace-insensitive) --
    unlike core/excel_io.py's append_leads, there's no FieldMapping role
    model here, just plain header-name matching, since these are the
    tool's own mirror files with fixed, known business-column headers
    (Company Name, Market, Segment, ...), not a generic leadfile.
    A dict key with no matching header is silently ignored; a header with
    no matching key is left blank for that row.
    """
    wb = openpyxl.load_workbook(mirror_path)
    try:
        ws = wb[tab_name]
        headers = [cell.value for cell in next(ws.iter_rows(min_row=header_row, max_row=header_row))]
        header_to_col = {
            str(h).strip().lower(): i + 1 for i, h in enumerate(headers) if h is not None
        }
        next_row = ws.max_row + 1
        for offset, row_dict in enumerate(rows):
            excel_row = next_row + offset
            for key, value in row_dict.items():
                col = header_to_col.get(str(key).strip().lower())
                if col is not None:
                    ws.cell(row=excel_row, column=col, value=value)
        wb.save(mirror_path)
    finally:
        wb.close()


def set_pacing_delivered(
    mirror_path: str, campaign: str, value: int,
    pacing_tab: str = "Pacing", week_label: str | None = None,
) -> None:
    """Sets (never adds to) the Delivered ("D") cell for `campaign`'s row,
    under `week_label`'s week block (defaults to the current week -- see
    current_week_label). The main Pacing grid pairs a "P" and "D"
    sub-column under each "Week of N" header; this locates the "D"
    sub-column by scanning the sub-header row for "D" starting at the
    "Week of N" column, then finds `campaign`'s row by scanning the
    Campaign column.
    """
    if week_label is None:
        week_label = current_week_label(datetime.date.today())

    wb = openpyxl.load_workbook(mirror_path)
    try:
        ws = wb[pacing_tab]
        header_row_idx = 1
        subheader_row_idx = 2

        week_col = next(
            (cell.column for cell in ws[header_row_idx] if str(cell.value or "").strip() == week_label),
            None,
        )
        if week_col is None:
            raise ValueError(f"No \"{week_label}\" column found in {pacing_tab!r}")

        d_col = None
        for col in range(week_col, ws.max_column + 1):
            sub = ws.cell(row=subheader_row_idx, column=col).value
            if str(sub or "").strip().upper() == "D":
                d_col = col
                break
            if str(sub or "").strip() and col > week_col:
                break  # ran into the next week block without finding "D"
        if d_col is None:
            raise ValueError(f"No \"D\" sub-column found under \"{week_label}\" in {pacing_tab!r}")

        campaign_col = next(
            (cell.column for cell in ws[header_row_idx] if str(cell.value or "").strip().lower() == "campaign"),
            None,
        )
        if campaign_col is None:
            raise ValueError(f"No \"Campaign\" column found in {pacing_tab!r}")

        for row in ws.iter_rows(min_row=subheader_row_idx + 1):
            if str(row[campaign_col - 1].value or "").strip() == campaign:
                ws.cell(row=row[0].row, column=d_col, value=value)
                break
        else:
            raise ValueError(f"No row for campaign {campaign!r} found in {pacing_tab!r}")

        wb.save(mirror_path)
    finally:
        wb.close()
