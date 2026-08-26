"""Reopen assertions for planned section and header/footer mutations."""

from hashlib import sha256
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn
from .package import OpcPackage
from .projection import project_sections
from .section_editing import SectionEditPlan


def assert_section_plans(
    package: OpcPackage,
    plans: list[SectionEditPlan],
) -> dict[str, Any]:
    sections = project_sections(package)
    section_nodes = list(package.xml("word/document.xml").iter(qn("w", "sectPr")))
    verified = []
    for plan in plans:
        if plan.section_index >= len(sections):
            _failed(plan, "section-index")
        actual = sections[plan.section_index]
        if plan.kind == "section_update":
            _assert_section_update(plan, actual)
        else:
            references = [
                item
                for item in actual["references"]
                if item["kind"] == plan.value["kind"]
                and item["reference_type"] == plan.value["variant"]
            ]
            if plan.value["link_to_previous"]:
                if references:
                    _failed(plan, "link-to-previous")
            else:
                expected_hash = sha256(package.parts[plan.target_part]).hexdigest()
                if (
                    len(references) != 1
                    or references[0]["target_part"] != plan.target_part
                    or references[0]["story_sha256"] != expected_hash
                ):
                    _failed(plan, "story-reference")
                if (
                    plan.value["variant"] == "first"
                    and section_nodes[plan.section_index].find(qn("w", "titlePg"))
                    is None
                ):
                    _failed(plan, "different-first-page")
                if plan.value["variant"] == "even":
                    settings = package.xml("word/settings.xml")
                    if settings.find(qn("w", "evenAndOddHeaders")) is None:
                        _failed(plan, "different-even-odd")
        verified.append(
            {
                "type": plan.kind,
                "section_index": plan.section_index,
            }
        )
    return {"verified_sections": verified}


def _assert_section_update(plan: SectionEditPlan, actual: dict[str, Any]) -> None:
    updates = plan.value
    if "orientation" in updates and actual["orientation"] != updates["orientation"]:
        _failed(plan, "orientation")
    if "break_type" in updates and actual["type"] != updates["break_type"]:
        _failed(plan, "break-type")
    if "page_size" in updates:
        expected = {
            "w": str(updates["page_size"]["width_twips"]),
            "h": str(updates["page_size"]["height_twips"]),
        }
        if actual["page_size"] != expected:
            _failed(plan, "page-size")
    if "margins" in updates:
        for name, value in updates["margins"].items():
            key = name.removesuffix("_twips")
            if actual["margins"].get(key) != str(value):
                _failed(plan, "margins")


def _failed(plan: SectionEditPlan, reason: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Edited DOCX section does not match the immutable section plan.",
        details={"section_index": plan.section_index, "reason": reason},
    )
