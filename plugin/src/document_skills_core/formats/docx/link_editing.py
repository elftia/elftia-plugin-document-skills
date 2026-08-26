"""Immutable-input planning for bookmarks and internal hyperlinks."""

from dataclasses import dataclass, field
from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn
from .mapping import Story


@dataclass(frozen=True)
class LinkEditPlan:
    kind: str
    paragraph_index: int
    paragraph: Element
    value: dict[str, Any]
    hyperlink: Element | None = None
    bookmark_id: int | None = None


@dataclass
class LinkMutationState:
    body: Story
    bookmark_names: set[str]
    bookmark_ids: set[int]
    selected_links: set[int] = field(default_factory=set)

    @classmethod
    def open(cls, body: Story) -> "LinkMutationState":
        names = {
            node.attrib.get(qn("w", "name"), "")
            for node in body.root.iter(qn("w", "bookmarkStart"))
        }
        ids = {
            int(value)
            for node in body.root.iter(qn("w", "bookmarkStart"))
            if (value := node.attrib.get(qn("w", "id"), "")).isdigit()
        }
        return cls(body, names, ids)

    def plan(
        self,
        edit: dict[str, Any],
        *,
        paragraph: Element,
        paragraph_index: int,
    ) -> LinkEditPlan:
        kind = edit["type"]
        if kind == "bookmark_insert":
            if edit["name"] in self.bookmark_names:
                _precondition_failed(paragraph_index, "bookmark-name-exists")
            bookmark_id = _allocate_number(self.bookmark_ids)
            self.bookmark_names.add(edit["name"])
            return LinkEditPlan(kind, paragraph_index, paragraph, edit, bookmark_id=bookmark_id)
        if kind == "hyperlink_insert":
            if edit["bookmark_name"] not in self.bookmark_names:
                _precondition_failed(paragraph_index, "bookmark-target-missing")
            return LinkEditPlan(kind, paragraph_index, paragraph, edit)

        matches = [
            link
            for link in paragraph.iter(qn("w", "hyperlink"))
            if link.attrib.get(qn("w", "anchor")) == edit["match"]["bookmark_name"]
            and _hyperlink_text(link) == edit["match"]["text"]
        ]
        if len(matches) != edit["match"]["expected_matches"]:
            _precondition_failed(
                paragraph_index,
                "hyperlink-match-count",
                expected_matches=edit["match"]["expected_matches"],
                actual_matches=len(matches),
            )
        if len(matches) != 1 or id(matches[0]) in self.selected_links:
            _conflict(paragraph_index)
        hyperlink = matches[0]
        if hyperlink.attrib.get(qn("r", "id")) is not None:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Core hyperlink update supports only internal bookmark links.",
                status="enhancement_required",
            )
        text_nodes = list(hyperlink.iter(qn("w", "t")))
        if len(text_nodes) != 1:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Core hyperlink update requires one simple hyperlink text run.",
                status="enhancement_required",
            )
        bookmark_name = edit["bookmark_name"] or edit["match"]["bookmark_name"]
        if bookmark_name not in self.bookmark_names:
            _precondition_failed(paragraph_index, "bookmark-target-missing")
        self.selected_links.add(id(hyperlink))
        return LinkEditPlan(kind, paragraph_index, paragraph, edit, hyperlink=hyperlink)


def hyperlink_text(node: Element) -> str:
    return _hyperlink_text(node)


def _hyperlink_text(node: Element) -> str:
    return "".join(text.text or "" for text in node.iter(qn("w", "t")))


def _allocate_number(values: set[int]) -> int:
    candidate = 0
    while candidate in values:
        candidate += 1
    values.add(candidate)
    return candidate


def _precondition_failed(index: int, reason: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "DOCX internal-link precondition did not match the immutable input.",
        details={"paragraph_index": index, "reason": reason, **details},
    )


def _conflict(index: int) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        "DOCX edit transaction contains conflicting hyperlink edits.",
        status="invalid_request",
        details={"paragraph_index": index},
    )
