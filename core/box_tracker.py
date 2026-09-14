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


def uploaded_to_approval_sheet_label(today: datetime.date) -> str:
    # Marks a lead the user added straight to the real Approval Sheet
    # themselves, bypassing the tool's automated Pacing-driven picking --
    # step 2 treats this the same as "Sent for Approval".
    return f"Uploaded to Approval Sheet - {today.strftime('%d-%b')}"


def cleared_for_upload_label(today: datetime.date) -> str:
    return f"Cleared for Upload - {today.strftime('%d-%b')}"


def uploaded_accepted_label(today: datetime.date) -> str:
    return f"Accepted - Uploaded - {today.strftime('%d-%b')}"


def uploaded_rejected_label(today: datetime.date) -> str:
    return f"Rejected - Refunded - {today.strftime('%d-%b')}"


def pick_leads_for_approval(
    accumulated_df: pd.DataFrame, cid_column: str, status_column: str,
    cid_campaign_map: dict[str, str], diffs: dict[str, int], buffer: int = 5,
    uncapped_campaigns: set[str] = frozenset(),
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Picks which blank-Status Accumulated leads go to the client for
    approval this cycle: for every CID with a known campaign mapping AND
    a Diff value for that campaign, picks (diff + buffer) leads with that
    CID and a blank status_column value.

    A CID with no entry in cid_campaign_map, or whose campaign has no
    entry in diffs (that campaign column doesn't exist in the Pacing
    summary block yet), is skipped entirely -- there's no target count to
    pick towards, so picking arbitrarily would be a guess, not a decision.

    Two situations take EVERY available blank-Status lead for a CID
    instead of a capped (diff + buffer) amount, and never appear in
    shortfall since there's no target to fall short of: uncapped_campaigns
    (a segment that's only just gone live with no established Pacing
    history yet -- see BoxTrackerConfig.pacing_skipped_campaigns), and a
    Diff of zero or negative (Delivered has already met or exceeded
    Pending -- there's nothing left to pace towards this cycle, so every
    available lead goes out rather than none).

    Returns (picked_df, shortfall) where shortfall is {cid: amount_short}
    for every capped CID that had fewer than its target available --
    picking still proceeds with whatever was available, this is purely a
    report for the caller to surface, never a reason to stop.
    """
    picked_frames = []
    shortfall: dict[str, int] = {}
    is_blank_status = accumulated_df[status_column].fillna("").astype(str).str.strip() == ""

    for cid, campaign in cid_campaign_map.items():
        candidates = accumulated_df[is_blank_status & (accumulated_df[cid_column].astype(str) == cid)]
        if campaign in uncapped_campaigns:
            if not candidates.empty:
                picked_frames.append(candidates)
            continue
        if campaign not in diffs:
            continue
        if diffs[campaign] <= 0:
            if not candidates.empty:
                picked_frames.append(candidates)
            continue
        target = diffs[campaign] + buffer
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


_PACING_COUNTRY_SUFFIXES = ("IN", "AU")
_STATIC_HEADER_SCAN_ROWS = 5  # how many top rows to search for "Campaign"/"Country"/the week label


def strip_country_suffix(campaign: str) -> str:
    """Some campaigns (e.g. "wxO (AI Pod)") reuse the same Campaign text
    for both the IN and AU Pacing rows, so cid_campaign_map disambiguates
    them with a trailing " IN"/" AU" (see set_pacing_delivered). The real
    Box file's Approval Sheet doesn't want that suffix in its
    Persona/Industry column -- country there is its own separate Market
    column -- so this strips it back off for that purpose. A campaign
    with no such suffix (e.g. "Bob") passes through unchanged.
    """
    for suffix in _PACING_COUNTRY_SUFFIXES:
        if campaign.strip().upper().endswith(f" {suffix}"):
            return campaign.strip()[: -(len(suffix) + 1)].strip()
    return campaign


def _find_header_cell(ws, label: str, max_row: int = _STATIC_HEADER_SCAN_ROWS):
    """Returns (row, col) of the first cell in the top `max_row` rows whose
    text matches `label` exactly (case-insensitive). The real Box file's
    static columns sit in row 1, but the week-block labels can land a row
    lower depending on whether a month header sits above them -- searching
    a small window instead of assuming a fixed row tolerates that drift.
    """
    for row in ws.iter_rows(min_row=1, max_row=max_row):
        for cell in row:
            if str(cell.value or "").strip().lower() == label.strip().lower():
                return cell.row, cell.column
    return None, None


def set_pacing_delivered(
    mirror_path: str, campaign: str, value: int,
    pacing_tab: str = "Pacing", week_label: str | None = None,
) -> None:
    """Sets (never adds to) the Delivered ("D") cell for `campaign`'s row,
    under `week_label`'s week block (defaults to the current week -- see
    current_week_label). The main Pacing grid pairs a "P" and "D"
    sub-column under each "Week of N" header; this locates the "D"
    sub-column by scanning the row directly below the week label for "D"
    starting at the "Week of N" column, then finds `campaign`'s row by
    scanning the Campaign column.

    Some campaigns (e.g. "wxO (AI Pod)") reuse the same Campaign text for
    both the IN and AU rows, distinguished only by a Country column. To
    address one of those rows unambiguously, pass `campaign` with a
    trailing " IN"/" AU" (e.g. "wxO (AI Pod) AU") -- if a Country column
    exists, the suffix is matched against it in addition to the base
    campaign text; otherwise it falls back to matching the full string
    as-is against the Campaign column.
    """
    if week_label is None:
        week_label = current_week_label(datetime.date.today())

    wb = openpyxl.load_workbook(mirror_path)
    try:
        ws = wb[pacing_tab]

        week_row, week_col = _find_header_cell(ws, week_label)
        if week_col is None:
            raise ValueError(f"No \"{week_label}\" column found in {pacing_tab!r}")
        subheader_row_idx = week_row + 1

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

        _, campaign_col = _find_header_cell(ws, "Campaign")
        if campaign_col is None:
            raise ValueError(f"No \"Campaign\" column found in {pacing_tab!r}")

        _, country_col = _find_header_cell(ws, "Country")
        match_campaign, match_country = campaign, None
        if country_col is not None:
            stripped = strip_country_suffix(campaign)
            if stripped != campaign:
                match_campaign = stripped
                match_country = campaign.strip().upper().rsplit(" ", 1)[-1]

        for row in ws.iter_rows(min_row=subheader_row_idx + 1):
            if str(row[campaign_col - 1].value or "").strip() != match_campaign:
                continue
            if match_country is not None:
                if str(row[country_col - 1].value or "").strip().upper() != match_country:
                    continue
            ws.cell(row=row[0].row, column=d_col, value=value)
            break
        else:
            raise ValueError(f"No row for campaign {campaign!r} found in {pacing_tab!r}")

        wb.save(mirror_path)
    finally:
        wb.close()


# Newly live segments' fixed Project Code, same pattern as
# _MICRO_AUDIENCE_BY_CID. Every CID's AMAL ID (including these) comes
# straight from its own leadfile column -- see parse_amal_id.
_PROJECT_CODE_OVERRIDE_BY_CID = {
    "120129": "CXOAP",  # AU CXO
    "120130": "CXOAP",  # IN CXO
    "120131": "SNCAP",  # IN DigiSov
}

# Response Details' Campaign Type is a fixed tactic abbreviation per
# campaign (matches the Pacing tab's own Tactic column: "2 Touch +
# TeleVerified" -> "2T", "1 Touch + TeleVerified" -> "1T"). CIDs not
# listed here (segments not live yet) get a blank.
_CAMPAIGN_TYPE_BY_CID = {
    "118741": "2T",  # Bob
    "118743": "2T",  # IN WXO
    "118745": "2T",  # AU WXO
    "120129": "1T",  # AU CXO
    "120130": "1T",  # IN CXO
    "120131": "1T",  # IN DigiSov
}


def campaign_type_for_cid(cid: str) -> str:
    return _CAMPAIGN_TYPE_BY_CID.get(cid, "")


def parse_amal_id(raw: str | None) -> str:
    """The leadfile's AMAL ID column sometimes carries two comma-separated
    values; the business rule is to take the later one. A single value
    (or a blank) passes through unchanged.
    """
    if not raw:
        return ""
    parts = str(raw).split(",")
    return parts[-1].strip()


def project_code_for_cid(cid: str, leadfile_value: str) -> str:
    """The Approval Sheet's Project Code is normally the leadfile's own
    Project Code/Tactic column value, passed straight through -- except
    for the CIDs in _PROJECT_CODE_OVERRIDE_BY_CID, which always get the
    fixed value regardless of what (if anything) the leadfile carries.
    """
    return _PROJECT_CODE_OVERRIDE_BY_CID.get(cid, leadfile_value)




# Fixed per-CID business rule for IBM APAC's Lead Template "micro_audience"
# column -- not derived from the leadfile at all for these CIDs, same
# pattern as Dell's AGREED_CONTACTED_BY_CID in core/complex_account.py.
_MICRO_AUDIENCE_BY_CID = {
    "118741": "Platform_SWE",  # Bob
    "120129": "All",           # AU CXO
    "118743": "AI Leaders",    # IN WXO
    "118745": "AI Leaders",    # AU WXO
    "120130": "All_CXO",       # IN CXO
}
# These CIDs instead copy the leadfile's own LOB column value through as
# micro_audience, rather than a fixed string.
_MICRO_AUDIENCE_FROM_LOB_CIDS = {"119750", "119751"}  # IN LOB, AU LOB
# IN DigiSov's leadfile carries its own micro_audience column directly
# (not derived from LOB or a fixed value) -- passed through as-is.
_MICRO_AUDIENCE_FROM_OWN_COLUMN_CIDS = {"120131"}  # IN DigiSov
_LEAD_TEMPLATE_INDUSTRY_VALUE = "All"


# Every Lead Template row also carries four identifier columns that are
# the same for EVERY row in a given file (AID, NC_EMAIL_DETAIL,
# NC_TELE_DETAIL, campaign_code) but aren't derived from the leadfile at
# all -- see read_lead_template_constants, which reads them from the
# template's own existing row before its data gets cleared.
_LEAD_TEMPLATE_CONSTANT_COLUMNS = ["AID", "NC_EMAIL_DETAIL", "NC_TELE_DETAIL", "campaign_code"]
_LEAD_TEMPLATE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def read_lead_template_constants(template_path: str, sheet_name: str) -> dict[str, object]:
    """Reads AID/NC_EMAIL_DETAIL/NC_TELE_DETAIL/campaign_code from the
    first row (top to bottom) whose AID cell isn't blank -- these four
    values are identical for every row in a given Lead Template file, so
    whatever the file's own existing data (or, for a segment with no real
    leads yet, its template/example row -- see the module docstring's note
    on the CXO file) already carries is exactly what new rows need too.
    Must be called BEFORE clearing the file's existing rows (see
    append_leads' clear_existing), since that's the only place these
    values live -- nothing here is configured anywhere.

    Returns {} if no row has a non-blank AID at all (a template that's
    never had this row populated even once has no known values to reuse).
    """
    wb = openpyxl.load_workbook(template_path, read_only=True, data_only=True)
    try:
        ws = wb[sheet_name]
        headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        col_idx = {name: headers.index(name) for name in _LEAD_TEMPLATE_CONSTANT_COLUMNS if name in headers}
        aid_idx = col_idx.get("AID")
        if aid_idx is None:
            return {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            if aid_idx < len(row) and row[aid_idx] not in (None, ""):
                return {name: row[idx] for name, idx in col_idx.items() if idx < len(row)}
        return {}
    finally:
        wb.close()


def add_lead_template_columns(
    leads_df: pd.DataFrame, cid_column: str, lob_column: str = "LOB",
    template_constants: dict[str, object] | None = None,
    asset_title_column: str = "Asset Title", country_column: str = "Country",
    company_size_column: str = "Company Size",
    timestamp_column: str = "Timestamp", now: datetime.datetime | None = None,
) -> pd.DataFrame:
    """Adds/fills every Lead Template-only column on a copy of leads_df:

    - micro_audience: the leadfile's own LOB value for
      _MICRO_AUDIENCE_FROM_LOB_CIDS, the leadfile's own micro_audience
      value for _MICRO_AUDIENCE_FROM_OWN_COLUMN_CIDS, else the fixed value
      from _MICRO_AUDIENCE_BY_CID (blank for any other, unmapped CID).
    - Industry: always _LEAD_TEMPLATE_INDUSTRY_VALUE ("All"), for every CID.
    - template_constants (if given): AID/NC_EMAIL_DETAIL/NC_TELE_DETAIL/
      campaign_code (see read_lead_template_constants), set the same on
      every row.
    - asset_title/country/Q_COMPS (if template_constants was given and the
      leadfile has these columns): passed through from the leadfile's own
      Asset Title/Country/Company Size columns under the Lead Template's
      own header names.
    - user_transaction_date (if template_constants was given): parsed
      per-row from the leadfile's own Timestamp column -- which arrives as
      plain text in whatever format the source system wrote it in -- and
      reformatted to "YYYY-MM-DD HH:MM:SS", the Lead Template's own
      placeholder text's exact format. Falls back to `now` (defaults to
      datetime.datetime.now()) for any row where that column is missing,
      blank, or unparseable.
    """
    df = leads_df.copy()
    micro_audience = []
    for _, row in df.iterrows():
        cid = str(row.get(cid_column, "")).strip()
        if cid in _MICRO_AUDIENCE_FROM_LOB_CIDS:
            micro_audience.append(row.get(lob_column, ""))
        elif cid in _MICRO_AUDIENCE_FROM_OWN_COLUMN_CIDS:
            micro_audience.append(row.get("micro_audience", ""))
        else:
            micro_audience.append(_MICRO_AUDIENCE_BY_CID.get(cid, ""))
    df["micro_audience"] = micro_audience
    df["Industry"] = _LEAD_TEMPLATE_INDUSTRY_VALUE

    if template_constants:
        for name, value in template_constants.items():
            df[name] = value
        if asset_title_column in df.columns:
            df["asset_title"] = df[asset_title_column]
        if country_column in df.columns:
            df["country"] = df[country_column]
        if company_size_column in df.columns:
            df["Q_COMPS"] = df[company_size_column]

        fallback = (now or datetime.datetime.now()).strftime(_LEAD_TEMPLATE_DATE_FORMAT)
        if timestamp_column in df.columns:
            parsed = pd.to_datetime(df[timestamp_column], errors="coerce")
            formatted = parsed.dt.strftime(_LEAD_TEMPLATE_DATE_FORMAT)
            df["user_transaction_date"] = formatted.fillna(fallback)
        else:
            df["user_transaction_date"] = fallback

    return df
