import os
import re

from core.paste_component import paste_screenshot

_COMPONENT_HTML_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "core", "static", "paste_component", "index.html",
)


def test_paste_screenshot_returns_none_by_default(monkeypatch):
    # The component itself can't be driven headlessly (it needs a real
    # browser paste event) — this confirms the wrapper correctly forwards
    # declare_component's return value, including the "nothing pasted yet"
    # default of None.
    monkeypatch.setattr(
        "core.paste_component._paste_screenshot_component",
        lambda key=None, default=None: default,
    )
    assert paste_screenshot(key="test_key") is None


def test_paste_screenshot_returns_component_value(monkeypatch):
    monkeypatch.setattr(
        "core.paste_component._paste_screenshot_component",
        lambda key=None, default=None: "data:image/png;base64,abc123",
    )
    assert paste_screenshot(key="test_key") == "data:image/png;base64,abc123"


def test_component_html_marks_every_postmessage_as_a_streamlit_message():
    # Regression test: Streamlit's ComponentRegistry.onMessageEvent silently
    # drops any postMessage lacking isStreamlitMessage: true — before it
    # even looks at `type` — so every window.parent.postMessage(...) call
    # in the component's frontend must include it. Missing this field was
    # the actual root cause of a real "Your app is having trouble loading
    # the component" failure that only showed up in a live browser (this
    # can't be driven by AppTest, which is why it's checked textually here
    # rather than caught by the other tests in this file).
    with open(_COMPONENT_HTML_PATH, encoding="utf-8") as f:
        html = f.read()

    post_message_calls = re.findall(r"postMessage\(\s*(\{.*?\})\s*,", html, re.DOTALL)
    assert post_message_calls, "expected at least one window.parent.postMessage(...) call in the component"
    for call in post_message_calls:
        assert "isStreamlitMessage: true" in call, f"postMessage call missing isStreamlitMessage: true: {call}"
