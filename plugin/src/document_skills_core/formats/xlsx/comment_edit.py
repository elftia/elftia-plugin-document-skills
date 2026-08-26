"""Transactional legacy cell-note mutation for existing XLSX packages."""

from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .annotations import build_comments_root, build_comments_vml
from .comment_package import (
    add_comment_content_types as _add_comment_content_types,
    insert_legacy_drawing as _insert_legacy_drawing,
    legacy_vml_relationship as _legacy_vml_relationship,
    next_comment_parts as _next_comment_parts,
    next_relationship_id as _next_relationship_id,
    next_vml_shape_id as _next_vml_shape_id,
    relative_target as _relative_target,
    remove_comment_content_types as _remove_comment_content_types,
    resolve_target as _resolve_target,
    single_relationship as _single_relationship,
    worksheet_relationships as _worksheet_relationships,
)
from .constants import NS, REL_COMMENTS, REL_VML_DRAWING

_MAIN_NS = NS["main"]
_REL_NS = NS["rels"]
_EXCEL_NS = "urn:schemas-microsoft-com:office:excel"


def apply_comment_edit(context: Any, sheet_part: str, edit: dict[str, Any]) -> None:
    worksheet = context.worksheet(sheet_part)
    rels_part, relationships = _worksheet_relationships(context, sheet_part)
    comment_relationship = _single_relationship(relationships, REL_COMMENTS)
    vml_relationship = _legacy_vml_relationship(worksheet, relationships)
    if edit["type"] == "comment_add" and comment_relationship is None:
        _add_first_comment(
            context,
            sheet_part,
            worksheet,
            rels_part,
            relationships,
            edit["comment"],
        )
        return
    if comment_relationship is None or vml_relationship is None:
        _invalid("Worksheet does not contain a complete legacy comment relationship.")
    comment_part = _resolve_target(sheet_part, comment_relationship.attrib["Target"])
    vml_part = _resolve_target(sheet_part, vml_relationship.attrib["Target"])
    comments_root = context.root(comment_part)
    vml_root = context.root(vml_part)
    entries = _comment_entries(comments_root)
    edit_type = edit["type"]
    if edit_type == "comment_add":
        comment = edit["comment"]
        _assert_unique(entries, comment["ref"])
        _append_comment(comments_root, vml_root, comment)
        context.mark_dirty(comment_part)
        context.mark_dirty(vml_part)
        return
    selector = edit["ref"].replace("$", "").upper()
    matches = [item for item in entries if item.attrib.get("ref", "").upper() == selector]
    if len(matches) != 1:
        _invalid(
            "Comment selector must match exactly one cell note.",
            ref=selector,
            matches=len(matches),
        )
    match = matches[0]
    if edit_type == "comment_update":
        _update_comment(comments_root, match, edit["comment"])
        context.mark_dirty(comment_part)
        return
    if edit_type != "comment_delete":
        _invalid("Comment edit type is not implemented.", edit_type=edit_type)
    comment_list = comments_root.find(f"{{{_MAIN_NS}}}commentList")
    assert comment_list is not None
    comment_list.remove(match)
    _remove_vml_shape(vml_root, selector)
    if len(comment_list):
        context.mark_dirty(comment_part)
        context.mark_dirty(vml_part)
        return
    remove_vml = not any(
        child.tag.rsplit("}", 1)[-1] == "shape" for child in vml_root
    )
    _remove_comment_parts(
        context,
        sheet_part,
        worksheet,
        rels_part,
        relationships,
        comment_relationship,
        vml_relationship,
        comment_part,
        vml_part,
        remove_vml=remove_vml,
    )


def _add_first_comment(
    context: Any,
    sheet_part: str,
    worksheet: Element,
    rels_part: str,
    relationships: Element,
    comment: dict[str, Any],
) -> None:
    if worksheet.find(f"{{{_MAIN_NS}}}legacyDrawing") is not None:
        _enhancement(
            "Comment creation cannot safely merge with an existing legacy drawing.",
            capability="xlsx.comment-existing-vml-merge",
        )
    comment_part, vml_part = _next_comment_parts(context)
    context.add_root(comment_part, build_comments_root([comment]))
    context.add_root(vml_part, build_comments_vml([comment]))
    comment_id = _next_relationship_id(relationships)
    SubElement(
        relationships,
        f"{{{_REL_NS}}}Relationship",
        {
            "Id": comment_id,
            "Type": REL_COMMENTS,
            "Target": _relative_target(sheet_part, comment_part),
        },
    )
    vml_id = _next_relationship_id(relationships)
    SubElement(
        relationships,
        f"{{{_REL_NS}}}Relationship",
        {
            "Id": vml_id,
            "Type": REL_VML_DRAWING,
            "Target": _relative_target(sheet_part, vml_part),
        },
    )
    if rels_part not in context.added:
        context.mark_dirty(rels_part)
    _insert_legacy_drawing(
        worksheet,
        Element(f"{{{_MAIN_NS}}}legacyDrawing", {f"{{{NS['r']}}}id": vml_id}),
    )
    context.mark_dirty(sheet_part)
    _add_comment_content_types(context, comment_part)


def _append_comment(
    comments_root: Element,
    vml_root: Element,
    comment: dict[str, Any],
) -> None:
    authors = comments_root.find(f"{{{_MAIN_NS}}}authors")
    comment_list = comments_root.find(f"{{{_MAIN_NS}}}commentList")
    if authors is None or comment_list is None:
        _invalid("Comments part is missing authors or commentList.")
    author_id = _ensure_author(authors, comment["author"])
    shape_ids = [
        int(item.attrib.get("shapeId", "0"))
        for item in comment_list.findall(f"{{{_MAIN_NS}}}comment")
        if item.attrib.get("shapeId", "0").isdigit()
    ]
    item = SubElement(
        comment_list,
        f"{{{_MAIN_NS}}}comment",
        {
            "ref": comment["ref"],
            "authorId": str(author_id),
            "shapeId": str(max(shape_ids, default=0) + 1),
        },
    )
    _replace_comment_text(item, comment["text"])
    generated_vml = build_comments_vml([comment])
    shape = next(child for child in generated_vml if child.tag.rsplit("}", 1)[-1] == "shape")
    shape.attrib["id"] = f"_x0000_s{_next_vml_shape_id(vml_root)}"
    vml_root.append(shape)


def _update_comment(
    comments_root: Element,
    item: Element,
    comment: dict[str, Any],
) -> None:
    if comment["ref"] != item.attrib.get("ref"):
        _invalid(
            "Comment update must retain the selected cell reference.",
            selected=item.attrib.get("ref"),
            requested=comment["ref"],
        )
    authors = comments_root.find(f"{{{_MAIN_NS}}}authors")
    if authors is None:
        _invalid("Comments part is missing authors.")
    item.attrib["authorId"] = str(_ensure_author(authors, comment["author"]))
    _replace_comment_text(item, comment["text"])


def _replace_comment_text(item: Element, value: str) -> None:
    existing = item.find(f"{{{_MAIN_NS}}}text")
    if existing is not None:
        item.remove(existing)
    text = SubElement(item, f"{{{_MAIN_NS}}}text")
    SubElement(text, f"{{{_MAIN_NS}}}t").text = value


def _remove_vml_shape(root: Element, ref: str) -> None:
    column, row = _cell_coordinates(ref)
    matches: list[Element] = []
    for shape in root:
        client = shape.find(f"{{{_EXCEL_NS}}}ClientData")
        if client is None:
            continue
        row_element = client.find(f"{{{_EXCEL_NS}}}Row")
        column_element = client.find(f"{{{_EXCEL_NS}}}Column")
        if (
            row_element is not None
            and column_element is not None
            and row_element.text == str(row - 1)
            and column_element.text == str(column - 1)
        ):
            matches.append(shape)
    if len(matches) != 1:
        _invalid("Comment VML shape selector is ambiguous.", ref=ref, matches=len(matches))
    root.remove(matches[0])


def _remove_comment_parts(
    context: Any,
    sheet_part: str,
    worksheet: Element,
    rels_part: str,
    relationships: Element,
    comment_relationship: Element,
    vml_relationship: Element,
    comment_part: str,
    vml_part: str,
    *,
    remove_vml: bool,
) -> None:
    relationships.remove(comment_relationship)
    context.remove_part(comment_part)
    if remove_vml:
        relationships.remove(vml_relationship)
        legacy = worksheet.find(f"{{{_MAIN_NS}}}legacyDrawing")
        if legacy is None:
            _invalid("Worksheet comment legacyDrawing reference is missing.")
        worksheet.remove(legacy)
        context.mark_dirty(sheet_part)
        context.remove_part(vml_part)
    else:
        context.mark_dirty(vml_part)
    if len(relationships):
        if rels_part not in context.added:
            context.mark_dirty(rels_part)
    else:
        context.remove_part(rels_part)
    _remove_comment_content_types(
        context,
        comment_part,
        vml_part,
        remove_vml=remove_vml,
    )


def _comment_entries(root: Element) -> list[Element]:
    container = root.find(f"{{{_MAIN_NS}}}commentList")
    if container is None:
        _invalid("Comments part is missing commentList.")
    return list(container.findall(f"{{{_MAIN_NS}}}comment"))


def _assert_unique(entries: list[Element], ref: str) -> None:
    if any(item.attrib.get("ref", "").upper() == ref.upper() for item in entries):
        _invalid("Cell comment already exists.", ref=ref)


def _ensure_author(authors: Element, author: str) -> int:
    values = [item.text or "" for item in authors.findall(f"{{{_MAIN_NS}}}author")]
    if author not in values:
        SubElement(authors, f"{{{_MAIN_NS}}}author").text = author
        values.append(author)
    return values.index(author)


def _cell_coordinates(ref: str) -> tuple[int, int]:
    letters = ref.rstrip("0123456789").upper()
    row = int(ref[len(letters):])
    column = 0
    for char in letters:
        column = column * 26 + ord(char) - ord("A") + 1
    return column, row


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
