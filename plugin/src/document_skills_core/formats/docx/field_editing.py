"""Safe Word field inventory, typed mutation, and reopen assertions."""

from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn
from .field_contract import SAFE_FIELD_KINDS, field_kind, normalize_instruction

_SAFE_PROJECTED_FIELD_KINDS = SAFE_FIELD_KINDS | {"PAGEREF", "REF"}
from .mapping import Story, iter_paragraphs
from .xml_utils import text_run


@dataclass(frozen=True)
class FieldReference:
    index: int
    paragraph_index: int
    instruction: str
    kind: str
    field_type: str
    update_pending: bool
    node: Element

    def as_dict(self, story: Story) -> dict[str, Any]:
        return {
            "index": self.index,
            "story": story.kind,
            "part": story.part,
            "paragraph_index": self.paragraph_index,
            "field_type": self.field_type,
            "instruction": self.instruction,
            "kind": self.kind,
            "safe": self.kind in _SAFE_PROJECTED_FIELD_KINDS | {"TOC"},
            "update_pending": self.update_pending,
        }


@dataclass(frozen=True)
class FieldEditPlan:
    value: dict[str, Any]
    paragraph: Element | None = None
    parent: Element | None = None
    reference: FieldReference | None = None


class FieldMutationState:
    def __init__(self, body: Story) -> None:
        self.body = body
        self.references = scan_story_fields(body)

    def plan_refresh(self, edit: dict[str, Any]) -> FieldEditPlan:
        selector = edit["selector"]
        index = selector["field_index"]
        if index >= len(self.references):
            _precondition("field-index", field_index=index)
        reference = self.references[index]
        if reference.instruction != selector["expected_instruction"]:
            _precondition(
                "expected-instruction",
                field_index=index,
                actual_instruction=reference.instruction,
            )
        if reference.kind not in SAFE_FIELD_KINDS | {"TOC"}:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Unsafe or external fields cannot be refreshed by Core.",
                status="enhancement_required",
            )
        return FieldEditPlan(edit, reference=reference)

    def plan_insert(
        self,
        edit: dict[str, Any],
        *,
        paragraph: Element,
        parent: Element,
    ) -> FieldEditPlan:
        return FieldEditPlan(edit, paragraph=paragraph, parent=parent)


def apply_field_plan(plan: FieldEditPlan) -> None:
    edit_type = plan.value["type"]
    if edit_type == "field_refresh":
        assert plan.reference is not None
        plan.reference.node.attrib[qn("w", "dirty")] = "1"
        return
    assert plan.paragraph is not None
    assert plan.parent is not None
    if edit_type == "field_insert":
        field = _simple_field(
            plan.value["field"]["kind"],
            plan.value["field"]["display_text"],
        )
        if plan.value["placement"] == "append":
            plan.paragraph.append(field)
        else:
            position = 1 if plan.paragraph.find(qn("w", "pPr")) is not None else 0
            plan.paragraph.insert(position, field)
        return
    levels = plan.value["heading_levels"]
    instruction = f'TOC \\o "{levels["start"]}-{levels["end"]}" \\h \\z \\u'
    toc = Element(qn("w", "p"))
    toc.append(_simple_field(instruction, "Update table of contents"))
    position = list(plan.parent).index(plan.paragraph)
    if plan.value["position"] == "after":
        position += 1
    plan.parent.insert(position, toc)


def project_fields(stories: list[Story], maximum: int = 1_000) -> tuple[list[dict[str, Any]], bool]:
    result: list[dict[str, Any]] = []
    for story in stories:
        for reference in scan_story_fields(story):
            if len(result) >= maximum:
                return result, True
            item = reference.as_dict(story)
            item["index"] = len(result)
            result.append(item)
    return result, False


def scan_story_fields(story: Story) -> list[FieldReference]:
    result: list[FieldReference] = []
    for paragraph_index, paragraph in enumerate(iter_paragraphs(story.root)):
        for field in paragraph.iter(qn("w", "fldSimple")):
            instruction = normalize_instruction(field.attrib.get(qn("w", "instr"), ""))
            result.append(
                FieldReference(
                    len(result),
                    paragraph_index,
                    instruction,
                    field_kind(instruction),
                    "simple",
                    field.attrib.get(qn("w", "dirty")) in {"1", "true"},
                    field,
                )
            )
        stack: list[dict[str, Any]] = []
        for node in paragraph.iter():
            if node.tag == qn("w", "fldChar"):
                char_type = node.attrib.get(qn("w", "fldCharType"))
                if char_type == "begin":
                    stack.append({"node": node, "text": []})
                elif char_type == "end" and stack:
                    active = stack.pop()
                    instruction = normalize_instruction("".join(active["text"]))
                    result.append(
                        FieldReference(
                            len(result),
                            paragraph_index,
                            instruction,
                            field_kind(instruction),
                            "complex",
                            active["node"].attrib.get(qn("w", "dirty")) in {"1", "true"},
                            active["node"],
                        )
                    )
            elif node.tag == qn("w", "instrText") and stack:
                stack[-1]["text"].append(node.text or "")
        if stack:
            _unsafe("Word field begin/end markers are unbalanced.")
    return result


def assert_field_inventory(path_story: Story, expected: list[dict[str, Any]]) -> dict[str, Any]:
    actual, truncated = project_fields([path_story], maximum=max(len(expected) + 1, 1))
    if truncated or actual != expected:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Edited Word fields do not match the immutable plan.",
        )
    return {"verified_fields": len(actual)}


def _simple_field(instruction: str, display_text: str) -> Element:
    field = Element(
        qn("w", "fldSimple"),
        {qn("w", "instr"): instruction, qn("w", "dirty"): "1"},
    )
    text_run(field, display_text)
    return field


def _precondition(reason: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "DOCX field selector did not match the immutable input.",
        details={"reason": reason, **details},
    )


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)
