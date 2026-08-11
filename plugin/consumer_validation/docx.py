"""Strict DOCX expectation schema and independent semantic assertions."""

from __future__ import annotations

import re
from typing import Any


_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": _DOC_REL,
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}
_ALLOWED_EXPECTATIONS = frozenset(
    {"images", "paragraph_styles", "tables", "text"}
)
_MAX_EXPECTATION_ITEMS = 256
_MAX_EXPECTATION_TEXT_BYTES = 8 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STYLE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,63}$")


def append_docx_assertions(
    document: Any,
    styles: Any,
    relationships: dict[str, Any],
    part_sha256: dict[str, str],
    expectations: dict[str, Any],
    assertions: list[dict[str, Any]],
) -> None:
    """Validate and prove the supported bounded DOCX expectation semantics."""

    parsed = _parse_expectations(expectations, assertions)
    if parsed is None:
        return
    _record(
        assertions,
        "docx.expectations-schema",
        True,
        {
            "images": 0 if parsed["images"] is None else len(parsed["images"]),
            "paragraph_styles": (
                0
                if parsed["paragraph_styles"] is None
                else len(parsed["paragraph_styles"])
            ),
            "tables": parsed["tables"],
            "text": len(parsed["text"]),
        },
    )
    text = "".join(node.text or "" for node in document.findall(".//w:t", _NS))
    missing = [value for value in parsed["text"] if value not in text]
    _record(assertions, "docx.requested-text", not missing, {"missing": missing})
    actual_tables = len(document.findall(".//w:tbl", _NS))
    _record(
        assertions,
        "docx.tables",
        actual_tables >= parsed["tables"],
        {"expected_minimum": parsed["tables"], "actual": actual_tables},
    )
    if parsed["images"] is not None:
        _assert_images(
            document,
            relationships,
            part_sha256,
            parsed["images"],
            assertions,
        )
    if parsed["paragraph_styles"] is not None:
        _assert_paragraph_styles(
            document,
            styles,
            parsed["paragraph_styles"],
            assertions,
        )


def _parse_expectations(
    expectations: dict[str, Any],
    assertions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    unknown = sorted(set(expectations) - _ALLOWED_EXPECTATIONS)
    if unknown:
        _record(
            assertions,
            "docx.expectations-schema",
            False,
            {"category": "unknown-expectation-keys", "unknown": unknown[:64]},
        )
        return None
    try:
        text = _text_list(expectations.get("text", []), "text")
        tables = expectations.get("tables", 0)
        if type(tables) is not int or type(tables) is bool or not 0 <= tables <= 1_000:
            raise ValueError("invalid-tables-expectation")
        images = (
            _images(expectations["images"])
            if "images" in expectations
            else None
        )
        paragraph_styles = (
            _paragraph_styles(expectations["paragraph_styles"])
            if "paragraph_styles" in expectations
            else None
        )
        return {
            "images": images,
            "paragraph_styles": paragraph_styles,
            "tables": tables,
            "text": text,
        }
    except ValueError as error:
        _record(
            assertions,
            "docx.expectations-schema",
            False,
            {"category": str(error)},
        )
        return None


def _text_list(value: Any, field: str) -> list[str]:
    if type(value) is not list or len(value) > _MAX_EXPECTATION_ITEMS:
        raise ValueError(f"invalid-{field}-expectation")
    return [_bounded_text(item, field) for item in value]


def _images(value: Any) -> list[dict[str, str]]:
    if type(value) is not list or len(value) > 32:
        raise ValueError("invalid-images-expectation")
    parsed: list[dict[str, str]] = []
    for item in value:
        if type(item) is not dict or set(item) != {"alt_text", "sha256"}:
            raise ValueError("invalid-image-identity-expectation")
        sha256 = item.get("sha256")
        if type(sha256) is not str or _SHA256.fullmatch(sha256) is None:
            raise ValueError("invalid-image-sha256-expectation")
        parsed.append(
            {
                "alt_text": _bounded_text(item.get("alt_text"), "image-alt-text"),
                "sha256": sha256,
            }
        )
    return parsed


def _paragraph_styles(value: Any) -> list[dict[str, str]]:
    if type(value) is not list or len(value) > _MAX_EXPECTATION_ITEMS:
        raise ValueError("invalid-paragraph-styles-expectation")
    parsed: list[dict[str, str]] = []
    for item in value:
        if type(item) is not dict or set(item) != {"style", "text"}:
            raise ValueError("invalid-paragraph-style-expectation")
        style = item.get("style")
        if type(style) is not str or _STYLE_ID.fullmatch(style) is None:
            raise ValueError("invalid-paragraph-style-id-expectation")
        parsed.append(
            {
                "style": style,
                "text": _bounded_text(item.get("text"), "paragraph-style-text"),
            }
        )
    return parsed


def _bounded_text(value: Any, field: str) -> str:
    if type(value) is not str or len(value.encode("utf-8")) > _MAX_EXPECTATION_TEXT_BYTES:
        raise ValueError(f"invalid-{field}-expectation")
    return value


def _assert_images(
    document: Any,
    relationships: dict[str, Any],
    part_sha256: dict[str, str],
    expected: list[dict[str, str]],
    assertions: list[dict[str, Any]],
) -> None:
    actual: list[dict[str, str]] = []
    for inline in document.findall(".//wp:inline", _NS):
        blip = inline.find(".//a:blip", _NS)
        drawing_properties = inline.find("wp:docPr", _NS)
        relationship_id = (
            "" if blip is None else blip.attrib.get(f"{{{_DOC_REL}}}embed", "")
        )
        relationship = relationships.get(relationship_id)
        if (
            relationship is None
            or not relationship.relationship_type.endswith("/image")
            or relationship.target not in part_sha256
        ):
            continue
        actual.append(
            {
                "alt_text": (
                    ""
                    if drawing_properties is None
                    else drawing_properties.attrib.get("descr", "")
                ),
                "sha256": part_sha256[relationship.target],
            }
        )
    mismatches: list[dict[str, Any]] = []
    for index in range(max(len(expected), len(actual))):
        expected_item = expected[index] if index < len(expected) else None
        actual_item = actual[index] if index < len(actual) else None
        if expected_item != actual_item:
            mismatches.append(
                {
                    "actual": actual_item,
                    "expected": expected_item,
                    "index": index,
                }
            )
    _record(
        assertions,
        "docx.images",
        not mismatches,
        {
            "actual_count": len(actual),
            "expected_count": len(expected),
            "mismatches": mismatches[:32],
        },
    )


def _assert_paragraph_styles(
    document: Any,
    styles: Any,
    expected: list[dict[str, str]],
    assertions: list[dict[str, Any]],
) -> None:
    registered = {
        item.attrib.get(f"{{{_NS['w']}}}styleId", "")
        for item in styles.findall("w:style", _NS)
        if item.attrib.get(f"{{{_NS['w']}}}type") == "paragraph"
    }
    paragraphs: list[tuple[str, str | None]] = []
    for paragraph in document.findall(".//w:p", _NS):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", _NS))
        style = paragraph.find("w:pPr/w:pStyle", _NS)
        style_id = None if style is None else style.attrib.get(f"{{{_NS['w']}}}val")
        paragraphs.append((text, style_id))
    failures: list[dict[str, Any]] = []
    for index, item in enumerate(expected):
        actual_styles = sorted(
            {style_id or "" for text, style_id in paragraphs if text == item["text"]}
        )
        if item["style"] not in registered or item["style"] not in actual_styles:
            failures.append(
                {
                    "actual_styles": actual_styles[:16],
                    "expected_style": item["style"],
                    "index": index,
                    "registered": item["style"] in registered,
                }
            )
    _record(
        assertions,
        "docx.paragraph-styles",
        not failures,
        {"failures": failures[:64], "requested": len(expected)},
    )


def _record(
    assertions: list[dict[str, Any]],
    assertion_id: str,
    passed: bool,
    evidence: dict[str, Any],
) -> None:
    assertions.append(
        {
            "id": assertion_id,
            "outcome": "pass" if passed else "fail",
            "evidence": evidence,
            "message": "" if passed else f"Independent assertion failed: {assertion_id}",
        }
    )
