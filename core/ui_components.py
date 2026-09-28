"""Small shared in-page visual components (status chips, empty states).

Page chrome (logo, login gate, sidebar) lives in core/branding.py; user-facing
error/warning rendering lives in core/errors.py. This module is for the
card-level building blocks from the UI redesign spec (section 1).
"""
from typing import Literal

import streamlit as st

ChipState = Literal["on", "off", "configured", "needs_setup"]

# (text, st.badge color). Glyphs match the design spec's section 1 exactly.
_CHIPS: dict[str, tuple[str, str]] = {
    "on": ("● On", "green"),
    "off": ("○ Off", "gray"),
    "configured": ("✓ Configured", "blue"),
    "needs_setup": ("⚠ Needs setup", "orange"),
}


def chip_markdown(state: ChipState, label: str = "") -> str:
    """Markdown for one status chip -- the same `:color-badge[...]` markup
    st.badge renders, returned as a string so it can also go inside a tab
    label or a single-line row of several chips."""
    text, color = _CHIPS[state]
    body = f"{label} {text}" if label else text
    return f":{color}-badge[{body}]"


def chip_state(enabled: bool, needs_setup: bool = False) -> ChipState:
    """A feature that's off is just "off", even if it would need setup were
    it on; an enabled feature missing required config is "needs_setup"."""
    if not enabled:
        return "off"
    return "needs_setup" if needs_setup else "on"


def render_status_strip(items: list[tuple[str, ChipState]]) -> None:
    """One row of labeled chips, in a single markdown element."""
    st.markdown("&nbsp; ".join(chip_markdown(state, label) for label, state in items))
