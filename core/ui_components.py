"""Small shared in-page visual components (status chips, empty states, stepper, metric cards).

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


def render_empty_state(message: str, hint: str = "", icon: str = "inbox") -> None:
    """Icon + one short line on what's missing + (optionally) where to fix
    it -- instead of rendering nothing or a bare caption (spec section 2)."""
    text = f":material/{icon}: {message}"
    if hint:
        text += f" — {hint}"
    st.caption(text)


StepState = Literal["done", "current", "todo"]

# (Material icon name, st.badge colour) per step state.
_STEPS: dict[str, tuple[str, str]] = {
    "done": ("check_circle", "green"),
    "current": ("arrow_circle_right", "blue"),
    "todo": ("radio_button_unchecked", "gray"),
}


def step_state(step_num: int, current: int) -> StepState:
    if step_num < current:
        return "done"
    return "current" if step_num == current else "todo"


def stepper_markdown(steps: list[str], current: int) -> str:
    """One row of numbered step badges (1-based `current`), joined by a
    chevron -- a real visual stepper instead of plain text with a coloured
    circle (UI redesign spec, section 5)."""
    parts = []
    for num, label in enumerate(steps, start=1):
        icon, color = _STEPS[step_state(num, current)]
        parts.append(f":{color}-badge[:material/{icon}: {num}. {label}]")
    return " :material/chevron_right: ".join(parts)


def render_stepper(steps: list[str], current: int) -> None:
    st.markdown(stepper_markdown(steps, current))
