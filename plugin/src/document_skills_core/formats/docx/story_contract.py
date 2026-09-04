"""Bounded parsing and OOXML emission for DOCX headers and footers."""

from typing import Any
from xml.etree.ElementTree import Element, SubElement

from .constants import qn
from .contracts import _exact_keys, _invalid, _text
from .xml_utils import paragraph, set_text, text_run, xml_bytes

_ALIGNMENTS = {"center", "left", "right"}
_FIELDS = {"PAGE", "NUMPAGES"}


def parse_story(value: Any, field: str) -> str | dict[str, Any] | None:
    """Parse a legacy string or a bounded structured story."""

    if value is None:
        return None
    if type(value) is str:
        return _text(value, field) or None
    if type(value) is not dict:
        _invalid("Header/footer must be text or a structured story.", field=field)
    _exact_keys(value, {"paragraphs"})
    paragraphs = value.get("paragraphs")
    if type(paragraphs) is not list or not 1 <= len(paragraphs) <= 16:
        _invalid("Structured stories require 1 to 16 paragraphs.", field=field)
    parsed_paragraphs = []
    for paragraph_index, item in enumerate(paragraphs):
        paragraph_field = f"{field}.paragraphs.{paragraph_index}"
        if type(item) is not dict:
            _invalid("Structured story paragraphs must be objects.", field=paragraph_field)
        _exact_keys(item, {"alignment", "runs"})
        alignment = item.get("alignment", "left")
        if alignment not in _ALIGNMENTS:
            _invalid("Story alignment must be left, center, or right.", field=f"{paragraph_field}.alignment")
        runs = item.get("runs")
        if type(runs) is not list or not 1 <= len(runs) <= 64:
            _invalid("Structured story paragraphs require 1 to 64 runs.", field=f"{paragraph_field}.runs")
        parsed_runs = []
        for run_index, run in enumerate(runs):
            run_field = f"{paragraph_field}.runs.{run_index}"
            if type(run) is not dict or len(run) != 1:
                _invalid("Each story run must contain exactly text or field.", field=run_field)
            if "text" in run:
                parsed_runs.append({"text": _text(run["text"], f"{run_field}.text")})
                continue
            if "field" not in run or run["field"] not in _FIELDS:
                _invalid("Story fields are restricted to PAGE or NUMPAGES.", field=f"{run_field}.field")
            parsed_runs.append({"field": run["field"]})
        parsed_paragraphs.append({"alignment": alignment, "runs": parsed_runs})
    return {"paragraphs": parsed_paragraphs}


def render_story(kind: str, story: str | dict[str, Any]) -> bytes:
    """Emit a legacy story byte-for-byte compatibly or structured safe fields."""

    root = Element(qn("w", kind))
    if type(story) is str:
        root.append(paragraph(story))
        return xml_bytes(root)
    for item in story["paragraphs"]:
        paragraph_node = SubElement(root, qn("w", "p"))
        properties = SubElement(paragraph_node, qn("w", "pPr"))
        SubElement(properties, qn("w", "jc"), {qn("w", "val"): item["alignment"]})
        for run in item["runs"]:
            if "text" in run:
                text_run(paragraph_node, run["text"])
            else:
                _append_field(paragraph_node, run["field"])
    return xml_bytes(root)


def _append_field(paragraph_node: Element, field: str) -> None:
    begin = SubElement(paragraph_node, qn("w", "r"))
    SubElement(begin, qn("w", "fldChar"), {qn("w", "fldCharType"): "begin"})
    instruction_run = SubElement(paragraph_node, qn("w", "r"))
    instruction = SubElement(instruction_run, qn("w", "instrText"))
    set_text(instruction, f" {field} ")
    separate = SubElement(paragraph_node, qn("w", "r"))
    SubElement(separate, qn("w", "fldChar"), {qn("w", "fldCharType"): "separate"})
    text_run(paragraph_node, "1")
    end = SubElement(paragraph_node, qn("w", "r"))
    SubElement(end, qn("w", "fldChar"), {qn("w", "fldCharType"): "end"})


__all__ = ["parse_story", "render_story"]
