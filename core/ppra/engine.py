"""Scan and format a raw PPRA deck (bytes in, bytes out).

scan() reports what every rule would change on the uploaded deck; format()
applies the enabled rules in EXECUTION_ORDER, each one re-reading the deck as
it is at that point, then removes the slides the deleting rules picked (all
decided from the ORIGINAL deck's data) last, highest index first.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from pptx import Presentation

from core.app_logging import get_logger
from core.ppra.detect import DeckInfo, SlideInfo, analyze, is_top_level, norm_text
from core.ppra.rules import (
    CHAR_WIDTH_EM, EXECUTION_ORDER, RULES, RULES_BY_ID, Finding, data_rows, pacing_tables, row_unit, wrapped_lines,
)

_P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"


@dataclass
class AttentionItem:
    slide_number: int | None
    slide_title: str
    message: str

    def __str__(self) -> str:
        where = f"Slide {self.slide_number} ({self.slide_title})" if self.slide_number else "Deck"
        return f"{where}: {self.message}"


@dataclass
class ScanResult:
    report_type: str | None
    detected_report_type: str | None
    findings: dict[str, list[Finding]] = field(default_factory=dict)  # every rule id present
    attention: list[AttentionItem] = field(default_factory=list)
    slide_titles: list[str] = field(default_factory=list)

    def found_rule_ids(self) -> list[str]:
        return [rid for rid, items in self.findings.items() if items]

    def skipped_rule_ids(self) -> list[str]:
        return [rid for rid, items in self.findings.items() if not items]

    def change_count(self, rule_ids=None) -> int:
        """Findings of the non-deleting rules (all, or only rule_ids)."""
        return sum(len(items) for rid, items in self.findings.items()
                   if not RULES_BY_ID[rid].deletes and (rule_ids is None or rid in rule_ids))

    def slides_to_remove(self, rule_ids=None) -> list[int]:
        """Distinct 1-based slide numbers the deleting rules picked."""
        return sorted({f.slide_index + 1 for rid, items in self.findings.items()
                       if RULES_BY_ID[rid].deletes and (rule_ids is None or rid in rule_ids) for f in items})


def load(pptx_bytes: bytes):
    return Presentation(io.BytesIO(pptx_bytes))


def save(prs) -> bytes:
    buffer = io.BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


def detect_report_type(pptx_bytes: bytes) -> str | None:
    return analyze(load(pptx_bytes)).detected_report_type


def scan(pptx_bytes: bytes, report_type: str | None, jira_info: dict | None = None) -> ScanResult:
    deck = analyze(load(pptx_bytes))
    findings = {rule.id: rule.applies(deck, report_type, jira_info) for rule in RULES}
    return ScanResult(
        report_type=report_type, detected_report_type=deck.detected_report_type, findings=findings,
        attention=attention_items(deck, report_type, jira_info),
        slide_titles=[s.label for s in deck.slides],
    )


def delete_slides(prs, indices) -> None:
    """Remove slides cleanly: drop the sldId entry, then the presentation's
    relationship to the slide part (python-pptx only drops a rel once
    nothing references it), plus any section-list reference, so PowerPoint
    opens the file without a repair prompt."""
    sld_id_lst = prs.slides._sldIdLst
    entries = list(sld_id_lst)
    for index in sorted(set(indices), reverse=True):
        entry = entries[index]
        slide_id, r_id = entry.get("id"), entry.rId
        sld_id_lst.remove(entry)
        prs.part.drop_rel(r_id)
        for ref in prs.part._element.iter(f"{{{_P14_NS}}}sldId"):
            if ref.get("id") == slide_id:
                ref.getparent().remove(ref)


def _change_line(finding: Finding) -> str:
    detail = f" ({finding.before} -> {finding.after})" if finding.before or finding.after else ""
    return f"{finding.rule_id}: {finding.description}{detail}"


def format_deck(pptx_bytes: bytes, report_type: str | None, jira_info: dict | None = None,
                enabled_rule_ids=None) -> tuple[bytes, list[str], list[AttentionItem]]:
    enabled = set(enabled_rule_ids) if enabled_rule_ids is not None else {r.id for r in RULES}
    prs = load(pptx_bytes)
    original = analyze(prs)
    change_log: list[str] = []
    problems: list[AttentionItem] = []

    to_delete: dict[int, Finding] = {}
    for rule in RULES:
        if rule.deletes and rule.id in enabled:
            for finding in rule.applies(original, report_type, jira_info):
                to_delete.setdefault(finding.slide_index, finding)

    for rule_id in EXECUTION_ORDER:
        if rule_id not in enabled:
            continue
        rule = RULES_BY_ID[rule_id]
        deck = analyze(prs)
        for finding in rule.applies(deck, report_type, jira_info):
            if finding.slide_index in to_delete:
                continue
            try:
                rule.apply(prs, finding)
            except Exception as exc:  # noqa: BLE001 - one bad slide must not sink the whole deck
                get_logger().exception("PPRA rule %s failed on slide %s", rule_id, finding.slide_index + 1)
                info = deck.slides[finding.slide_index]
                problems.append(AttentionItem(info.number, info.label,
                                              f"{rule_id} could not be applied ({exc}) - check this by hand."))
                continue
            change_log.append(_change_line(finding))

    for index in sorted(to_delete):
        change_log.append(_change_line(to_delete[index]))
    delete_slides(prs, to_delete.keys())

    out = save(prs)
    final = analyze(load(out))
    return out, change_log, problems + attention_items(final, report_type, jira_info)


format = format_deck  # noqa: A001 - the spec's public name


# ---------------------------------------------------------------- attention list

def estimated_table_height(table) -> int:
    """Rendered height (EMU) once long cell text wraps - the stored row
    heights are only minimums, so a table of long asset names can grow down
    over whatever sits below it."""
    total = 0
    for row in table.rows:
        row_height = int(row.height)
        for cell, column in zip(row.cells, table.columns):
            sizes = [r.font.size.pt for p in cell.text_frame.paragraphs for r in p.runs if r.font.size]
            size = max(sizes) if sizes else 12.0
            per_line = max(1, int((int(column.width) - 182880) / (size * CHAR_WIDTH_EM * 12700)))
            lines = sum(wrapped_lines(line, per_line) for line in (cell.text or " ").splitlines() or [" "])
            row_height = max(row_height, int(lines * size * 1.2 * 12700) + 91440)
        total += row_height
    return total


def _overlapping_tables(info: SlideInfo) -> bool:
    frames = sorted((shape for shape, _rows in info.tables if is_top_level(shape)), key=lambda s: int(s.top))
    for i, upper in enumerate(frames):
        bottom = int(upper.top) + estimated_table_height(upper.table)
        for lower in frames[i + 1:]:
            side_by_side = (int(lower.left) >= int(upper.left) + int(upper.width)
                            or int(upper.left) >= int(lower.left) + int(lower.width))
            if not side_by_side and bottom > int(lower.top):
                return True
    return False


def _takeaway_text(info: SlideInfo) -> str:
    shape = info.text_shape("key takeaways")
    return norm_text(shape.text_frame.text) if shape is not None else ""


def attention_items(deck: DeckInfo, report_type: str | None, jira_info: dict | None = None) -> list[AttentionItem]:
    """Things the tool can't do or can't be sure about - shown after Format."""
    jira_info = jira_info or {}
    items: list[AttentionItem] = []

    def add(info: SlideInfo | None, message: str) -> None:
        items.append(AttentionItem(info.number if info else None, info.label if info else "", message))

    if report_type is None:
        add(None, "Report type unknown - pick one so pacing units and CTV handling are right.")
    for info, shape, rows, cols in pacing_tables(deck):
        for r in data_rows(rows):
            if row_unit(rows[r][cols["campaign"]], rows[r], cols, deck, report_type) is None:
                add(info, f"Couldn't tell whether '{norm_text(rows[r][cols['campaign']])}' is Imps or Leads.")
    for info in deck.slides:
        takeaway = _takeaway_text(info)
        if info.kind == "agenda":
            add(info, "Check the Agenda still matches the slides in the deck.")
        elif info.kind == "content_insights" and any(len(rows) > 1 for _s, rows in info.tables):
            add(info, "Add the asset preview thumbnails.")
        elif info.kind == "creative_sets" and info.has_text("this slide will not be populated"):
            add(info, "Creative Sets still has the template example - pull the report and add the insights.")
        elif info.kind in ("top_accounts_cs", "top_accounts") and info.has_text("add in logos"):
            add(info, "Add the top account logos.")
        elif info.kind == "halo" and " X " in f" {takeaway} ":
            add(info, "Halo Effect takeaway still has the X placeholder.")
        elif info.kind == "recommended_actions":
            add(info, "Write the recommended actions.")
        elif info.kind == "key_call_outs":
            add(info, "Review the Key Call Outs text.")
        elif info.kind == "audience_reach" and takeaway and "% of leads" in takeaway and not any(
                ch.isdigit() for ch in takeaway.split("% of leads")[0]):
            add(info, "Audience Reach takeaway has no lead % - write this takeaway by hand.")
        elif info.kind == "industry_insights" and "(% of total)" in takeaway:
            add(info, "Industry Insights takeaway has blank numbers.")
        if info.kind == "thank_you" and (info.has_text("owner name") or info.has_text("<ml team member name>")):
            add(info, "Thank You page still has placeholder owner details (missing from the Jira ticket?).")
        if info.has_text("to be filled by csm"):
            add(info, "A 'To be filled by CSM team' placeholder is still on this slide.")
        if info.has_text("error:"):
            add(info, "Slide still shows an ERROR value from the platform.")
        if len(info.tables) > 1 and _overlapping_tables(info):
            add(info, "Tables overlap once their text wraps - move or shrink them.")
        shape = info.text_shape("key takeaways")
        if shape is not None and int(shape.top) + int(shape.height) > deck.slide_height:
            add(info, "Key Takeaways box runs off the bottom of the slide - shorten or resize it.")
    return items
