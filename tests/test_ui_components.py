from streamlit.testing.v1 import AppTest

from core.ui_components import chip_markdown, chip_state


def test_chip_markdown_uses_spec_glyphs_and_colors():
    assert chip_markdown("on") == ":green-badge[● On]"
    assert chip_markdown("off") == ":gray-badge[○ Off]"
    assert chip_markdown("configured") == ":blue-badge[✓ Configured]"
    assert chip_markdown("needs_setup") == ":orange-badge[⚠ Needs setup]"


def test_chip_markdown_prefixes_a_label():
    assert chip_markdown("on", "Leadcap") == ":green-badge[Leadcap ● On]"


def test_chip_state_mapping():
    assert chip_state(False) == "off"
    assert chip_state(False, needs_setup=True) == "off"
    assert chip_state(True) == "on"
    assert chip_state(True, needs_setup=True) == "needs_setup"


def test_render_status_strip_renders_one_markdown_row():
    def _app():
        from core.ui_components import render_status_strip
        render_status_strip([("Leadcap", "on"), ("TAL", "needs_setup"), ("Exclusion", "off")])

    at = AppTest.from_function(_app)
    at.run()
    assert not at.exception
    assert len(at.markdown) == 1
    value = at.markdown[0].value
    assert ":green-badge[Leadcap ● On]" in value
    assert ":orange-badge[TAL ⚠ Needs setup]" in value
    assert ":gray-badge[Exclusion ○ Off]" in value
