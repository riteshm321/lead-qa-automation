from core.paste_component import paste_screenshot


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
