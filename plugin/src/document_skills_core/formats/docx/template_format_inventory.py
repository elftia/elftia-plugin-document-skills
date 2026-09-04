"""Bounded, content-free inventory of material DOCX reference formatting."""

from collections import Counter
from hashlib import sha256
from typing import Any

from .constants import qn
from .mapping import document_stories, iter_paragraphs, paragraph_style
from .package import OpcPackage

_MAX_FORMATS = 256
_MAX_STORY_PARAGRAPHS = 16


def inspect_format_features(package: OpcPackage) -> dict[str, Any]:
    run_formats: Counter[tuple[tuple[str, Any], ...]] = Counter()
    paragraph_formats: Counter[tuple[tuple[str, Any], ...]] = Counter()
    story_inventory = []
    story_overflows = []
    for story in document_stories(package):
        fields = []
        alignments = Counter()
        story_paragraphs = []
        parents = {
            id(child): parent
            for parent in story.root.iter()
            for child in parent
        }
        for paragraph in iter_paragraphs(story.root):
            style_id = paragraph_style(paragraph)
            location = _paragraph_location(paragraph, story.kind, parents)
            paragraph_format = _paragraph_format(paragraph)
            if paragraph_format:
                paragraph_format.update(
                    {"paragraph_style": style_id or "", "location": location}
                )
                paragraph_formats[tuple(sorted(paragraph_format.items()))] += 1
            alignment = paragraph_format.get("alignment")
            if alignment:
                alignments[alignment] += 1
            story_runs = []
            field_active = False
            for run in paragraph.iter(qn("w", "r")):
                run_format = _run_format(run)
                if run_format:
                    run_format.update(
                        {"paragraph_style": style_id or "", "location": location}
                    )
                    run_formats[tuple(sorted(run_format.items()))] += 1
                field_types = [
                    item.attrib.get(qn("w", "fldCharType"))
                    for item in run.iter(qn("w", "fldChar"))
                ]
                if "begin" in field_types:
                    field_active = True
                text = "".join(item.text or "" for item in run.iter(qn("w", "t")))
                instruction = next(run.iter(qn("w", "instrText")), None)
                if instruction is not None:
                    normalized = " ".join((instruction.text or "").split()).upper()
                    if normalized:
                        story_runs.append({"field": normalized})
                elif text and not field_active:
                    encoded = text.encode("utf-8", errors="strict")
                    story_runs.append(
                        {
                            "text_sha256": sha256(encoded).hexdigest(),
                            "text_bytes": len(encoded),
                        }
                    )
                if "end" in field_types:
                    field_active = False
            for instruction in paragraph.iter(qn("w", "instrText")):
                normalized = " ".join((instruction.text or "").split()).upper()
                if normalized:
                    fields.append(
                        {
                            "instruction": normalized,
                            "allowlisted": normalized in {"PAGE", "NUMPAGES"},
                        }
                    )
            if story.kind in {"header", "footer"}:
                story_paragraphs.append(
                    {
                        "alignment": alignment or "left",
                        "runs": story_runs,
                    }
                )
        if story.kind in {"header", "footer"}:
            bounded_fields, fields_truncated = _bounded_records(fields, _MAX_FORMATS)
            bounded_paragraphs, paragraphs_truncated = _bounded_records(
                story_paragraphs,
                _MAX_STORY_PARAGRAPHS,
            )
            if fields_truncated:
                story_overflows.append(
                    _overflow(
                        "story-field-inventory-overflow",
                        _MAX_FORMATS,
                        part=story.part,
                    )
                )
            if paragraphs_truncated:
                story_overflows.append(
                    _overflow(
                        f"{story.kind}-paragraph-inventory-overflow",
                        _MAX_STORY_PARAGRAPHS,
                        part=story.part,
                    )
                )
            story_inventory.append(
                {
                    "kind": story.kind,
                    "part": story.part,
                    "alignments": dict(sorted(alignments.items())),
                    "field_count": len(fields),
                    "fields_truncated": fields_truncated,
                    "fields": bounded_fields,
                    "paragraph_count": len(story_paragraphs),
                    "paragraphs_truncated": paragraphs_truncated,
                    "paragraphs": bounded_paragraphs,
                }
            )
    tables, table_overflows = _table_inventory(package)
    direct_run_formats, run_formats_truncated = _counter_records(run_formats)
    direct_paragraph_formats, paragraph_formats_truncated = _counter_records(
        paragraph_formats
    )
    format_overflows = []
    if run_formats_truncated:
        format_overflows.append(
            _overflow("direct-run-format-inventory-overflow", _MAX_FORMATS)
        )
    if paragraph_formats_truncated:
        format_overflows.append(
            _overflow("direct-paragraph-format-inventory-overflow", _MAX_FORMATS)
        )
    return {
        "direct_run_formats": direct_run_formats,
        "direct_paragraph_formats": direct_paragraph_formats,
        "tables": tables,
        "stories": story_inventory,
        "overflows": format_overflows + story_overflows + table_overflows,
    }


def mode_compatibility(
    inventory: dict[str, Any],
    *,
    template_syntax_supported: bool,
    document_spec_styles_supported: bool,
) -> dict[str, dict[str, Any]]:
    table_defects = [
        item["index"]
        for item in inventory["tables"]
        if not item["grid_positive"] or not item["cell_widths_complete"]
    ]
    unsafe_fields = [
        field["instruction"]
        for story in inventory["stories"]
        for field in story["fields"]
        if not field["allowlisted"]
    ]
    inventory_overflow_reasons = sorted(
        {item["reason"] for item in inventory.get("overflows", [])}
    )
    template_reasons = []
    if not template_syntax_supported:
        template_reasons.append("token-syntax-is-not-executable")
    if table_defects:
        template_reasons.append("source-table-geometry-is-not-strict-consumer-valid")
    document_spec_reasons = []
    if not document_spec_styles_supported:
        document_spec_reasons.append("style-dependencies-are-not-representable")
    if inventory["direct_run_formats"]:
        document_spec_reasons.append("direct-run-format-requires-explicit-authoring-map")
    if inventory["direct_paragraph_formats"]:
        document_spec_reasons.append("direct-paragraph-format-requires-explicit-authoring-map")
    if inventory["tables"]:
        document_spec_reasons.append("table-geometry-and-borders-require-explicit-authoring-map")
    if any(story["fields"] for story in inventory["stories"]):
        document_spec_reasons.append("story-fields-require-explicit-authoring-map")
    if unsafe_fields:
        document_spec_reasons.append("story-field-is-not-allowlisted")
    document_spec_reasons.extend(inventory_overflow_reasons)
    template_status = (
        "incompatible"
        if not template_syntax_supported
        else "degraded"
        if template_reasons
        else "compatible"
    )
    document_spec_status = (
        "incompatible"
        if not document_spec_styles_supported
        or unsafe_fields
        or inventory_overflow_reasons
        else "degraded"
        if document_spec_reasons
        else "compatible"
    )
    return {
        "template": {
            "status": template_status,
            "preservation": "base-copy",
            "reasons": template_reasons,
            "table_indexes": table_defects,
        },
        "document-spec": {
            "status": document_spec_status,
            "preservation": "reconstruction",
            "reasons": document_spec_reasons,
            "unsupported_fields": sorted(set(unsafe_fields)),
        },
    }


def _run_format(run: Any) -> dict[str, Any]:
    properties = run.find(qn("w", "rPr"))
    if properties is None:
        return {}
    fonts = properties.find(qn("w", "rFonts"))
    result = {}
    if fonts is not None:
        for key in ("ascii", "hAnsi", "eastAsia", "cs"):
            value = fonts.attrib.get(qn("w", key))
            if value:
                result[f"font_{key}"] = value
    for key in ("sz", "szCs"):
        node = properties.find(qn("w", key))
        if node is not None and (value := node.attrib.get(qn("w", "val"))):
            result[key] = value
    for key in ("b", "i"):
        if properties.find(qn("w", key)) is not None:
            result[{"b": "bold", "i": "italic"}[key]] = True
    return result


def _paragraph_format(paragraph: Any) -> dict[str, Any]:
    properties = paragraph.find(qn("w", "pPr"))
    if properties is None:
        return {}
    result = {}
    alignment = properties.find(qn("w", "jc"))
    if alignment is not None and (value := alignment.attrib.get(qn("w", "val"))):
        result["alignment"] = value
    indentation = properties.find(qn("w", "ind"))
    if indentation is not None:
        for key in ("left", "right", "firstLine", "firstLineChars", "hanging", "hangingChars"):
            if (value := indentation.attrib.get(qn("w", key))) is not None:
                result[f"indent_{key}"] = value
    spacing = properties.find(qn("w", "spacing"))
    if spacing is not None:
        for key in ("before", "after", "line", "lineRule"):
            if (value := spacing.attrib.get(qn("w", key))) is not None:
                result[f"spacing_{key}"] = value
    return result


def _table_inventory(
    package: OpcPackage,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    document = package.xml("word/document.xml")
    result = []
    for index, table in enumerate(document.iter(qn("w", "tbl"))):
        rows = list(table.findall(qn("w", "tr")))
        column_count = max(
            (len(row.findall(qn("w", "tc"))) for row in rows),
            default=0,
        )
        grid = table.find(qn("w", "tblGrid"))
        widths = [] if grid is None else [
            _positive_int(item.attrib.get(qn("w", "w")))
            for item in grid.findall(qn("w", "gridCol"))
        ]
        cell_widths = [
            _positive_int(width.attrib.get(qn("w", "w")))
            for cell in table.iter(qn("w", "tc"))
            if (width := cell.find(f"./{qn('w', 'tcPr')}/{qn('w', 'tcW')}")) is not None
        ]
        table_width = table.find(f"./{qn('w', 'tblPr')}/{qn('w', 'tblW')}")
        layout = table.find(f"./{qn('w', 'tblPr')}/{qn('w', 'tblLayout')}")
        bounded_cell_widths, cell_widths_truncated = _bounded_records(
            cell_widths,
            _MAX_FORMATS,
        )
        result.append(
            {
                "index": index,
                "rows": len(rows),
                "columns": column_count,
                "grid_widths_twips": widths,
                "grid_positive": len(widths) == column_count and all(widths),
                "table_width_twips": _positive_int(
                    None if table_width is None else table_width.attrib.get(qn("w", "w"))
                ),
                "layout": None if layout is None else layout.attrib.get(qn("w", "type")),
                "cell_widths_complete": len(cell_widths) == len(rows) * column_count and all(cell_widths),
                "cell_width_count": len(cell_widths),
                "cell_widths_truncated": cell_widths_truncated,
                "cell_widths_twips": bounded_cell_widths,
                "borders": {
                    **_borders(table),
                    **(
                        {"header_bottom": header_bottom}
                        if (header_bottom := _header_bottom(table)) is not None
                        else {}
                    ),
                },
            }
        )
    bounded_tables, tables_truncated = _bounded_records(result, _MAX_FORMATS)
    overflows = [
        _overflow(
            "table-cell-width-inventory-overflow",
            _MAX_FORMATS,
            table_index=item["index"],
        )
        for item in bounded_tables
        if item["cell_widths_truncated"]
    ]
    if tables_truncated:
        overflows.append(_overflow("table-inventory-overflow", _MAX_FORMATS))
    return bounded_tables, overflows


def _borders(table: Any) -> dict[str, dict[str, str]]:
    root = table.find(f"./{qn('w', 'tblPr')}/{qn('w', 'tblBorders')}")
    if root is None:
        return {}
    result = {}
    for name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = root.find(qn("w", name))
        if node is not None:
            result[name] = {
                key: node.attrib.get(qn("w", key), "")
                for key in ("val", "sz", "color", "space")
            }
    return result


def _header_bottom(table: Any) -> dict[str, str] | None:
    first_row = table.find(qn("w", "tr"))
    if first_row is None:
        return None
    borders = []
    for cell in first_row.findall(qn("w", "tc")):
        node = cell.find(
            f"./{qn('w', 'tcPr')}/{qn('w', 'tcBorders')}/{qn('w', 'bottom')}"
        )
        if node is None:
            return None
        borders.append(
            {
                key: node.attrib.get(qn("w", key), "")
                for key in ("val", "sz", "color", "space")
            }
        )
    if not borders or any(item != borders[0] for item in borders[1:]):
        return None
    return borders[0]


def _paragraph_location(
    paragraph: Any,
    story_kind: str,
    parents: dict[int, Any],
) -> str:
    if story_kind != "body":
        return story_kind
    current = paragraph
    while (parent := parents.get(id(current))) is not None:
        if parent.tag == qn("w", "tc"):
            return "table"
        current = parent
    return "body"


def _counter_records(
    counter: Counter[tuple[tuple[str, Any], ...]],
) -> tuple[list[dict[str, Any]], bool]:
    bounded, truncated = _bounded_records(sorted(counter.items()), _MAX_FORMATS)
    return [
        {"format": dict(items), "occurrences": count}
        for items, count in bounded
    ], truncated


def _bounded_records(items: list[Any], limit: int) -> tuple[list[Any], bool]:
    observed = items[: limit + 1]
    return observed[:limit], len(observed) > limit


def _overflow(reason: str, limit: int, **context: Any) -> dict[str, Any]:
    return {
        "reason": reason,
        "limit": limit,
        "observed_at_least": limit + 1,
        **context,
    }


def _positive_int(value: str | None) -> int:
    try:
        parsed = int(value or "0")
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


__all__ = ["inspect_format_features", "mode_compatibility"]
