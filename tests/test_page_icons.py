"""Source-level guard: no app file (Summary, pages, core) carries emoji.

Streamlit silently renders an unknown :material/name: as a blank gap, and
AppTest can't see most icons, so a plain source scan is the regression
check that a later edit doesn't quietly re-emoji a page -- same approach as
tests/test_branding.py's sidebar-nav check."""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

# Pictographs, misc symbols/dingbats, and U+FE0F (the variation selector
# that turns a text glyph like "ℹ" into an emoji). Plus the geometric
# status glyphs the old chips used. Deliberately NOT the arrows block:
# "→" is ordinary punctuation in this app's copy.
_EMOJI = re.compile("[🌀-🫿☀-➿⬀-⯿️○●]")

APP_FILES = sorted(
    [_ROOT / "Summary.py", *(_ROOT / "pages").glob("*.py"), *(_ROOT / "core").glob("*.py")]
)


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_app_file_has_no_emoji(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    offenders = [
        f"{path.name}:{n}: {line.strip()}"
        for n, line in enumerate(lines, start=1)
        if _EMOJI.search(line)
    ]
    assert offenders == []
