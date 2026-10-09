import io

import pytest
from pptx import Presentation
from pptx.oxml.ns import qn

from core.ppra.detect import analyze, iter_shapes, norm_text
from core.ppra.rules import RULES_BY_ID, TABLE_WIDTH, TAKEAWAY_TEMPLATES, estimate_text_height, wrapped_lines
from ppra import _decks as d

OWNER = {"owner_name": "Pat Lee", "owner_title": "CXM", "owner_email": "plee@madisonlogic.com"}


def run_rule(prs, rule_id, report_type="CS", jira=None):
    rule = RULES_BY_ID[rule_id]
    findings = rule.applies(analyze(prs), report_type, jira or {})
    for finding in findings:
        rule.apply(prs, finding)
    return findings


def reopen(prs):
    return Presentation(io.BytesIO(d.to_bytes(prs)))


def shape_named(slide, name):
    return next(s for s in iter_shapes(slide.shapes) if s.name == name)


def slide_of(prs, kind):
    return analyze(prs).of_kind(kind)[0].slide


def paragraphs(shape):
    return [norm_text(p.text) for p in shape.text_frame.paragraphs]


def last(rows):
    return rows[len(rows) - 1]


def pacing_table(prs):
    return shape_named(slide_of(prs, "pacing"), "Table 5")


# ---------------------------------------------------------------- R1-R3 pacing

def test_r1_adds_leads_to_unit_values_only():
    prs = d.cs_deck()
    assert len(run_rule(prs, "R1")) == 1
    rows = [[c.text for c in r.cells] for r in pacing_table(prs).table.rows]
    assert rows[1] == ["Client_NAMER_ABM_AV_2CQ_Direct_Q226", "$1,768", "$1,768", "$0", "26 Leads", "26 Leads",
                       "0 Leads", "100%"]
    assert run_rule(prs, "R1") == []  # idempotent: no "26 Leads Leads"


def test_r1_uses_campaign_keywords_for_imps_and_leads():
    prs = d.combined_deck()
    run_rule(prs, "R1", "CS + Display")
    rows = [[c.text for c in r.cells] for r in pacing_table(prs).table.rows]
    assert rows[1][4:7] == ["320,000 Imps", "320,000 Imps", "0 Imps"]
    assert rows[2][4:7] == ["181 Leads", "181 Leads", "0 Leads"]


def test_r2_total_row_values_and_format():
    prs = d.cs_deck()
    run_rule(prs, "R1")
    frame = pacing_table(prs)
    height_before = frame.height
    assert len(run_rule(prs, "R2")) == 1
    table = frame.table
    total = [c.text for c in last(table.rows).cells]
    assert total == ["Total", "$21,760", "$21,760", "$0", "320 Leads", "320 Leads", "0 Leads", "100%"]
    assert last(table.rows).height == table.rows[0].height
    assert frame.height == height_before + table.rows[0].height
    cell = table.cell(len(table.rows) - 1, 1)
    run = cell.text_frame.paragraphs[0].runs[0]
    assert run.font.bold and run.font.name == "Montserrat"
    tcpr = cell._tc.tcPr
    assert tcpr.find(qn("a:solidFill")).find(qn("a:srgbClr")).get("val") == "EBEEF5"
    assert (tcpr.get("marL"), tcpr.get("marB"), tcpr.get("anchor")) == ("6350", "0", "ctr")
    assert run_rule(prs, "R2") == []  # never a second Total row


def test_r2_mixed_units_are_two_paragraphs_in_one_cell():
    prs = d.combined_deck()
    run_rule(prs, "R1", "CS + Display")
    run_rule(prs, "R2", "CS + Display")
    total = last(pacing_table(prs).table.rows).cells
    assert [p.text for p in total[4].text_frame.paragraphs] == ["320,000 Imps", "181 Leads"]
    assert total[1].text == "$19,946"
    assert total[7].text == "100%"


def test_r2_percent_is_sum_delivered_over_sum_goal():
    prs = d.display_deck()
    run_rule(prs, "R2", "Display")
    total = [c.text for c in last(pacing_table(prs).table.rows).cells]
    assert total[1:4] == ["$35,000", "$7,825", "$27,175"]
    assert total[4:] == ["2,333,333 Imps", "521,611 Imps", "1,811,722 Imps", "22%"]


def test_r3_rebalances_then_fits_12_5_inches_centred():
    prs = d.cs_deck()
    before = [c.width for c in pacing_table(prs).table.columns]
    run_rule(prs, "R3")
    frame = pacing_table(prs)
    widths = [c.width for c in frame.table.columns]
    assert sum(widths) == TABLE_WIDTH and frame.width == TABLE_WIDTH
    assert frame.left == (d.SLIDE_W - TABLE_WIDTH) // 2
    assert widths[0] < before[0]
    assert widths[4] > widths[2]  # Units wider than Budget after the rebalance
    assert run_rule(prs, "R3") == []  # the -600000/+200000 shift happens once


# ---------------------------------------------------------------- R4-R8 deletions

def _deleted_titles(prs, rule_id, report_type="CS"):
    deck = analyze(prs)
    return [deck.slides[f.slide_index].title for f in RULES_BY_ID[rule_id].applies(deck, report_type, {})]


def test_r4_marks_header_only_and_default_chart_slides_and_keeps_data_slides():
    prs = d.cs_deck(countries=())
    titles = _deleted_titles(prs, "R4")
    assert f"Top Accounts {d.EN_DASH} Content Syndication" in titles
    assert "Country Insights" in titles
    assert "Content Insights" not in titles and "Industry Insights" not in titles


def test_r4_never_deletes_a_slide_with_real_data():
    prs = d.new_prs()
    d.top_accounts_cs(prs, rows=[["Acme", "acme.com", "3", "uem", "5"]])
    assert _deleted_titles(prs, "R4") == []


def test_r5_single_country_slide():
    assert _deleted_titles(d.cs_deck(countries=(("United States", "181", "100%"),)), "R5") == ["Country Insights"]
    assert _deleted_titles(d.cs_deck(), "R5") == []


def test_r6_single_channel_halo_with_no_site_visits_only():
    titles = _deleted_titles(d.combined_deck(), "R6", "CS + Display")
    assert len(titles) == 1  # the two-channel one stays


def test_r7_custom_question_example():
    assert _deleted_titles(d.cs_deck(), "R7") == [f"Custom Question {d.EN_DASH} Example"]


def test_r8_creative_sets_only_in_cs_sections():
    assert _deleted_titles(d.combined_deck(), "R8", "CS + Display") == [
        f"ABM CS{d.EN_DASH} Display Data, Creative Sets"]


# ---------------------------------------------------------------- R9 / R21 tables

def test_r9_drops_zero_ctv_column_and_retitles_for_combined_reports():
    prs = d.combined_deck()
    assert run_rule(prs, "R9", "Display") == []  # not a combined report
    findings = run_rule(prs, "R9", "CS + Display")
    assert len(findings) == 1
    slide = prs.slides[findings[0].slide_index]
    frame = shape_named(slide, "Table 2")
    assert "CTV Impressions" not in [c.text for c in frame.table.rows[0].cells]
    assert len(frame.table.columns) == 6
    assert norm_text(shape_named(slide, "Title 2").text_frame.text) == f"Top Accounts {d.EN_DASH} Display"
    assert run_rule(prs, "R9", "CS + Display") == []


def test_r21_top_accounts_table_12_5_inches_centred():
    prs = d.combined_deck()
    findings = run_rule(prs, "R21", "CS + Display")
    assert findings
    frame = shape_named(prs.slides[findings[0].slide_index], "Table 2")
    assert frame.width == TABLE_WIDTH and sum(c.width for c in frame.table.columns) == TABLE_WIDTH
    assert frame.left == (d.SLIDE_W - TABLE_WIDTH) // 2
    assert run_rule(prs, "R21", "CS + Display") == []


# ---------------------------------------------------------------- text rules

def test_r10_hyperlinks_the_split_platform_url():
    prs = d.cs_deck()
    assert len(run_rule(prs, "R10")) == 2
    prs = reopen(prs)
    box = shape_named(slide_of(prs, "audience_reach"), "TextBox 14")
    runs = box.text_frame.paragraphs[0].runs
    linked = [r for r in runs if r.hyperlink.address]
    url = "https://platform.madisonlogic.com/platform/3836/programs/139823"
    assert "".join(r.text for r in linked) == url
    assert all(r.hyperlink.address == url for r in linked)
    assert norm_text(box.text_frame.text) == f"Click to view on ML Platform {url}"
    assert run_rule(prs, "R10") == []


def test_r11_rounds_float_noise_to_two_places():
    prs = d.display_deck()
    run_rule(prs, "R11", "Display")
    slide = slide_of(prs, "display_performance")
    assert paragraphs(shape_named(slide, "TextBox 12"))[1] == "19.92%"
    assert shape_named(slide, "Table 21").table.cell(1, 4).text == "0.02%"
    assert run_rule(prs, "R11", "Display") == []


def test_r12_removes_empty_site_visit_kpi_lines():
    prs = d.display_deck()
    run_rule(prs, "R12", "Display")
    box = shape_named(slide_of(prs, "program_performance"), "TextBox 7")
    assert paragraphs(box) == ["83%", "Penetration Rate", "", "97.16%", "of Impressions delivered"]


def test_r13_company_size_thousands_and_open_top_band():
    prs = d.cs_deck()
    run_rule(prs, "R13")
    box = shape_named(slide_of(prs, "highlights"), "TextBox 7")
    assert paragraphs(box)[1:] == ["44% of companies had 1,000-4,999 employees",
                                   "28% of companies had 10,000+ employees"]
    assert run_rule(prs, "R13") == []


def _label_rprs(chart_shape):
    return list(chart_shape.chart._chartSpace.iter(qn("a:defRPr")))


def test_r14_country_pie_labels_bold_and_one_point_bigger_once():
    prs = d.cs_deck()
    run_rule(prs, "R14")
    run_rule(prs, "R14")
    rprs = [r for r in _label_rprs(shape_named(slide_of(prs, "country_insights"), "Chart 2"))
            if r.getparent().getparent().getparent().getparent().tag == qn("c:dLbls")]
    assert rprs and all(r.get("b") == "1" and r.get("sz") == "1000" for r in rprs)


def test_r14_doughnut_labels_bold_12pt():
    prs = d.display_deck()
    run_rule(prs, "R14", "Display")
    chart = shape_named(slide_of(prs, "program_performance"), "Chart 8")
    rprs = [r for r in _label_rprs(chart) if r.getparent().getparent().getparent().getparent().tag == qn("c:dLbls")]
    assert rprs and all(r.get("b") == "1" and r.get("sz") == "1200" for r in rprs)
    assert run_rule(prs, "R14", "Display") == []


def _takeaway(prs, kind, name):
    return paragraphs(shape_named(slide_of(prs, kind), name))


def test_r15_audience_reach_top_three_topics():
    prs = d.cs_deck()
    run_rule(prs, "R15")
    text = _takeaway(prs, "audience_reach", "Rectangle 13")
    assert text == ["Key Takeaways:", "26%",
                    "of leads delivered from accounts actively engaging with the following top 3 intent topics:",
                    "", "Device Security", "Device Enrollment", "Endpoint Management"]
    box = shape_named(slide_of(prs, "audience_reach"), "Rectangle 13")
    numbered = [p for p in box.text_frame.paragraphs if p._p.find(".//" + qn("a:buAutoNum")) is not None]
    assert len(numbered) == 3
    assert run_rule(prs, "R15") == []


@pytest.mark.parametrize("topics, sentence", [
    (["Device Security", "Device Enrollment"], "engaging with the following top 2 intent topics:"),
    (["Device Security"], "engaging with the following top intent topic:"),
])
def test_r15_fewer_than_three_topics(topics, sentence):
    prs = d.cs_deck(topics=topics)
    run_rule(prs, "R15")
    text = _takeaway(prs, "audience_reach", "Rectangle 13")
    assert text[2].endswith(sentence)
    assert text[4:] == topics


def test_r15_skips_when_the_lead_percentage_is_blank():
    prs = d.new_prs()
    d.audience_reach(prs, pct="% ")
    d.audience_insights(prs, ["A", "B", "C"])
    assert run_rule(prs, "R15") == []


def test_r16_content_insights_top_job_titles():
    prs = d.cs_deck()
    run_rule(prs, "R16")
    assert _takeaway(prs, "content_insights", "Rectangle 14") == [
        "Key Takeaways:", "", "The following are the top 3 job titles:", "",
        "Chief Operations Officer", "Chief Technology Officer", "Chief Information Officer"]
    assert run_rule(prs, "R16") == []


def test_r16_two_job_titles():
    prs = d.cs_deck(job_titles=(("CEO", "5", "50%"), ("CTO", "5", "50%")))
    run_rule(prs, "R16")
    text = _takeaway(prs, "content_insights", "Rectangle 14")
    assert text[2] == "The following are the top 2 job titles:" and text[4:] == ["CEO", "CTO"]


def test_r17_percentage_template_and_placeholder_removed():
    prs = d.new_prs()
    d.audience_insights(prs, ["A", "B", "C"], pct_runs=(("79% ", True), ("of accounts are trending on ", None),
                                                        ("5+ ", True), ("intent topics", None)))
    run_rule(prs, "R17")
    text = _takeaway(prs, "audience_insights", "Rectangle 1")
    assert text[:2] == ["Key Takeaways:", TAKEAWAY_TEMPLATES["audience_insights"].format(pct="79")]
    assert not any(t.startswith("[Topics trending") for t in text)
    runs = shape_named(slide_of(prs, "audience_insights"), "Rectangle 1").text_frame.paragraphs[1].runs
    assert runs[0].text == "79% " and runs[0].font.bold  # original formatting kept
    assert run_rule(prs, "R17") == []


@pytest.mark.parametrize("first_run", ["ERROR:Division by zero% ", "0% "])
def test_r17_error_or_zero_falls_back_to_top_topics(first_run):
    prs = d.new_prs()
    d.audience_insights(prs, ["Fraud", "Forensics"], pct_runs=((first_run, True),
                                                               ("of accounts are trending on 5+ intent topics", None)))
    run_rule(prs, "R17")
    text = _takeaway(prs, "audience_insights", "Rectangle 1")
    assert text[1:5] == ["The following are the top 2 intent topics in your campaign:", "", "Fraud", "Forensics"]
    assert run_rule(prs, "R17") == []


def test_r18_country_takeaway_three_countries():
    prs = d.cs_deck(countries=(("United States", "300", "75%"), ("Canada", "60", "15%"), ("India", "40", "10%")))
    run_rule(prs, "R18")
    box = shape_named(slide_of(prs, "country_insights"), "Rectangle 1")
    p = box.text_frame.paragraphs[2]
    assert norm_text(p.text) == ("75% of leads (300 of 400) came from the United States, followed by Canada (15%) "
                                 "and India (10%).")
    assert p.runs[0].font.bold and not p.runs[1].font.bold
    assert p.runs[0].text == "75% of leads (300 of 400) came from the United States"
    assert run_rule(prs, "R18") == []


def test_r18_two_countries():
    prs = d.cs_deck()
    run_rule(prs, "R18")
    assert _takeaway(prs, "country_insights", "Rectangle 1")[2] == (
        "97% of leads (311 of 320) came from the United States, followed by Canada (3%).")


def test_r19_autofit_never_shrinks_and_fits_estimate():
    prs = d.cs_deck()
    run_rule(prs, "R16")
    box = shape_named(slide_of(prs, "content_insights"), "Rectangle 14")
    original = box.height
    run_rule(prs, "R19")
    body = box.text_frame._txBody.find(qn("a:bodyPr"))
    assert body.find(qn("a:spAutoFit")) is not None
    assert box.height >= original and box.height >= estimate_text_height(box)
    assert run_rule(prs, "R19") == []


def test_wrapped_lines_breaks_on_words():
    assert wrapped_lines("aaa bbb ccc", 7) == 2
    assert wrapped_lines("x" * 25, 10) == 3
    assert wrapped_lines("", 10) == 1


def test_r20_thank_you_owner_and_mailto():
    prs = d.cs_deck()
    assert run_rule(prs, "R20", jira={}) == []  # nothing to fill without ticket data
    run_rule(prs, "R20", jira=OWNER)
    prs = reopen(prs)
    box = shape_named(slide_of(prs, "thank_you"), "TextBox 7")
    assert paragraphs(box) == ["Pat Lee", "CXM", "plee@madisonlogic.com"]
    assert box.text_frame.paragraphs[0].runs[0].font.bold  # run formatting kept
    assert box.text_frame.paragraphs[2].runs[0].hyperlink.address == "mailto:plee@madisonlogic.com"
    assert run_rule(prs, "R20", jira=OWNER) == []


def test_r20_replaces_ml_team_member_placeholders():
    prs = d.combined_deck()
    run_rule(prs, "R20", "CS + Display", jira=OWNER)
    assert paragraphs(shape_named(slide_of(prs, "thank_you"), "TextBox 7")) == [
        "Pat Lee", "CXM", "plee@madisonlogic.com"]
