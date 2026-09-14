import re

import pandas as pd

from core.excel_io import read_leadfile

# A CID is a 5-6 digit number found in the file name (e.g. a ShareFile
# export) -- ported from the standalone File Collation tool's own
# convention. Files with no such number are still collated in full, they
# simply get no CID rather than a fake placeholder.
_CID_IN_FILENAME = re.compile(r"\d{5,6}")


def _normalize_header(col) -> str:
    return re.sub(r"[^a-z0-9]", "", str(col).lower())


def extract_cid_from_filename(filename: str) -> str | None:
    candidates = _CID_IN_FILENAME.findall(filename)
    return candidates[-1] if candidates else None


def flag_duplicate_emails(df: pd.DataFrame, column_name: str = "duplicate_email") -> tuple[int | None, str | None]:
    """Marks rows sharing an email address across any 'email'-like column
    (different source files sometimes name it 'Email' vs 'Email Address').
    Returns (count of leads involved, name of the flag column used), or
    (None, None) if no email column exists. If the data already has a
    column by that name, a different one is used instead of overwriting it.
    """
    email_cols = [c for c in df.columns if "email" in c.lower()]
    if not email_cols:
        return None, None

    if column_name in df.columns:
        column_name = "Duplicate Email Flag"

    def first_email(row):
        for v in row:
            if pd.notna(v) and str(v).strip():
                return str(v).strip().lower()
        return None

    normalized = df[email_cols].apply(first_email, axis=1)
    dup_mask = normalized.notna() & normalized.duplicated(keep=False)
    df[column_name] = dup_mask
    return int(dup_mask.sum()), column_name


def collate_uploaded_files(
    uploaded_files: list, cid_column_name: str = "CID",
) -> tuple[pd.DataFrame, list[tuple[str, str | None, int]], list[tuple[str, str]], list[tuple[str, set, set]]]:
    """Stacks a batch of uploaded lead files (Excel or CSV, any mix) into
    one DataFrame, the same way the standalone File Collation tool does:
    headers are normalized so "Name"/"name"/"NAME" line up across files
    (first file's own header text wins for display), a CID is extracted
    from each filename, and rows sharing an email address across files
    get flagged.

    Returns (master_df, per_file_results, skipped_files, column_notes):
    - per_file_results: (filename, cid or None, lead count) for every
      file that was read successfully, in upload order.
    - skipped_files: (filename, error message) for every file that
      couldn't be read at all -- collation proceeds with whatever did
      load, this is purely a report for the caller to surface.
    - column_notes: (filename, new_columns, missing_columns) for any file
      whose column set differs from the ones seen before it.

    If every file's own CID column would collide with the filename-derived
    one, the derived one is added under "{cid_column_name} (from filename)"
    instead of overwriting real data.
    """
    loaded: list[tuple[str, str | None, pd.DataFrame]] = []
    skipped_files: list[tuple[str, str]] = []
    master_columns: set[str] = set()
    all_keys: set[str] = set()
    header_by_key: dict[str, str] = {}
    column_notes: list[tuple[str, set, set]] = []

    for uploaded_file in uploaded_files:
        filename = getattr(uploaded_file, "name", "") or ""
        try:
            df = read_leadfile(uploaded_file)

            original_cols = list(df.columns)
            normalized_cols = [_normalize_header(c) for c in original_cols]
            final_cols = [header_by_key.setdefault(key, str(orig).strip())
                          for orig, key in zip(original_cols, normalized_cols)]
            df.columns = final_cols

            current_cols = set(final_cols)
            if loaded:
                new_cols = current_cols - master_columns
                missing_cols = master_columns - current_cols
                if new_cols or missing_cols:
                    column_notes.append((filename, new_cols, missing_cols))
            master_columns |= current_cols
            all_keys.update(normalized_cols)

            cid = extract_cid_from_filename(filename)
            loaded.append((filename, cid, df))
        except Exception as exc:
            skipped_files.append((filename, str(exc)))

    if not loaded:
        return pd.DataFrame(), [], skipped_files, column_notes

    effective_cid_column = cid_column_name
    if _normalize_header(cid_column_name) in all_keys:
        effective_cid_column = f"{cid_column_name} (from filename)"

    per_file_results: list[tuple[str, str | None, int]] = []
    for filename, cid, df in loaded:
        if cid is not None:
            df.insert(0, effective_cid_column, cid)
        per_file_results.append((filename, cid, len(df)))

    master_df = pd.concat([df for _, _, df in loaded], ignore_index=True, sort=False)
    flag_duplicate_emails(master_df)

    return master_df, per_file_results, skipped_files, column_notes
