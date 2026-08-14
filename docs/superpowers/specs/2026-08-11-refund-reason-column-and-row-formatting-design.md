# Refund Reason Column & Row Formatting Propagation — Design Spec

Date: 2026-08-11
Status: Approved by user, implementing directly (small, well-scoped change)

## Purpose

Two related fixes to `append_leads` in `core/excel_io.py`, used when writing valid leads to the Accumulated tab and refunded leads to the Refund tab:

1. Recognize the client's real refund-reason column name ("Refund Reason"), not just "Reason".
2. Preserve the Accumulated Report's existing cell formatting when appending new lead rows, instead of leaving newly written cells unstyled.

## 1. Refund Reason Column

`append_leads` currently only recognizes a header spelled exactly "Reason" (case-insensitive) as the reason column, and auto-adds a column named "Reason" if none is found. Real client Accumulated Reports use "Refund Reason" as the standing column name.

Change: recognize either "reason" or "refund reason" (case-insensitive, trimmed) as the reason column. If reasons are being written (i.e. `reasons` dict is non-empty) and neither is present, auto-add a column named **"Refund Reason"** (not "Reason").

## 2. Row Formatting Propagation

Today, `append_leads` writes plain values into cells via `ws.cell(row, col, value=...)` with no style applied — appended rows come out unformatted regardless of what the rest of the sheet looks like.

New behavior, determined once per `append_leads` call before writing any rows:

- **Sheet has no existing lead rows yet** (rows 2..max_row contain no non-empty cell in any mapped column — i.e. this is the first batch for a new campaign): write the new leads starting at row 2, and apply **row 2's own existing per-column cell styles** (font, fill, border, alignment, number format) to each cell as it's written. This preserves whatever blank formatted template row the client's Accumulated Report ships with.
- **Sheet already has lead rows**: write new leads starting at the next empty row after the last existing row, and apply the **last existing lead row's per-column cell styles** to each new row's cells.
- If there is no row 2 at all (`ws.max_row < 2`, truly nothing below the header), fall back to no explicit styling (current behavior) — there is nothing to copy from.

Style is captured per column (by column index) from the template row once, then applied to every cell in every newly written row for that column — a plain copy of `font`, `fill`, `border`, `alignment`, and `number_format` (openpyxl style objects are safe to share by reference across cells).

This applies identically to both the Accumulated tab (valid leads) and the Refund tab (refunded leads) — both go through the same `append_leads` function.

## Out of Scope

- Fuzzy company-name matching for Exclusion/TAL/Suppression — already implemented via `company_names_match()` in `core/matching.py` (rapidfuzz-based, HIGH/LOW thresholds, sends gray-zone matches to Needs Review). No changes requested here.
- The "Lead QA" vs "Lead QA & Upload" mode split and lead templates — separate, larger feature to be spec'd on its own.

## Testing

- `core/excel_io.py` tests: reason column recognized when named "Refund Reason"; new "Refund Reason" column auto-added (not "Reason") when neither exists and reasons are present.
- Formatting tests: appending to an empty-of-leads sheet copies row 2's style to written rows; appending to a sheet with existing leads copies the last existing row's style to new rows; a sheet with no row 2 at all still appends without error (no styling applied).
