"""Reopen assertions for bookmark and internal hyperlink edits."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn
from .link_editing import LinkEditPlan, hyperlink_text
from .mapping import Story, iter_paragraphs


def assert_link_plans(body: Story, plans: list[LinkEditPlan]) -> dict[str, Any]:
    paragraphs = list(iter_paragraphs(body.root))
    verified = []
    for plan in plans:
        if plan.paragraph_index >= len(paragraphs):
            _failed(plan, "paragraph-index")
        paragraph = paragraphs[plan.paragraph_index]
        if plan.kind == "bookmark_insert":
            starts = [
                node
                for node in paragraph.iter(qn("w", "bookmarkStart"))
                if node.attrib.get(qn("w", "name")) == plan.value["name"]
            ]
            if len(starts) != 1:
                _failed(plan, "bookmark-start")
            bookmark_id = starts[0].attrib.get(qn("w", "id"))
            if not any(
                node.attrib.get(qn("w", "id")) == bookmark_id
                for node in paragraph.iter(qn("w", "bookmarkEnd"))
            ):
                _failed(plan, "bookmark-end")
        else:
            anchor = (
                plan.value["bookmark_name"]
                if plan.kind == "hyperlink_insert"
                else plan.value["bookmark_name"] or plan.value["match"]["bookmark_name"]
            )
            text = (
                plan.value["text"]
                if plan.kind == "hyperlink_insert"
                else plan.value["text"] or plan.value["match"]["text"]
            )
            matches = [
                node
                for node in paragraph.iter(qn("w", "hyperlink"))
                if node.attrib.get(qn("w", "anchor")) == anchor
                and hyperlink_text(node) == text
            ]
            if len(matches) != 1:
                _failed(plan, "hyperlink")
        verified.append({"type": plan.kind, "paragraph_index": plan.paragraph_index})
    return {"verified_internal_links": verified}


def _failed(plan: LinkEditPlan, reason: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Edited DOCX internal link does not match the immutable link plan.",
        details={"paragraph_index": plan.paragraph_index, "reason": reason},
    )
