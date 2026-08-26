"""Inert DOCX/DOTX template-base admission and private staging."""

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any
from xml.etree.ElementTree import tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import CONTENT_TYPES, CONTENT_TYPES_NS, WORD_MAIN
from .content_types import (
    WORD_DOCUMENT_MAIN_CONTENT_TYPE,
    WORD_TEMPLATE_MAIN_CONTENT_TYPE,
)
from .package import OpcPackage, PreservationManifest


@dataclass(frozen=True)
class TemplateBasePlan:
    input_format: str
    converted_main_content_type: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_format": self.input_format,
            "output_format": "docx",
            "converted_main_content_type": self.converted_main_content_type,
        }

    @property
    def allowed_changed_parts(self) -> set[str]:
        return {CONTENT_TYPES} if self.converted_main_content_type else set()


def open_template_base(path: Path) -> tuple[OpcPackage, TemplateBasePlan]:
    input_format = path.suffix.casefold().lstrip(".")
    converted = input_format == "dotx"
    package = OpcPackage.open(path, allow_template_main=converted)
    expected = (
        WORD_TEMPLATE_MAIN_CONTENT_TYPE
        if converted
        else WORD_DOCUMENT_MAIN_CONTENT_TYPE
    )
    if package.content_type_for(WORD_MAIN) != expected:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Template base main content type does not match its extension.",
            details={"input_format": input_format},
        )
    return package, TemplateBasePlan(input_format, converted)


def stage_template_base(
    package: OpcPackage,
    source: Path,
    private_root: Path,
    plan: TemplateBasePlan,
    *,
    additional_changed_parts: dict[str, bytes] | None = None,
) -> Path:
    staged = private_root / "template-input.docx"
    changed_parts = dict(additional_changed_parts or {})
    if not plan.converted_main_content_type and not changed_parts:
        shutil.copyfile(source, staged)
        return staged
    if plan.converted_main_content_type:
        root = package.xml(CONTENT_TYPES)
        overrides = [
            node
            for node in root.findall(f"{{{CONTENT_TYPES_NS}}}Override")
            if node.attrib.get("PartName") == f"/{WORD_MAIN}"
        ]
        if (
            len(overrides) != 1
            or overrides[0].attrib.get("ContentType")
            != WORD_TEMPLATE_MAIN_CONTENT_TYPE
        ):
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "DOTX main content-type declaration is ambiguous.",
            )
        overrides[0].attrib["ContentType"] = WORD_DOCUMENT_MAIN_CONTENT_TYPE
        changed_parts[CONTENT_TYPES] = tostring(
            root,
            encoding="utf-8",
            xml_declaration=True,
        )
    package.write_copy(
        staged,
        changed_parts=changed_parts,
    )
    return staged


def compare_template_base_preservation(
    source: OpcPackage,
    output: Path,
    *,
    story_parts: tuple[str, ...],
    base_plan: TemplateBasePlan,
    additional_changed_parts: set[str] | None = None,
) -> PreservationManifest:
    output_package = OpcPackage.open(output)
    return source.compare_preservation(
        output_package,
        allowed_changed=(
            set(story_parts)
            | base_plan.allowed_changed_parts
            | (additional_changed_parts or set())
        ),
    )
