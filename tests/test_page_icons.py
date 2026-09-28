"""Source-level guard: swept pages carry no decorative emoji.

Streamlit silently renders an unknown :material/name: as a blank gap, and
AppTest can't see most icons, so a plain source scan is the regression
check that a later edit doesn't quietly re-emoji a page -- same approach as
tests/test_branding.py's sidebar-nav check."""
import re
from pathlib import Path

import pytest

_PAGES_DIR = Path(__file__).resolve().parent.parent / "pages"

# Pictographs, misc symbols/dingbats, and U+FE0F (the variation selector
# that turns a text glyph like "ℹ" into an emoji "ℹ️"). Deliberately NOT the
# arrows block: "→" is ordinary punctuation in this app's copy.
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿️]")

# Emoji that are data or exact-text-tested, not decoration:
# - Result-column cells on the upload pages, and the .str.startswith(...)
#   counts over them: Material shorthand doesn't render inside st.dataframe,
#   and tests assert the ✅/❌/⏭️ prefixes.
# - The "📋 Preview leads to send" expander label, which
#   tests/test_convertr_page.py and tests/test_enhancio_page.py match with
#   .startswith("📋 Preview leads to send").
_ALLOWED_LINE = re.compile(r'"Result"|\.str\.startswith\(|📋 Preview leads to send')

SWEPT_PAGES = [
    "3_Settings.py",
    "4_Activity_Log.py",
    "6_Fuzzy_Match.py",
    "5_Box_Tracker.py",
    "7_Convertr.py",
    "8_Enhancio.py",
]


@pytest.mark.parametrize("page", SWEPT_PAGES)
def test_swept_page_has_no_decorative_emoji(page):
    lines = (_PAGES_DIR / page).read_text(encoding="utf-8").splitlines()
    offenders = [
        f"{page}:{n}: {line.strip()}"
        for n, line in enumerate(lines, start=1)
        if _EMOJI.search(line) and not _ALLOWED_LINE.search(line)
    ]
    assert offenders == []
