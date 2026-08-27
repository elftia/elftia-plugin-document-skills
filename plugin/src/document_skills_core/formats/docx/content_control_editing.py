"""Bounded content-control inventory and text-only mutation."""

from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn
from .mapping import Story
from .xml_utils import selector_sha256, set_text

_PROTECTED = {
    "commentRangeEnd",
    "commentRangeStart",
    "commentReference",
    "del",
    "drawing",
    "fldChar",
    "fldSimple",
    "hyperlink",
    "ins",
    "instrText",
    "moveFrom",
    "moveTo",
    "tbl",
}


@dataclass(frozen=True)
class ContentControlReference:
    index: int
    node: Element
    text_node: Element | None
    record: dict[str, Any]


@dataclass(frozen=True)
class ContentControlEditPlan:
    value: dict[str, Any]
    reference: ContentControlReference


class ContentControlMutationState:
    def __init__(self, body: Story) -> None:
        self.body = body
        self.references = scan_content_controls(body)
        self.selected: set[int] = set()

    def plan(self, edit: dict[str, Any]) -> ContentControlEditPlan:
        selector = edit["selector"]
        index = selector["control_index"]
        if index >= len(self.references):
            _precondition("control-index", control_index=index)
        reference = self.references[index]
        if index in self.selected:
            _precondition("control-selected-twice", control_index=index)
        if reference.record["selector_sha256"] != selector["expected_sha256"]:
            _precondition("expected-sha256", control_index=index)
        if reference.record["text"] != selector["expected_text"]:
            _precondition("expected-text", control_index=index)
        if reference.record["locked"] or not reference.record["simple_text"]:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Core updates only unlocked single-text-node content controls.",
                status="enhancement_required",
                details={"control_index": index},
            )
        self.selected.add(index)
        return ContentControlEditPlan(edit, reference)


def apply_content_control_plan(plan: ContentControlEditPlan) -> None:
    assert plan.reference.text_node is not None
    set_text(plan.reference.text_node, plan.value["text"])


def project_content_controls(
    stories: list[Story],
    maximum: int = 1_000,
) -> tuple[list[dict[str, Any]], bool]:
    result: list[dict[str, Any]] = []
    for story in stories:
        for reference in scan_content_controls(story):
            if len(result) >= maximum:
                return result, True
            record = dict(reference.record)
            record["index"] = len(result)
            result.append(record)
    return result, False


def scan_content_controls(story: Story) -> list[ContentControlReference]:
    result: list[ContentControlReference] = []
    for node in story.root.iter(qn("w", "sdt")):
        properties = node.find(qn("w", "sdtPr"))
        content = node.find(qn("w", "sdtContent"))
        text_nodes = list(content.iter(qn("w", "t"))) if content is not None else []
        protected = (
            content is None
            or any(
                element is not node
                and element.tag == qn("w", "sdt")
                or element.tag.rsplit("}", 1)[-1] in _PROTECTED
                for element in (content.iter() if content is not None else ())
            )
        )
        lock = properties.find(qn("w", "lock")) if properties is not None else None
        record = {
            "index": len(result),
            "story": story.kind,
            "part": story.part,
            "id": _property(properties, "id"),
            "tag": _property(properties, "tag"),
            "alias": _property(properties, "alias"),
            "text": "".join(text.text or "" for text in text_nodes),
            "locked": lock is not None and lock.attrib.get(qn("w", "val"), "") not in {"", "unlocked"},
            "simple_text": not protected and len(text_nodes) == 1,
            "selector_sha256": selector_sha256(node),
        }
        result.append(
            ContentControlReference(
                len(result),
                node,
                text_nodes[0] if len(text_nodes) == 1 else None,
                record,
            )
        )
    return result


def assert_content_control_inventory(
    story: Story,
    expected: list[dict[str, Any]],
) -> dict[str, Any]:
    actual, truncated = project_content_controls([story], max(len(expected) + 1, 1))
    if truncated or actual != expected:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Edited content controls do not match the immutable plan.",
        )
    return {"verified_content_controls": len(actual)}


def _property(properties: Element | None, name: str) -> str | None:
    node = properties.find(qn("w", name)) if properties is not None else None
    return node.attrib.get(qn("w", "val")) if node is not None else None


def _precondition(reason: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "DOCX content-control selector did not match the immutable input.",
        details={"reason": reason, **details},
    )
