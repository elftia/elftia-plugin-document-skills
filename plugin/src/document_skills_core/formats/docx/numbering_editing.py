"""Typed paragraph numbering updates bound to the existing numbering graph."""

from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn
from .mapping import Story, iter_paragraphs, paragraph_numbering
from .package import OpcPackage


@dataclass(frozen=True)
class NumberingEditPlan:
    value: dict[str, Any]
    paragraph: Element
    paragraph_index: int


class NumberingMutationState:
    def __init__(self, package: OpcPackage) -> None:
        part = "word/numbering.xml"
        if part not in package.parts:
            self.instances: dict[str, set[int]] = {}
            return
        root = package.xml(part)
        abstract_levels = {
            node.attrib.get(qn("w", "abstractNumId"), ""): {
                int(value)
                for level in node.findall(qn("w", "lvl"))
                if (value := level.attrib.get(qn("w", "ilvl"), "")).isdigit()
            }
            for node in root.findall(qn("w", "abstractNum"))
        }
        self.instances = {}
        for number in root.findall(qn("w", "num")):
            num_id = number.attrib.get(qn("w", "numId"), "")
            reference = number.find(qn("w", "abstractNumId"))
            abstract_id = (
                reference.attrib.get(qn("w", "val"), "")
                if reference is not None
                else ""
            )
            if not num_id or abstract_id not in abstract_levels:
                _unsafe("DOCX numbering graph is internally inconsistent.")
            self.instances[num_id] = abstract_levels[abstract_id]

    def plan(
        self,
        edit: dict[str, Any],
        paragraph: Element,
        paragraph_index: int,
    ) -> NumberingEditPlan:
        numbering = edit["numbering"]
        levels = self.instances.get(numbering["num_id"])
        if levels is None or numbering["level"] not in levels:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Paragraph numbering selector does not exist in the immutable numbering graph.",
                details={
                    "paragraph_index": paragraph_index,
                    "num_id": numbering["num_id"],
                    "level": numbering["level"],
                },
            )
        return NumberingEditPlan(edit, paragraph, paragraph_index)


def apply_numbering_plan(plan: NumberingEditPlan) -> None:
    properties = plan.paragraph.find(qn("w", "pPr"))
    if properties is None:
        properties = Element(qn("w", "pPr"))
        plan.paragraph.insert(0, properties)
    existing = properties.find(qn("w", "numPr"))
    if existing is not None:
        properties.remove(existing)
    numbering = SubElement(properties, qn("w", "numPr"))
    SubElement(numbering, qn("w", "ilvl"), {qn("w", "val"): str(plan.value["numbering"]["level"])})
    SubElement(numbering, qn("w", "numId"), {qn("w", "val"): plan.value["numbering"]["num_id"]})


def assert_numbering_plans(story: Story, plans: list[NumberingEditPlan]) -> dict[str, Any]:
    paragraphs = list(iter_paragraphs(story.root))
    for plan in plans:
        actual = paragraph_numbering(paragraphs[plan.paragraph_index])
        expected = {
            "numbering_id": plan.value["numbering"]["num_id"],
            "level": str(plan.value["numbering"]["level"]),
        }
        if actual != expected:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Paragraph numbering does not match the immutable edit plan.",
            )
    return {"verified_numbering_edits": len(plans)}


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)
