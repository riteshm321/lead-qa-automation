import os
from contextlib import ExitStack
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from core.app_settings import save_jira_settings
from core.jira_client import JiraError
from core.ppra import engine
from ppra import _decks as d

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "pages",
                          "10_PPRA_Reports.py")
_KEY = "TM-10001"
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

TICKET = {
    "key": _KEY, "summary": "PPR - Client X", "client_name": "Client X", "report_format": "Redesigned CS Format",
    "products": ["Content Syndication"], "flight_start": "2026-08-04", "flight_end": "2026-10-01",
    "reporter": {"accountId": "acc-123", "displayName": "Sam Reporter"},
    "owner_name": "Pat Lee", "owner_title": "CXM", "owner_email": "plee@madisonlogic.com", "attachments": [],
}
TRANSITIONS = [{"id": "21", "name": "In Progress", "to": "In Progress"},
               {"id": "31", "name": "Send to Client", "to": "Client Review"}]


def _patches(stack: ExitStack, **overrides) -> dict:
    """Patch every Jira call the page makes; returns the mocks by name."""
    defaults = {"fetch_ppra_ticket": {"return_value": TICKET}, "post_ppra_deck": {},
                "get_issue_status": {"return_value": "In Progress"},
                "get_transitions": {"return_value": TRANSITIONS}, "transition_issue": {}}
    defaults.update(overrides)
    return {name: stack.enter_context(patch(f"core.jira_client.{name}", **kwargs))
            for name, kwargs in defaults.items()}


def _to_review(tmp_path, monkeypatch, deck=None):
    monkeypatch.chdir(tmp_path)
    save_jira_settings("https://example.atlassian.net", "me@x.com", "tok")
    at = AppTest.from_file(_PAGE_PATH, default_timeout=60)
    at.run()
    at.text_input(key="ppra_ticket_input").set_value(f"https://example.atlassian.net/browse/{_KEY}").run()
    at.button(key="ppra_fetch_button").click().run()
    at.get("file_uploader")[0].set_value(("raw.pptx", d.to_bytes(deck or d.cs_deck()), _PPTX_MIME)).run()
    assert not at.exception
    return at


def _format_and_mark_downloaded(at):
    at.button(key=f"ppra_format_button_{_KEY}").click().run()
    assert not at.exception
    at.session_state["ppra_tickets"][_KEY]["downloaded"] = True
    at.run()


def _stepper(at) -> str:
    return next(m.value for m in at.markdown if "1. Ticket" in m.value)


def test_warns_when_jira_is_not_set_up(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=30)
    at.run()
    assert not at.exception
    assert any("Jira account" in w.value for w in at.warning)
    assert at.button(key="ppra_fetch_button").disabled
    assert ":blue-badge[:material/arrow_circle_right: 1. Ticket]" in _stepper(at)


def test_ticket_to_post_flow(tmp_path, monkeypatch):
    with ExitStack() as stack:
        mocks = _patches(stack)
        at = _to_review(tmp_path, monkeypatch)
        assert mocks["fetch_ppra_ticket"].call_args.args[3] == _KEY
        assert any(_KEY in m.value for m in at.markdown)
        assert at.selectbox(key=f"ppra_report_type_{_KEY}").value == "CS"
        assert any(":blue-badge[CS: Leads]" in m.value and "From the ticket" in m.value for m in at.markdown)
        # Scanned automatically: everything found starts selected.
        assert at.toggle(key=f"ppra_rule_{_KEY}_R1").value is True
        assert at.checkbox(key=f"ppra_group_{_KEY}_pacing").value is True
        assert "3. Review" in _stepper(at) and "arrow_circle_right: 3. Review" in _stepper(at)

        at.button(key=f"ppra_format_button_{_KEY}").click().run()
        assert not at.exception
        assert at.button(key=f"ppra_post_button_{_KEY}").disabled  # not downloaded yet

        at.session_state["ppra_tickets"][_KEY]["downloaded"] = True
        at.run()
        assert not at.button(key=f"ppra_post_button_{_KEY}").disabled
        assert any("Will attach:** TM-10001 - Formatted.pptx" in m.value for m in at.markdown)
        at.button(key=f"ppra_post_button_{_KEY}").click().run()

    assert not at.exception
    mocks["post_ppra_deck"].assert_called_once()
    args = mocks["post_ppra_deck"].call_args.args
    assert args[3] == _KEY and args[5:] == ("acc-123", "Sam Reporter")
    assert args[4] == at.session_state["ppra_tickets"][_KEY]["formatted"]
    assert any("Posted" in s.value for s in at.success)
    assert "arrow_circle_right" not in _stepper(at)  # every step done


def test_review_summary_groups_and_skipped(tmp_path, monkeypatch):
    with ExitStack() as stack:
        _patches(stack)
        at = _to_review(tmp_path, monkeypatch)
    scan = at.session_state["ppra_tickets"][_KEY]["scan"]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Changes to make"] == str(scan.change_count())
    assert metrics["Slides to remove"] == "2"
    assert metrics["Skipped (not in this deck)"] == str(len(scan.skipped_rule_ids()))
    # AppTest reports an st.expander that has an icon as a "status" block.
    labels = [e.label for e in [*at.expander, *at.get("status")]]
    assert any(label.startswith("Pacing table - ") for label in labels)
    assert "Slides to remove - 2 slides" in labels
    assert "Advanced: choose individual changes" in labels
    assert any(label.startswith("Skipped - not in this deck") for label in labels)
    lines = [m.value for m in at.markdown]
    assert any(v.startswith("Slide 4 - Add Total row: 320 Leads, \\$21,760") for v in lines)
    # Rules with nothing to do get no toggle, just a line in Skipped.
    assert not [t for t in at.toggle if t.key == f"ppra_rule_{_KEY}_R9"]


def _checklist(at):
    return [c for c in at.checkbox if str(c.key).startswith(f"ppra_check_{_KEY}_")]


def test_before_you_post_checklist(tmp_path, monkeypatch):
    with ExitStack() as stack:
        _patches(stack)
        at = _to_review(tmp_path, monkeypatch)
        boxes = _checklist(at)
        # The ticket has the owner details, so only the thumbnails are manual.
        assert [b.label for b in boxes] == ["Slide 8 · Add the asset thumbnails"]
        assert {m.label: m.value for m in at.metric}["Before you post"] == "1"
        assert any("Before you post** · 0 of 1 checked" in m.value for m in at.markdown)
        assert not any("Nothing left to check by hand" in m.value for m in at.markdown)
        assert not [e for e in [*at.expander, *at.get("status")] if "attention" in e.label.lower()]

        boxes[0].check().run()
        assert any("Nothing left to check by hand" in m.value for m in at.markdown)
        # The tick survives formatting (same item in the formatted deck).
        at.button(key=f"ppra_format_button_{_KEY}").click().run()
        assert not at.exception
        assert _checklist(at)[0].value is True
        assert any("Nothing left to check by hand" in m.value for m in at.markdown)


def test_checklist_lists_missing_owner_details_and_empty_state(tmp_path, monkeypatch):
    display = {**TICKET, "report_format": "Standard", "products": ["Display"]}
    with ExitStack() as stack:
        _patches(stack, fetch_ppra_ticket={"return_value": {**display, "owner_title": ""}})
        at = _to_review(tmp_path, monkeypatch, deck=d.display_deck())
        labels = [b.label for b in _checklist(at)]
        assert labels == ["Slide 5 · Add the owner name, title and email (missing on the Jira ticket)"]

    with ExitStack() as stack:
        _patches(stack, fetch_ppra_ticket={"return_value": display})
        at = _to_review(tmp_path, monkeypatch, deck=d.display_deck())
        assert _checklist(at) == []
        assert any("Nothing left to check by hand" in m.value for m in at.markdown)
        assert {m.label: m.value for m in at.metric}["Before you post"] == "0"


def test_group_include_and_rule_toggles_reach_format_deck(tmp_path, monkeypatch):
    with ExitStack() as stack:
        _patches(stack)
        fmt = stack.enter_context(patch("core.ppra.engine.format", wraps=engine.format))
        at = _to_review(tmp_path, monkeypatch)
        at.checkbox(key=f"ppra_group_{_KEY}_remove").uncheck().run()
        at.toggle(key=f"ppra_rule_{_KEY}_R1").set_value(False).run()
        assert {m.label: m.value for m in at.metric}["Slides to remove"] == "0"
        assert any(m.value.startswith("~~Slide 4 - Add Leads") for m in at.markdown)  # struck through
        at.button(key=f"ppra_format_button_{_KEY}").click().run()
    assert not at.exception
    enabled = fmt.call_args.args[3]
    assert "R1" not in enabled and not {"R4", "R5", "R6", "R7", "R8"} & set(enabled)
    assert {"R2", "R15", "R20"} <= set(enabled)


def test_changing_the_selection_after_format_drops_the_stale_deck(tmp_path, monkeypatch):
    with ExitStack() as stack:
        _patches(stack)
        at = _to_review(tmp_path, monkeypatch)
        _format_and_mark_downloaded(at)
        assert not at.button(key=f"ppra_post_button_{_KEY}").disabled
        at.toggle(key=f"ppra_rule_{_KEY}_R2").set_value(False).run()
    assert "formatted" not in at.session_state["ppra_tickets"][_KEY]
    assert not [b for b in at.button if b.key == f"ppra_post_button_{_KEY}"]


def test_uploaded_final_deck_is_posted_instead_and_unlocks_post(tmp_path, monkeypatch):
    final = d.to_bytes(d.display_deck())
    with ExitStack() as stack:
        mocks = _patches(stack)
        at = _to_review(tmp_path, monkeypatch)
        at.button(key=f"ppra_format_button_{_KEY}").click().run()
        assert at.button(key=f"ppra_post_button_{_KEY}").disabled
        at.get("file_uploader")[1].set_value(("my final.pptx", final, _PPTX_MIME)).run()
        assert not at.button(key=f"ppra_post_button_{_KEY}").disabled  # no download needed
        assert any("Will attach:** my final.pptx" in m.value and "Your upload" in m.value for m in at.markdown)
        at.button(key=f"ppra_post_button_{_KEY}").click().run()
    assert not at.exception
    assert mocks["post_ppra_deck"].call_args.args[4] == final
    assert any("Posted my final.pptx as TM-10001.pptx" in s.value for s in at.success)


def test_status_change_then_start_a_new_report(tmp_path, monkeypatch):
    with ExitStack() as stack:
        mocks = _patches(stack)
        at = _to_review(tmp_path, monkeypatch)
        _format_and_mark_downloaded(at)
        at.button(key=f"ppra_post_button_{_KEY}").click().run()
        assert any(":blue-badge[In Progress]" in m.value for m in at.markdown)
        assert at.selectbox(key=f"ppra_transition_{_KEY}").options == ["In Progress", "Send to Client -> Client Review"]
        assert at.button(key=f"ppra_transition_button_{_KEY}").disabled

        mocks["get_issue_status"].return_value = "Client Review"
        at.selectbox(key=f"ppra_transition_{_KEY}").set_value("Send to Client -> Client Review").run()
        at.button(key=f"ppra_transition_button_{_KEY}").click().run()
        assert not at.exception
        assert mocks["transition_issue"].call_args.args[3:] == (_KEY, "31")
        assert any("Status changed to Client Review" in s.value for s in at.success)
        assert any(":blue-badge[Client Review]" in m.value for m in at.markdown)

        at.button(key="ppra_new_report_button").click().run()
        assert not at.exception
        assert at.text_input(key="ppra_ticket_input").value == ""
        leftover = [k for k in at.session_state.filtered_state if k.startswith("ppra_") and k != "ppra_nonce"]
        assert set(leftover) <= {"ppra_ticket_input", "ppra_fetch_button"}  # re-created by this run's widgets
        assert "ppra_tickets" not in at.session_state
        assert at.session_state["ppra_nonce"] == 1
        assert not at.get("file_uploader")
        assert ":blue-badge[:material/arrow_circle_right: 1. Ticket]" in _stepper(at)

        # The same ticket again starts from an empty deck step.
        at.text_input(key="ppra_ticket_input").set_value(_KEY).run()
        at.button(key="ppra_fetch_button").click().run()
        assert len(at.get("file_uploader")) == 1 and at.get("file_uploader")[0].value is None
        assert not [s for s in at.selectbox if s.key == f"ppra_report_type_{_KEY}"]


def test_new_report_is_offered_even_without_a_status_change(tmp_path, monkeypatch):
    with ExitStack() as stack:
        _patches(stack)
        at = _to_review(tmp_path, monkeypatch)
        _format_and_mark_downloaded(at)
        at.button(key=f"ppra_post_button_{_KEY}").click().run()
        assert at.button(key="ppra_new_report_button")


def test_status_problems_are_shown_with_render_problem(tmp_path, monkeypatch):
    with ExitStack() as stack:
        mocks = _patches(stack, get_transitions={"side_effect": JiraError("Jira returned 403 for TM-10001")})
        at = _to_review(tmp_path, monkeypatch)
        _format_and_mark_downloaded(at)
        at.button(key=f"ppra_post_button_{_KEY}").click().run()
        assert not at.exception
        assert any("Couldn't load the ticket's statuses" in e.value for e in at.error)
        assert at.button(key=f"ppra_transitions_retry_{_KEY}")

        mocks["get_transitions"].side_effect = None
        mocks["get_transitions"].return_value = TRANSITIONS
        mocks["transition_issue"].side_effect = JiraError("Jira returned 400 for TM-10001: resolution required")
        at.button(key=f"ppra_transitions_retry_{_KEY}").click().run()
        at.selectbox(key=f"ppra_transition_{_KEY}").set_value("In Progress").run()
        at.button(key=f"ppra_transition_button_{_KEY}").click().run()
    assert not at.exception
    assert any("didn't change the status" in e.value and "resolution required" in e.value for e in at.error)


def test_data_issues_panel_shows_before_formatting(tmp_path, monkeypatch):
    deck = d.cs_deck()
    d.key_takeaways_slide(deck)
    with ExitStack() as stack:
        _patches(stack)
        at = _to_review(tmp_path, monkeypatch, deck)
    assert not at.session_state["ppra_tickets"][_KEY].get("formatted")
    values = [m.value for m in at.markdown]
    assert any("Data issues in the original report" in v for v in values)
    assert any("Key Takeaways · 4 blank values" in v for v in values)
    assert any("Fix these in the source report" in c.value for c in at.caption)
    assert not at.button(key=f"ppra_format_button_{_KEY}").disabled  # formatting stays allowed
