"""Internal hyperlinks and legacy cell-note part builders."""

from __future__ import annotations

import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement, register_namespace

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS, REL_COMMENTS, REL_VML_DRAWING
from .relationships import relationship_map

_MAIN_NS = NS["main"]
_VML_NS = "urn:schemas-microsoft-com:vml"
_OFFICE_NS = "urn:schemas-microsoft-com:office:office"
_EXCEL_NS = "urn:schemas-microsoft-com:office:excel"
_XML_NS = "http://www.w3.org/XML/1998/namespace"

register_namespace("v", _VML_NS)
register_namespace("o", _OFFICE_NS)
register_namespace("x", _EXCEL_NS)


def append_hyperlinks(root: Element, hyperlinks: list[dict[str, Any]]) -> None:
    if not hyperlinks:
        return
    container = Element(f"{{{_MAIN_NS}}}hyperlinks")
    for hyperlink in hyperlinks:
        _append_hyperlink(container, hyperlink)
    _insert_before_print_metadata(root, container)


def apply_hyperlink_edit(root: Element, edit: dict[str, Any]) -> None:
    container = root.find(f"{{{_MAIN_NS}}}hyperlinks")
    entries = [] if container is None else list(container.findall(f"{{{_MAIN_NS}}}hyperlink"))
    edit_type = edit["type"]
    if edit_type == "hyperlink_add":
        hyperlink = edit["hyperlink"]
        _assert_unique_hyperlink(entries, hyperlink["ref"])
        if container is None:
            container = Element(f"{{{_MAIN_NS}}}hyperlinks")
            _insert_before_print_metadata(root, container)
        _append_hyperlink(container, hyperlink)
        return
    selector = _normalize_range(edit["ref"])
    matches = [
        item
        for item in entries
        if _normalize_range(item.attrib.get("ref", "")) == selector
    ]
    if len(matches) != 1:
        _invalid(
            "Hyperlink selector must match exactly one internal hyperlink.",
            ref=selector,
            matches=len(matches),
        )
    assert container is not None
    match = matches[0]
    if f"{{{NS['r']}}}id" in match.attrib:
        _enhancement(
            "External hyperlink mutation is not authorized by the Core profile.",
            capability="xlsx.external-hyperlink-authoring",
        )
    if edit_type == "hyperlink_delete":
        container.remove(match)
        if not len(container):
            root.remove(container)
        return
    if edit_type != "hyperlink_update":
        _invalid("Hyperlink edit type is not implemented.", edit_type=edit_type)
    hyperlink = edit["hyperlink"]
    _assert_unique_hyperlink(entries, hyperlink["ref"], excluding=match)
    index = list(container).index(match)
    container.remove(match)
    replacement_parent = Element("replacement")
    replacement = _append_hyperlink(replacement_parent, hyperlink)
    container.insert(index, replacement)


def build_comments_root(comments: list[dict[str, Any]]) -> Element:
    root = Element(f"{{{_MAIN_NS}}}comments")
    authors = SubElement(root, f"{{{_MAIN_NS}}}authors")
    author_names: list[str] = []
    for comment in comments:
        if comment["author"] not in author_names:
            author_names.append(comment["author"])
            SubElement(authors, f"{{{_MAIN_NS}}}author").text = comment["author"]
    comment_list = SubElement(root, f"{{{_MAIN_NS}}}commentList")
    for shape_id, comment in enumerate(comments, start=1):
        item = SubElement(
            comment_list,
            f"{{{_MAIN_NS}}}comment",
            {
                "ref": comment["ref"],
                "authorId": str(author_names.index(comment["author"])),
                "shapeId": str(shape_id),
            },
        )
        text = SubElement(item, f"{{{_MAIN_NS}}}text")
        run = SubElement(text, f"{{{_MAIN_NS}}}t")
        if comment["text"] != comment["text"].strip():
            run.attrib[f"{{{_XML_NS}}}space"] = "preserve"
        run.text = comment["text"]
    return root


def build_comments_vml(comments: list[dict[str, Any]]) -> Element:
    root = Element("xml")
    shape_layout = SubElement(root, f"{{{_OFFICE_NS}}}shapelayout", {f"{{{_VML_NS}}}ext": "edit"})
    SubElement(
        shape_layout,
        f"{{{_OFFICE_NS}}}idmap",
        {f"{{{_VML_NS}}}ext": "edit", "data": "1"},
    )
    shape_type = SubElement(
        root,
        f"{{{_VML_NS}}}shapetype",
        {
            "id": "_x0000_t202",
            "coordsize": "21600,21600",
            f"{{{_OFFICE_NS}}}spt": "202",
            "path": "m,l,21600r21600,l21600,xe",
        },
    )
    SubElement(shape_type, f"{{{_VML_NS}}}stroke", {"joinstyle": "miter"})
    SubElement(
        shape_type,
        f"{{{_VML_NS}}}path",
        {"gradientshapeok": "t", f"{{{_OFFICE_NS}}}connecttype": "rect"},
    )
    for index, comment in enumerate(comments, start=1):
        column, row = _cell_ref(comment["ref"])
        shape = SubElement(
            root,
            f"{{{_VML_NS}}}shape",
            {
                "id": f"_x0000_s{1024 + index}",
                "type": "#_x0000_t202",
                "style": (
                    "position:absolute;margin-left:59.25pt;margin-top:1.5pt;"
                    "width:108pt;height:59.25pt;z-index:1;visibility:hidden"
                ),
                "fillcolor": "#ffffe1",
                f"{{{_OFFICE_NS}}}insetmode": "auto",
            },
        )
        SubElement(shape, f"{{{_VML_NS}}}fill", {"color2": "#ffffe1"})
        SubElement(shape, f"{{{_VML_NS}}}shadow", {"on": "t", "color": "black", "obscured": "t"})
        SubElement(shape, f"{{{_VML_NS}}}path", {f"{{{_OFFICE_NS}}}connecttype": "none"})
        textbox = SubElement(shape, f"{{{_VML_NS}}}textbox", {"style": "mso-direction-alt:auto"})
        SubElement(textbox, "div", {"style": "text-align:left"})
        client = SubElement(shape, f"{{{_EXCEL_NS}}}ClientData", {"ObjectType": "Note"})
        SubElement(client, f"{{{_EXCEL_NS}}}MoveWithCells")
        SubElement(client, f"{{{_EXCEL_NS}}}SizeWithCells")
        SubElement(client, f"{{{_EXCEL_NS}}}Anchor").text = (
            f"{column}, 15, {row - 1}, 2, {column + 2}, 15, {row + 3}, 4"
        )
        SubElement(client, f"{{{_EXCEL_NS}}}AutoFill").text = "False"
        SubElement(client, f"{{{_EXCEL_NS}}}Row").text = str(row - 1)
        SubElement(client, f"{{{_EXCEL_NS}}}Column").text = str(column - 1)
    return root


def project_comments(package: Any) -> list[dict[str, Any]]:
    workbook = package.xml("xl/workbook.xml")
    workbook_rels = relationship_map(package.relationships, "xl/workbook.xml")
    sheet_names: dict[str, str] = {}
    for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
        relationship = workbook_rels.get(sheet.attrib.get(f"{{{NS['r']}}}id", ""))
        if relationship is not None and relationship.resolved_target:
            sheet_names[relationship.resolved_target] = sheet.attrib.get("name", "")
    result: list[dict[str, Any]] = []
    for sheet_part, sheet_name in sheet_names.items():
        relationships = relationship_map(package.relationships, sheet_part)
        comments_relationships = [
            item
            for item in relationships.values()
            if item.relationship_type == REL_COMMENTS and item.resolved_target
        ]
        worksheet = package.xml(sheet_part)
        legacy = worksheet.find(f"{{{_MAIN_NS}}}legacyDrawing")
        vml_relationship = (
            None
            if legacy is None
            else relationships.get(legacy.attrib.get(f"{{{NS['r']}}}id", ""))
        )
        vml_part = (
            vml_relationship.resolved_target
            if vml_relationship is not None
            and vml_relationship.relationship_type == REL_VML_DRAWING
            else None
        )
        for relationship in comments_relationships:
            part = relationship.resolved_target
            assert part is not None
            root = package.xml(part)
            authors = [
                item.text or ""
                for item in root.findall(f"{{{_MAIN_NS}}}authors/{{{_MAIN_NS}}}author")
            ]
            for item in root.findall(
                f"{{{_MAIN_NS}}}commentList/{{{_MAIN_NS}}}comment"
            ):
                author_id = item.attrib.get("authorId", "")
                author = (
                    authors[int(author_id)]
                    if author_id.isdigit() and int(author_id) < len(authors)
                    else None
                )
                result.append(
                    {
                        "sheet": sheet_name,
                        "ref": item.attrib.get("ref", ""),
                        "text": "".join(
                            text.text or ""
                            for text in item.findall(f".//{{{_MAIN_NS}}}t")
                        ),
                        "author": author,
                        "part": part,
                        "vml_part": vml_part,
                    }
                )
    return result


def _append_hyperlink(parent: Element, hyperlink: dict[str, Any]) -> Element:
    attributes = {"ref": hyperlink["ref"], "location": hyperlink["location"]}
    for source in ("display", "tooltip"):
        if hyperlink.get(source) is not None:
            attributes[source] = hyperlink[source]
    return SubElement(parent, f"{{{_MAIN_NS}}}hyperlink", attributes)


def _assert_unique_hyperlink(
    entries: list[Element],
    ref: str,
    *,
    excluding: Element | None = None,
) -> None:
    if any(
        item is not excluding
        and _normalize_range(item.attrib.get("ref", "")) == _normalize_range(ref)
        for item in entries
    ):
        _invalid("Internal hyperlink ref already exists.", ref=ref)


def _insert_before_print_metadata(root: Element, element: Element) -> None:
    following_names = {
        "printOptions",
        "pageMargins",
        "pageSetup",
        "headerFooter",
        "rowBreaks",
        "colBreaks",
        "drawing",
        "legacyDrawing",
        "tableParts",
        "extLst",
    }
    for index, child in enumerate(root):
        if child.tag.rsplit("}", 1)[-1] in following_names:
            root.insert(index, element)
            return
    root.append(element)


def _cell_ref(ref: str) -> tuple[int, int]:
    match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", ref)
    assert match is not None
    column = 0
    for char in match.group(1).upper():
        column = column * 26 + ord(char) - ord("A") + 1
    return column, int(match.group(2))


def _normalize_range(ref: str) -> str:
    return ":".join(item.replace("$", "").upper() for item in ref.split(":"))


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
