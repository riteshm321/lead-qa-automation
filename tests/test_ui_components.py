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


def test_render_empty_state_with_hint():
    def _app():
        from core.ui_components import render_empty_state
        render_empty_state("No TAL sources configured yet.", "Click **➕ Add TAL Source** below.")

    at = AppTest.from_function(_app)
    at.run()
    assert not at.exception
    assert at.caption[0].value == ":material/inbox: No TAL sources configured yet. — Click **➕ Add TAL Source** below."


def test_render_empty_state_without_hint_and_custom_icon():
    def _app():
        from core.ui_components import render_empty_state
        render_empty_state("TAL check is off.", icon="toggle_off")

    at = AppTest.from_function(_app)
    at.run()
    assert at.caption[0].value == ":material/toggle_off: TAL check is off."


def test_step_state_mapping():
    from core.ui_components import step_state
    assert step_state(1, 2) == "done"
    assert step_state(2, 2) == "current"
    assert step_state(3, 2) == "todo"


def test_stepper_markdown_marks_done_current_and_upcoming_steps():
    from core.ui_components import stepper_markdown
    assert stepper_markdown(["Run Check", "Review & Finalize", "Post to Jira"], 2) == (
        ":green-badge[:material/check_circle: 1. Run Check]"
        " :material/chevron_right: "
        ":blue-badge[:material/arrow_circle_right: 2. Review & Finalize]"
        " :material/chevron_right: "
        ":gray-badge[:material/radio_button_unchecked: 3. Post to Jira]"
    )


def test_stepper_markdown_past_the_last_step_marks_everything_done():
    from core.ui_components import stepper_markdown
    value = stepper_markdown(["Run Check", "Review & Finalize"], 3)
    assert "blue-badge" not in value and "gray-badge" not in value
    assert value.count(":green-badge[") == 2


def test_render_stepper_renders_one_markdown_element():
    def _app():
        from core.ui_components import render_stepper
        render_stepper(["Run Check", "Review & Finalize"], 1)

    at = AppTest.from_function(_app)
    at.run()
    assert not at.exception
    assert len(at.markdown) == 1
    assert at.markdown[0].value.startswith(":blue-badge[:material/arrow_circle_right: 1. Run Check]")
    assert len(at.caption) == 0  # never a caption -- see Run Check's "completed" caption test


def test_render_metric_cards_renders_bordered_icon_metrics_in_order():
    def _app():
        from core.ui_components import render_metric_cards
        render_metric_cards([("Leads In", 3, "group"), ("Valid", 1, "check_circle")])

    at = AppTest.from_function(_app)
    at.run()
    assert not at.exception
    assert [m.label for m in at.metric] == ["Leads In", "Valid"]
    assert [m.value for m in at.metric] == ["3", "1"]
    assert [m.proto.icon for m in at.metric] == [":material/group:", ":material/check_circle:"]
    assert all(m.proto.show_border for m in at.metric)
