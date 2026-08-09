"""Deterministic Word content projection for read and inspection."""

from collections import Counter
from typing import Any
from xml.etree.ElementTree import Element

from .constants import REL_HYPERLINK, local_name, qn
from .mapping import (
    Story,
    iter_paragraphs,
    map_paragraph,
    paragraph_numbering,
    paragraph_style,
)
from .package import OpcPackage
from .relationships import relationship_map


def project_story(
    package: OpcPackage,
    story: Story,
    *,
    paragraph_limit: int,
    text_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    relationships = relationship_map(package.relationships, story.part)
    projected = []
    text_count = 0
    truncated = {"paragraphs": False, "text": False}
    for index, paragraph in enumerate(iter_paragraphs(story.root)):
        if len(projected) >= paragraph_limit:
            truncated["paragraphs"] = True
            break
        mapped = map_paragraph(paragraph)
        text = "".join(group.text for group in mapped.groups)
        remaining = text_limit - text_count
        if remaining <= 0:
            truncated["text"] = True
            break
        if len(text) > remaining:
            text = text[:remaining]
            truncated["text"] = True
        text_count += len(text)
        runs = (
            _truncate_runs(mapped.run_summaries, len(text))
            if truncated["text"]
            else mapped.run_summaries
        )
        style = paragraph_style(paragraph)
        numbering = paragraph_numbering(paragraph)
        hyperlinks = []
        for relationship_id in mapped.hyperlink_ids:
            relationship = relationships.get(relationship_id)
            if relationship is None:
                continue
            hyperlinks.append(
                {
                    "relationship_id": relationship_id,
                    "target": relationship.target,
                    "target_mode": relationship.target_mode,
                    "resolved_target": relationship.resolved_target,
                    "type": relationship.relationship_type,
                }
            )
        projected.append(
            {
                "index": index,
                "text": text,
                "style": style,
                "heading_level": _heading_level(style),
                "numbering": numbering,
                "runs": runs,
                "hyperlinks": hyperlinks,
                "protected_text_present": bool(mapped.protected_text),
            }
        )
        if truncated["text"]:
            break
    return projected, truncated


def project_tables(
    root: Element,
    *,
    table_limit: int,
    row_limit: int,
    text_limit: int | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    tables = []
    rows_seen = 0
    text_seen = 0
    truncated = False
    for table_index, table in enumerate(root.iter(qn("w", "tbl"))):
        if len(tables) >= table_limit:
            truncated = True
            break
        style_node = table.find(f"./{qn('w', 'tblPr')}/{qn('w', 'tblStyle')}")
        rows = []
        for row_index, row in enumerate(table.findall(f"./{qn('w', 'tr')}")):
            if rows_seen >= row_limit or (
                text_limit is not None and text_seen >= text_limit
            ):
                truncated = True
                break
            cells = []
            for cell_index, cell in enumerate(row.findall(f"./{qn('w', 'tc')}")):
                paragraphs = []
                for paragraph in cell.iter(qn("w", "p")):
                    mapped = map_paragraph(paragraph)
                    text = "".join(group.text for group in mapped.groups)
                    if text_limit is not None:
                        remaining = text_limit - text_seen
                        if remaining <= 0:
                            truncated = True
                            break
                        if len(text) > remaining:
                            text = text[:remaining]
                            truncated = True
                    text_seen += len(text)
                    paragraphs.append(
                        {
                            "text": text,
                            "style": paragraph_style(paragraph),
                        }
                    )
                    if text_limit is not None and text_seen >= text_limit:
                        break
                grid_span = cell.find(
                    f"./{qn('w', 'tcPr')}/{qn('w', 'gridSpan')}"
                )
                cells.append(
                    {
                        "index": cell_index,
                        "paragraphs": paragraphs,
                        "grid_span": (
                            grid_span.attrib.get(qn("w", "val"))
                            if grid_span is not None
                            else None
                        ),
                    }
                )
                if text_limit is not None and text_seen >= text_limit:
                    break
            rows.append({"index": row_index, "cells": cells})
            rows_seen += 1
            if text_limit is not None and text_seen >= text_limit:
                truncated = True
                break
        tables.append(
            {
                "index": table_index,
                "style": (
                    style_node.attrib.get(qn("w", "val"))
                    if style_node is not None
                    else None
                ),
                "rows": rows,
            }
        )
        if truncated:
            break
    return tables, truncated


def project_images(package: OpcPackage, story: Story) -> list[dict[str, Any]]:
    relationships = relationship_map(package.relationships, story.part)
    images = []
    for drawing in story.root.iter(qn("w", "drawing")):
        for blip in drawing.iter(qn("a", "blip")):
            relationship_id = blip.attrib.get(qn("r", "embed"))
            relationship = relationships.get(relationship_id or "")
            if relationship is None:
                continue
            extent = next(drawing.iter(qn("wp", "extent")), None)
            properties = next(drawing.iter(qn("wp", "docPr")), None)
            target = relationship.resolved_target
            images.append(
                {
                    "source_part": story.part,
                    "relationship_id": relationship_id,
                    "target_part": target,
                    "content_type": package.content_type_for(target or ""),
                    "dimensions_emu": (
                        {"cx": extent.attrib.get("cx"), "cy": extent.attrib.get("cy")}
                        if extent is not None
                        else None
                    ),
                    "alt_text": (
                        properties.attrib.get("descr") if properties is not None else None
                    ),
                }
            )
    return images


def project_sections(package: OpcPackage) -> list[dict[str, Any]]:
    root = package.xml("word/document.xml")
    relationships = relationship_map(package.relationships, "word/document.xml")
    sections = []
    for index, section in enumerate(root.iter(qn("w", "sectPr"))):
        size = section.find(qn("w", "pgSz"))
        margins = section.find(qn("w", "pgMar"))
        section_type = section.find(qn("w", "type"))
        references = []
        for child in section:
            name = local_name(child.tag)
            if name not in {"headerReference", "footerReference"}:
                continue
            relationship_id = child.attrib.get(qn("r", "id"))
            relationship = relationships.get(relationship_id or "")
            references.append(
                {
                    "kind": name.removesuffix("Reference"),
                    "reference_type": child.attrib.get(qn("w", "type"), "default"),
                    "relationship_id": relationship_id,
                    "target_part": (
                        relationship.resolved_target if relationship is not None else None
                    ),
                }
            )
        sections.append(
            {
                "index": index,
                "type": (
                    section_type.attrib.get(qn("w", "val"), "continuous")
                    if section_type is not None
                    else "continuous"
                ),
                "orientation": (
                    size.attrib.get(qn("w", "orient"), "portrait")
                    if size is not None
                    else None
                ),
                "page_size": _attributes(size, {"h", "w"}),
                "margins": _attributes(
                    margins,
                    {"bottom", "footer", "gutter", "header", "left", "right", "top"},
                ),
                "references": references,
            }
        )
    return sections


def feature_counts(package: OpcPackage) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for name, payload in package.parts.items():
        if not name.endswith((".xml", ".rels")):
            continue
        root = package.xml(name)
        for node in root.iter():
            local = local_name(node.tag)
            if local in {"comment", "commentRangeEnd", "commentRangeStart", "commentReference"}:
                counts["comments"] += 1
            elif local in {"del", "ins", "moveFrom", "moveTo"}:
                counts["revisions"] += 1
            elif local in {"fldChar", "fldSimple", "instrText"}:
                counts["fields"] += 1
            elif local == "sectPr":
                counts["sections"] += 1
    return {key: counts.get(key, 0) for key in ("comments", "fields", "revisions", "sections")}


def _heading_level(style: str | None) -> int | None:
    if not style:
        return None
    folded = style.casefold().replace(" ", "")
    if folded.startswith("heading") and folded[7:].isdigit():
        return int(folded[7:])
    return None


def _attributes(node: Element | None, names: set[str]) -> dict[str, str] | None:
    if node is None:
        return None
    return {
        name: node.attrib[qn("w", name)]
        for name in sorted(names)
        if qn("w", name) in node.attrib
    }


def _truncate_runs(
    runs: list[dict[str, object]],
    text_limit: int,
) -> list[dict[str, object]]:
    remaining = text_limit
    result = []
    for run in runs:
        if remaining <= 0:
            break
        text = str(run["text"])
        visible = text[:remaining]
        copied = dict(run)
        copied["text"] = visible
        result.append(copied)
        remaining -= len(visible)
    return result
