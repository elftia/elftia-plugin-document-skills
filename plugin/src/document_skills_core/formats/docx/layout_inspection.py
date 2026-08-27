"""Deterministic page and OOXML layout checks over real render evidence."""

from typing import Any

from document_skills_core.formats.pptx.png_compare import decode_png

from .constants import qn
from .formatting_inspection import project_formatting
from .mapping import document_stories
from .package import OpcPackage
from .semantic_nodes import semantic_node_for

_EMU_PER_TWIP = 635


def inspect_rendered_layout(
    source: Any,
    pages: list[dict[str, Any]],
    *,
    dpi: int,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    page_metrics = []
    for page in pages:
        width, height, rgba = decode_png(page["payload"])
        metrics = _page_metrics(rgba, width, height)
        page_metrics.append(
            {
                "page": page["source_page"],
                "dimensions_px": {"width": width, "height": height},
                **metrics,
            }
        )
        expected = page["dimensions_points"]
        expected_width = round(expected["width"] * dpi / 72)
        expected_height = round(expected["height"] * dpi / 72)
        if abs(width - expected_width) > 3 or abs(height - expected_height) > 3:
            findings.append(
                _finding(
                    "DOCX_LAYOUT_PAGE_GEOMETRY_MISMATCH",
                    "error",
                    page["source_page"],
                    None,
                    {
                        "actual_px": {"width": width, "height": height},
                        "expected_px": {
                            "width": expected_width,
                            "height": expected_height,
                        },
                    },
                    "Render again with the fixed profile and verify page size.",
                )
            )
        if metrics["blank"]:
            findings.append(
                _finding(
                    "DOCX_LAYOUT_BLANK_PAGE",
                    "warning",
                    page["source_page"],
                    None,
                    {"non_white_ratio": metrics["non_white_ratio"]},
                    "Review page and section breaks around this page.",
                )
            )
        elif metrics["non_white_ratio"] < 0.0005:
            findings.append(
                _finding(
                    "DOCX_LAYOUT_EXCESSIVE_WHITESPACE",
                    "warning",
                    page["source_page"],
                    None,
                    {"non_white_ratio": metrics["non_white_ratio"]},
                    "Review paragraph spacing and forced breaks on this page.",
                )
            )
        if metrics["touches_page_edge"]:
            findings.append(
                _finding(
                    "DOCX_LAYOUT_CONTENT_NEAR_PAGE_EDGE",
                    "warning",
                    page["source_page"],
                    None,
                    {"content_bbox_px": metrics["content_bbox_px"]},
                    "Check page margins and oversized positioned objects.",
                )
            )
    package = OpcPackage.open(source)
    stories = document_stories(package, include_headers_footers=True)
    findings.extend(_table_findings(package))
    findings.extend(_object_width_findings(package))
    direct = project_formatting(package, stories)["direct_formatting"]
    if direct["paragraph_count"] or direct["run_count"]:
        findings.append(
            _finding(
                "DOCX_LAYOUT_DIRECT_FORMATTING_DRIFT",
                "info",
                None,
                None,
                {
                    "paragraph_count": direct["paragraph_count"],
                    "run_count": direct["run_count"],
                },
                "Prefer named styles for repeatable agent corrections.",
            )
        )
    severities = {item["severity"] for item in findings}
    status = (
        "fail"
        if "error" in severities
        else "review_required" if severities & {"warning", "info"} else "pass"
    )
    return {
        "profile": {"id": "professional-v1", "version": "1.0"},
        "status": status,
        "findings": findings,
        "page_metrics": page_metrics,
        "degradations": [
            {
                "code": "DOCX_LAYOUT_NODE_PAGE_MAPPING_UNAVAILABLE",
                "message": (
                    "LibreOffice raster evidence does not expose a stable mapping "
                    "from every semantic node to a rendered page."
                ),
            }
        ],
    }


def _page_metrics(rgba: bytes, width: int, height: int) -> dict[str, Any]:
    left, top, right, bottom = width, height, -1, -1
    non_white = 0
    for index in range(width * height):
        offset = index * 4
        red, green, blue, alpha = rgba[offset : offset + 4]
        if alpha <= 8 or min(red, green, blue) >= 245:
            continue
        non_white += 1
        x, y = index % width, index // width
        left, top = min(left, x), min(top, y)
        right, bottom = max(right, x), max(bottom, y)
    blank = non_white == 0
    bbox = None if blank else {"left": left, "top": top, "right": right, "bottom": bottom}
    edge_x = max(2, round(width * 0.005))
    edge_y = max(2, round(height * 0.005))
    touches = not blank and (
        left <= edge_x
        or top <= edge_y
        or right >= width - edge_x - 1
        or bottom >= height - edge_y - 1
    )
    return {
        "blank": blank,
        "non_white_ratio": round(non_white / (width * height), 6),
        "content_bbox_px": bbox,
        "touches_page_edge": touches,
    }


def _table_findings(package: OpcPackage) -> list[dict[str, Any]]:
    result = []
    root = package.xml("word/document.xml")
    for table in root.iter(qn("w", "tbl")):
        first_row = table.find(qn("w", "tr"))
        header = (
            first_row.find(f"./{qn('w', 'trPr')}/{qn('w', 'tblHeader')}")
            if first_row is not None
            else None
        )
        if first_row is not None and header is None:
            semantic = semantic_node_for(table)
            result.append(
                _finding(
                    "DOCX_LAYOUT_TABLE_HEADER_NOT_REPEATABLE",
                    "warning",
                    None,
                    semantic.node_id if semantic is not None else None,
                    {"first_row_present": True, "tbl_header_present": False},
                    "Mark the first table row to repeat across page breaks.",
                )
            )
    return result


def _object_width_findings(package: OpcPackage) -> list[dict[str, Any]]:
    root = package.xml("word/document.xml")
    section = next(root.iter(qn("w", "sectPr")), None)
    if section is None:
        return []
    size = section.find(qn("w", "pgSz"))
    margins = section.find(qn("w", "pgMar"))
    if size is None or margins is None:
        return []
    try:
        page_width = int(size.attrib[qn("w", "w")])
        left = int(margins.attrib[qn("w", "left")])
        right = int(margins.attrib[qn("w", "right")])
    except (KeyError, ValueError):
        return []
    available_emu = (page_width - left - right) * _EMU_PER_TWIP
    result = []
    for paragraph in root.iter(qn("w", "p")):
        semantic = semantic_node_for(paragraph)
        for extent in paragraph.iter(qn("wp", "extent")):
            try:
                width = int(extent.attrib["cx"])
            except (KeyError, ValueError):
                continue
            if width > available_emu:
                result.append(
                    _finding(
                        "DOCX_LAYOUT_OBJECT_EXCEEDS_TEXT_WIDTH",
                        "error",
                        None,
                        semantic.node_id if semantic is not None else None,
                        {"width_emu": width, "available_width_emu": available_emu},
                        "Reduce the object width or use an appropriate section orientation.",
                    )
                )
    return result


def _finding(
    code: str,
    severity: str,
    page: int | None,
    node_id: str | None,
    evidence: dict[str, Any],
    suggestion: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "page": page,
        "semantic_node_id": node_id,
        "evidence": evidence,
        "suggestion": suggestion,
    }
