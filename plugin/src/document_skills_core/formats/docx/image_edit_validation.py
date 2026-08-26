"""Reopen assertions for planned DOCX image mutations."""

from hashlib import sha256
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import WORD_MAIN, qn
from .drawing import crop_attributes, image_dimensions_emu
from .image_editing import ImageEditPlan, drawings_for_relationship
from .mapping import Story
from .package import OpcPackage
from .relationships import relationship_map


def assert_image_plans(
    package: OpcPackage,
    body: Story,
    plans: list[ImageEditPlan],
) -> dict[str, Any]:
    verified = []
    for plan in plans:
        drawings = drawings_for_relationship(body.root, plan.relationship_id)
        if len(drawings) != 1:
            _candidate_failed(plan.relationship_id, "drawing-reference-count")
        drawing = drawings[0]
        properties = list(drawing.iter(qn("wp", "docPr")))
        extents = list(drawing.iter(qn("wp", "extent")))
        relationship = relationship_map(
            package.relationships, WORD_MAIN
        ).get(plan.relationship_id)
        width, height = image_dimensions_emu(plan.image)
        payload = package.parts.get(plan.target_part)
        source_rectangles = list(drawing.iter(qn("a", "srcRect")))
        expected_crop = crop_attributes(plan.image.get("crop"))
        actual_crop = (
            dict(source_rectangles[0].attrib) if len(source_rectangles) == 1 else None
        )
        if (
            len(properties) != 1
            or len(extents) != 1
            or relationship is None
            or relationship.resolved_target != plan.target_part
            or properties[0].attrib.get("descr", "") != plan.image["alt_text"]
            or extents[0].attrib.get("cx") != str(width)
            or extents[0].attrib.get("cy") != str(height)
            or payload is None
            or sha256(payload).digest() != sha256(plan.image["bytes"]).digest()
            or actual_crop != expected_crop
            or (expected_crop is None and source_rectangles)
        ):
            _candidate_failed(plan.relationship_id, "image-semantics")
        verified.append(
            {
                "type": plan.kind,
                "relationship_id": plan.relationship_id,
                "target_part": plan.target_part,
                "media_sha256": sha256(plan.image["bytes"]).hexdigest(),
            }
        )
    return {"verified_images": verified}


def _candidate_failed(relationship_id: str, reason: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Edited DOCX image does not match the immutable image plan.",
        details={"relationship_id": relationship_id, "reason": reason},
    )
