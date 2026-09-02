"""Internal strict-authoring assertions run before a DOCX candidate is written."""

from typing import Any
import re
from xml.etree.ElementTree import fromstring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn


def assert_authoring_parts(parts: dict[str, bytes]) -> None:
    _assert_relationship_serialization(parts)
    document = fromstring(parts["word/document.xml"])
    _assert_tables(document)
    _assert_style_references(document, fromstring(parts["word/styles.xml"]))
    for name in ("word/header1.xml", "word/footer1.xml"):
        payload = parts.get(name)
        if payload is not None:
            _assert_story(fromstring(payload), name)


def _assert_relationship_serialization(parts: dict[str, bytes]) -> None:
    for name in ("_rels/.rels", "word/_rels/document.xml.rels"):
        payload = parts[name]
        match = re.search(br"<([A-Za-z_][A-Za-z0-9_.-]*:)?Relationships(?:\s|>)", payload)
        if match is None or match.group(1) is not None:
            _failed("relationship-namespace-prefix", part=name)


def _assert_tables(document: Any) -> None:
    for index, table in enumerate(document.iter(qn("w", "tbl"))):
        rows = list(table.findall(qn("w", "tr")))
        columns = len(rows[0].findall(qn("w", "tc"))) if rows else 0
        if not rows or columns == 0 or any(len(row.findall(qn("w", "tc"))) != columns for row in rows):
            _failed("table-cardinality", table_index=index)
        grid = table.find(qn("w", "tblGrid"))
        widths = [] if grid is None else [
            _positive(item.attrib.get(qn("w", "w")))
            for item in grid.findall(qn("w", "gridCol"))
        ]
        if len(widths) != columns or not all(widths):
            _failed("table-grid", table_index=index)
        table_width = table.find(f"./{qn('w', 'tblPr')}/{qn('w', 'tblW')}")
        if table_width is None or _positive(table_width.attrib.get(qn("w", "w"))) != sum(widths):
            _failed("table-width", table_index=index)
        cell_widths = [
            _positive(width.attrib.get(qn("w", "w")))
            for cell in table.iter(qn("w", "tc"))
            if (width := cell.find(f"./{qn('w', 'tcPr')}/{qn('w', 'tcW')}")) is not None
        ]
        expected = widths * len(rows)
        if cell_widths != expected:
            _failed("table-cell-widths", table_index=index)


def _assert_story(story: Any, part: str) -> None:
    instructions = [
        " ".join((node.text or "").split()).upper()
        for node in story.iter(qn("w", "instrText"))
    ]
    if any(item not in {"PAGE", "NUMPAGES"} for item in instructions):
        _failed("story-field-instruction", part=part)
    field_types = [
        node.attrib.get(qn("w", "fldCharType"))
        for node in story.iter(qn("w", "fldChar"))
    ]
    if field_types and field_types != [
        item
        for _instruction in instructions
        for item in ("begin", "separate", "end")
    ]:
        _failed("story-field-sequence", part=part)


def _assert_style_references(document: Any, styles: Any) -> None:
    available = {
        node.attrib.get(qn("w", "styleId"))
        for node in styles.findall(qn("w", "style"))
    }
    used = {
        node.attrib.get(qn("w", "val"))
        for name in ("pStyle", "tblStyle")
        for node in document.iter(qn("w", name))
    }
    missing = sorted(item for item in used if item and item not in available)
    if missing:
        _failed("style-reference", missing=missing)


def _positive(value: str | None) -> int:
    try:
        parsed = int(value or "0")
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def _failed(reason: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Generated DOCX failed strict authoring-format assertions.",
        details={"diagnostic": "DS_DOCX_AUTHORING_FORMAT_INVALID", "reason": reason, **details},
    )


__all__ = ["assert_authoring_parts"]
