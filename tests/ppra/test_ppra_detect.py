import pytest

from core.ppra.detect import (
    REPORT_AUDIO, REPORT_CS, REPORT_CS_AUDIO, REPORT_CS_DISPLAY, REPORT_CS_DISPLAY_AUDIO_CTV, REPORT_CS_DISPLAY_CTV,
    REPORT_CTV, REPORT_CTV_DISPLAY, REPORT_DISPLAY, REPORT_LINKEDIN, REPORT_TYPE_CHANNELS, REPORT_TYPES,
    UNIT_BY_CHANNEL, analyze, channels_of, has_cs, has_impressions, map_report_type, norm_text,
    report_type_from_flight_lines, single_unit,
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
    (["ABM Connected TV: x"], REPORT_CTV),
    (["ABM Podcast Audio: x"], REPORT_AUDIO),
    (["LinkedIn Sponsored Content: x"], REPORT_LINKEDIN),
    (["ABM Display: x", "ABM CTV: x"], REPORT_CTV_DISPLAY),
    (["ABM Content Syndication: x", "Spotify Audio: x"], REPORT_CS_AUDIO),
    (["ABM Content Syndication: x", "ABM Display x", "ABM OTT x"], REPORT_CS_DISPLAY_CTV),
    (["ABM Content Syndication: x", "ABM Display x", "Audio x", "Connected TV x"], REPORT_CS_DISPLAY_AUDIO_CTV),
    (["ABM Content Syndication: x", "Webinar Promotion: x"], None),  # unknown line: let the user pick
    (["ABM Content Syndication: x", "LinkedIn x"], None),  # not a listed combination
    ([], None),
])
def test_report_type_from_flight_lines(lines, expected):
    assert report_type_from_flight_lines(lines) == expected


@pytest.mark.parametrize("fmt, products, expected", [
    ("Redesigned CS Format", [], REPORT_CS),
    ("Standard", ["Lead Gen"], REPORT_CS),
    ("Redesigned CS Format", ["Content Syndication", "Display"], REPORT_CS_DISPLAY),
    ("Standard", ["Display"], REPORT_DISPLAY),
    ("Standard", ["Video"], REPORT_DISPLAY),
    ("Standard", ["Display", "Connected TV"], REPORT_CTV_DISPLAY),
    ("Standard", ["CTV"], REPORT_CTV),
    ("Standard", ["Audio"], REPORT_AUDIO),
    ("Standard", ["LinkedIn"], REPORT_LINKEDIN),
    ("Combined", ["Content Syndication", "Audio"], REPORT_CS_AUDIO),
    ("Combined", ["Content Syndication", "Display", "CTV"], REPORT_CS_DISPLAY_CTV),
    ("Combined", ["Lead Gen", "Display", "Audio", "Connected TV"], REPORT_CS_DISPLAY_AUDIO_CTV),
    ("Combined", ["Content Syndication", "LinkedIn"], None),  # not a listed type
    ("Combined report", ["Webinar"], None),
    ("", [], None),
    (None, None, None),
])
def test_map_report_type(fmt, products, expected):
    assert map_report_type(fmt, products) == expected


@pytest.mark.parametrize("text, expected", [
    ("Client_Fin Crime_ABM CS_Q1-26", {"CS"}),
    ("Content Syndication - ABM", {"CS"}),
    ("Client_LeadGen_Q3", {"CS"}),
    ("Client Leads Program", {"CS"}),
    ("Client Leadership Display", {"Display"}),  # "Leadership" is not a lead keyword
    ("Client Telco Exec Digital Video - USA", {"Display"}),
    ("Client_Banner_Q1", {"Display"}),
    ("Client CTV Q1", {"CTV"}),
    ("Client OTT Q1", {"CTV"}),
    ("Client Connected TV Q1", {"CTV"}),
    ("Scott Ottawa Q1", set()),  # no OTT token inside words
    ("Client Spotify Q1", {"Audio"}),
    ("Client Podcast Q1", {"Audio"}),
    ("Client_LinkedIn_Q1", {"LinkedIn"}),
    ("Top Accounts - Display and CTV", {"Display", "CTV"}),
    ("Acme_NAMER_ABM_Direct_Q226", set()),
    ("ACSE_Campaign", set()),
])
def test_channels_of_campaign_names(text, expected):
    assert channels_of(text) == expected


def test_report_types_are_channel_sets():
    assert REPORT_TYPES == ("CS", "Display", "CTV", "Audio", "LinkedIn", "CTV + Display", "CS + Display",
                            "CS + Audio", "CS + Display + CTV", "CS + Display + Audio + CTV")
    assert "Other combined" not in REPORT_TYPES
    assert len(set(REPORT_TYPE_CHANNELS.values())) == len(REPORT_TYPES)
    assert UNIT_BY_CHANNEL["LinkedIn"] == "Imps"


@pytest.mark.parametrize("report_type, cs, imps, unit", [
    ("CS", True, False, "Leads"),
    ("Display", False, True, "Imps"),
    ("CTV + Display", False, True, "Imps"),
    ("LinkedIn", False, True, "Imps"),
    ("CS + Audio", True, True, None),
    ("CS + Display + Audio + CTV", True, True, None),
    (None, False, False, None),
])
def test_channel_questions(report_type, cs, imps, unit):
    assert has_cs(report_type) is cs
    assert has_impressions(report_type) is imps
    assert single_unit(REPORT_TYPE_CHANNELS.get(report_type or "", frozenset())) == unit


def test_deck_detection_recognises_new_channels():
    prs = d.new_prs()
    d.title_slide(prs, ["ABM Display: 05/26/2026 - 10/01/2026", "ABM Connected TV 05/26/2026 - 10/01/2026"])
    deck = analyze(prs)
    assert deck.flight_channels == {"Display", "CTV"}
    assert deck.detected_report_type == REPORT_CTV_DISPLAY
