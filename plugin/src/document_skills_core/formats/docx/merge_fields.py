"""Safety audit for Word fields admitted by high-fidelity merge."""

from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn
from .field_contract import SAFE_FIELD_KINDS, field_kind, normalize_instruction
from .mapping import iter_paragraphs

_SAFE_MERGE_FIELD_KINDS = SAFE_FIELD_KINDS | {"TOC"}


def count_safe_merge_fields(root: Element, *, source_index: int | None) -> int:
    """Return the field count after rejecting malformed or unsafe instructions."""
    count = 0
    for paragraph_index, paragraph in enumerate(iter_paragraphs(root)):
        for simple in paragraph.iter(qn("w", "fldSimple")):
            _assert_safe_instruction(
                simple.attrib.get(qn("w", "instr"), ""),
                source_index=source_index,
                paragraph_index=paragraph_index,
            )
            count += 1
        stack: list[list[str]] = []
        for node in paragraph.iter():
            if node.tag == qn("w", "instrText"):
                if not stack:
                    _malformed(
                        "Word field instruction text is not inside a field.",
                        source_index=source_index,
                        paragraph_index=paragraph_index,
                    )
                stack[-1].append(node.text or "")
                continue
            if node.tag != qn("w", "fldChar"):
                continue
            char_type = node.attrib.get(qn("w", "fldCharType"))
            if char_type == "begin":
                stack.append([])
            elif char_type == "separate":
                if not stack:
                    _malformed(
                        "Word field separator has no matching begin marker.",
                        source_index=source_index,
                        paragraph_index=paragraph_index,
                    )
            elif char_type == "end":
                if not stack:
                    _malformed(
                        "Word field end has no matching begin marker.",
                        source_index=source_index,
                        paragraph_index=paragraph_index,
                    )
                _assert_safe_instruction(
                    "".join(stack.pop()),
                    source_index=source_index,
                    paragraph_index=paragraph_index,
                )
                count += 1
            else:
                _malformed(
                    "Word field marker type is invalid.",
                    source_index=source_index,
                    paragraph_index=paragraph_index,
                )
        if stack:
            _malformed(
                "Word field begin/end markers are unbalanced.",
                source_index=source_index,
                paragraph_index=paragraph_index,
            )
    return count


def _assert_safe_instruction(
    instruction: str,
    *,
    source_index: int | None,
    paragraph_index: int,
) -> None:
    normalized = normalize_instruction(instruction)
    kind = field_kind(normalized)
    if kind not in _SAFE_MERGE_FIELD_KINDS:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "DOCX merge accepts only the closed safe Word field vocabulary.",
            status="enhancement_required",
            details={
                **_location(source_index, paragraph_index),
                "field_kind": kind,
            },
        )


def _malformed(
    message: str,
    *,
    source_index: int | None,
    paragraph_index: int,
) -> None:
    raise DocumentSkillsError(
        ErrorCode.ARCHIVE_UNSAFE,
        message,
        details=_location(source_index, paragraph_index),
    )


def _location(source_index: int | None, paragraph_index: int) -> dict[str, Any]:
    location: dict[str, Any] = {"paragraph_index": paragraph_index}
    if source_index is not None:
        location["source_index"] = source_index
    else:
        location["document"] = "base"
    return location
