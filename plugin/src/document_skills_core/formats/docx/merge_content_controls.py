"""Safety audit for content controls admitted by high-fidelity merge."""

from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import local_name, qn, WORD_MAIN
from .content_control_editing import scan_content_controls
from .mapping import Story

_SAFE_PROPERTY_NAMES = {"alias", "id", "lock", "tag", "text"}
_RELATIONSHIP_ATTRIBUTES = {
    qn("r", "embed"),
    qn("r", "id"),
    qn("r", "link"),
}


def count_safe_merge_content_controls(
    root: Element,
    *,
    source_index: int | None,
) -> int:
    story = Story("body", WORD_MAIN, root)
    references = scan_content_controls(story)
    for reference in references:
        record = reference.record
        if record["locked"] or not record["simple_text"]:
            _unsupported(
                "DOCX merge accepts only unlocked single-text-node content controls.",
                source_index=source_index,
                control_index=reference.index,
            )
        properties = reference.node.find(qn("w", "sdtPr"))
        property_names = (
            {local_name(child.tag) for child in properties}
            if properties is not None
            else set()
        )
        unsupported_properties = sorted(property_names - _SAFE_PROPERTY_NAMES)
        if unsupported_properties:
            _unsupported(
                "DOCX merge content control requires an unsupported property graph.",
                source_index=source_index,
                control_index=reference.index,
                properties=unsupported_properties,
            )
        if any(
            set(node.attrib).intersection(_RELATIONSHIP_ATTRIBUTES)
            for node in reference.node.iter()
        ):
            _unsupported(
                "DOCX merge content control contains a relationship binding.",
                source_index=source_index,
                control_index=reference.index,
            )
    return len(references)


def _unsupported(
    message: str,
    *,
    source_index: int | None,
    control_index: int,
    **details: Any,
) -> None:
    location: dict[str, Any] = {"control_index": control_index}
    if source_index is None:
        location["document"] = "base"
    else:
        location["source_index"] = source_index
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={**location, **details},
    )
