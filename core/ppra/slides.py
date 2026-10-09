"""Slide duplication for python-pptx, which has no copy-slide API.

The copy gets the source's layout, background and every shape, and its own
relationships: pictures and media point at the same (read-only) parts,
while charts get their own chart part and embedded workbook, since
PowerPoint expects each chart part to belong to one slide. The new slide is
moved to the requested position and added to the source's section, so the
file opens without a repair prompt.
"""
from __future__ import annotations

import copy
import re

from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import Part
from pptx.oxml.ns import qn
from pptx.parts.chart import ChartPart
from pptx.parts.embeddedpackage import EmbeddedXlsxPart

_P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_SKIP_RELS = (RT.SLIDE_LAYOUT, RT.NOTES_SLIDE)
_DIGITS_RE = re.compile(r"\d*(\.\w+)$")


def _remap_rids(element, rid_map: dict) -> None:
    for el in element.iter():
        for attr, value in list(el.attrib.items()):
            if attr.startswith(f"{{{_R_NS}}}") and value in rid_map:
                el.set(attr, rid_map[value])


def _copy_chart_part(src_part, package):
    partname = package.next_partname(ChartPart.partname_template)
    new_part = ChartPart.load(partname, src_part.content_type, package, src_part.blob)
    rid_map = {}
    for rid, rel in src_part.rels.items():
        if rel.is_external:
            rid_map[rid] = new_part.relate_to(rel.target_ref, rel.reltype, is_external=True)
        elif isinstance(rel.target_part, EmbeddedXlsxPart):
            rid_map[rid] = new_part.relate_to(EmbeddedXlsxPart.new(rel.target_part.blob, package), rel.reltype)
        else:  # chart style / colour parts: the copy gets its own too
            target = rel.target_part
            tmpl = _DIGITS_RE.sub(r"%d\1", str(target.partname))
            clone = Part.load(package.next_partname(tmpl), target.content_type, package, target.blob)
            rid_map[rid] = new_part.relate_to(clone, rel.reltype)
    _remap_rids(new_part._element, rid_map)
    return new_part


def duplicate_slide(prs, src_index: int, dest_index: int):
    """Copy slide src_index to position dest_index (0-based, in the deck as
    it is after the copy); returns the new slide."""
    src = prs.slides[src_index]
    dst = prs.slides.add_slide(src.slide_layout)
    try:
        _fill_copy(prs, src, dst, src_index, dest_index)
    except Exception:
        # Never leave a half-built blank slide at the end of the deck.
        entry = next(e for e in prs.slides._sldIdLst if int(e.get("id")) == dst.slide_id)
        prs.slides._sldIdLst.remove(entry)
        prs.part.drop_rel(entry.rId)
        raise
    return dst


def _fill_copy(prs, src, dst, src_index: int, dest_index: int) -> None:
    for shape in list(dst.shapes):  # the layout's empty placeholders
        shape._element.getparent().remove(shape._element)

    rid_map = {}
    for rid, rel in src.part.rels.items():
        if rel.reltype in _SKIP_RELS:
            continue
        if rel.is_external:
            rid_map[rid] = dst.part.relate_to(rel.target_ref, rel.reltype, is_external=True)
        elif rel.reltype == RT.CHART:
            rid_map[rid] = dst.part.relate_to(_copy_chart_part(rel.target_part, prs.part.package), rel.reltype)
        else:
            rid_map[rid] = dst.part.relate_to(rel.target_part, rel.reltype)

    src_csld, dst_csld = src._element.cSld, dst._element.cSld
    bg = src_csld.find(qn("p:bg"))
    if bg is not None:
        dst_csld.insert(0, copy.deepcopy(bg))
    dst_tree = dst.shapes._spTree
    for child in src.shapes._spTree:
        if child.tag in (qn("p:nvGrpSpPr"), qn("p:grpSpPr")):
            continue
        dst_tree.append(copy.deepcopy(child))
    _remap_rids(dst._element.cSld, rid_map)
    # Colour-map override and transitions travel with the slide too.
    for tag in ("p:clrMapOvr", "p:transition", "p:timing"):
        el = src._element.find(qn(tag))
        old = dst._element.find(qn(tag))
        if old is not None:
            dst._element.remove(old)
        if el is not None:
            dst._element.append(copy.deepcopy(el))

    sld_id_lst = prs.slides._sldIdLst
    entries = list(sld_id_lst)
    src_id, new_entry = entries[src_index].get("id"), entries[-1]
    sld_id_lst.remove(new_entry)
    sld_id_lst.insert(dest_index, new_entry)
    _add_to_section(prs, src_id, dest_index, new_entry.get("id"))


def _add_to_section(prs, src_id: str, dest_index: int, new_id: str) -> None:
    """Put the new slide in the source slide's section, right after the slide
    that now precedes it (the source, or an earlier copy of it)."""
    prev_id = list(prs.slides._sldIdLst)[dest_index - 1].get("id") if dest_index else src_id
    for ref in prs.part._element.iter(f"{{{_P14_NS}}}sldId"):
        if ref.get("id") == prev_id:
            ref.addnext(ref.makeelement(ref.tag, {"id": new_id}))
            return
