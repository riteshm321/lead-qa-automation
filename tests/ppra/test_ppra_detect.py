import pytest

from core.ppra.detect import (
    REPORT_CS, REPORT_CS_DISPLAY, REPORT_DISPLAY, REPORT_OTHER, analyze, channels_of, map_report_type, norm_text,
    report_type_from_flight_lines,
)
from ppra import _decks as d


def test_norm_text_collapses_platform_whitespace_but_keeps_en_dash():
    raw = f"Top Accounts {d.EN_DASH}{d.NBSP}Display{d.VT}\n"
    assert norm_text(raw) == f"Top Accounts {d.EN_DASH} Display"


def test_cs_deck_slide_kinds():
    deck = analyze(d.cs_deck())
    kinds = [s.kind for s in deck.slides]
    assert kinds == ["title", "agenda", "highlights", "pacing", "section", "audience_reach", "audience_insights",
                     "content_insights", "industry_insights", "country_insights", "top_accounts_cs",
                     "custom_question", "thank_you"]


def test_titles_are_read_from_title_n_text_boxes_and_normalised():
    deck = analyze(d.cs_deck())
    reach = deck.of_kind("audience_reach")[0]
    assert reach.title == "Audience Reach"  # trailing \xa0 stripped
    assert deck.of_kind("custom_question")[0].title == f"Custom Question {d.EN_DASH} Example"


def test_combined_deck_kinds_and_section_channels():
    deck = analyze(d.combined_deck())
    creative = deck.of_kind("creative_sets")
    assert [sorted(s.section_channels) for s in creative] == [["Display"], ["CS"]]
    assert [s.kind for s in deck.slides].count("halo") == 2
    assert deck.detected_report_type == REPORT_CS_DISPLAY


def test_display_deck_kinds():
    deck = analyze(d.display_deck())
    assert [s.kind for s in deck.slides] == ["title", "pacing", "program_performance", "display_performance",
                                            "top_accounts_display", "thank_you"]
    assert deck.detected_report_type == REPORT_DISPLAY


def test_report_type_from_title_slide_flight_dates():
    assert analyze(d.cs_deck()).detected_report_type == REPORT_CS
    assert analyze(d.cs_deck()).flight_channels == {"CS"}


@pytest.mark.parametrize("lines, expected", [
    (["ABM Content Syndication: 08/04/2026 - 10/01/2026"], REPORT_CS),
    (["ABM Display Advertising: 09/20/2026 - 01/01/2027"], REPORT_DISPLAY),
    (["ABM Content Syndication: x", "ABM Display x"], REPORT_CS_DISPLAY),
    (["ABM Content Syndication: x", "Webinar Promotion: x"], REPORT_OTHER),
    ([], None),
])
def test_report_type_from_flight_lines(lines, expected):
    assert report_type_from_flight_lines(lines) == expected


@pytest.mark.parametrize("fmt, products, expected", [
    ("Redesigned CS Format", [], REPORT_CS),
    ("Redesigned CS Format", ["Content Syndication", "Display"], REPORT_CS_DISPLAY),
    ("Standard", ["Display", "Connected TV"], REPORT_DISPLAY),
    ("Standard", ["Video"], REPORT_DISPLAY),
    ("Standard", ["Audio"], REPORT_DISPLAY),
    ("Combined report", ["Webinar"], REPORT_OTHER),
    ("", [], None),
    (None, None, None),
])
def test_map_report_type(fmt, products, expected):
    assert map_report_type(fmt, products) == expected


@pytest.mark.parametrize("text, expected", [
    ("Client_Fin Crime_ABM CS_Q1-26", {"CS"}),
    ("Content Syndication - ABM", {"CS"}),
    ("Client Telco Exec Digital Video - USA", {"Display"}),
    ("Acme_NAMER_ABM_Direct_Q226", set()),
    ("ACSE_Campaign", set()),
])
def test_channels_of_campaign_names(text, expected):
    assert channels_of(text) == expected
