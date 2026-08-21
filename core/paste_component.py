import os

import streamlit.components.v1 as components

_COMPONENT_DIR = os.path.join(os.path.dirname(__file__), "static", "paste_component")

_paste_screenshot_component = components.declare_component("paste_screenshot", path=_COMPONENT_DIR)


def paste_screenshot(key: str) -> str | None:
    """Renders the paste-a-screenshot box and returns the pasted image as a
    base64 data URL (e.g. "data:image/png;base64,...."), or None if nothing
    has been pasted yet in this session."""
    return _paste_screenshot_component(key=key, default=None)
