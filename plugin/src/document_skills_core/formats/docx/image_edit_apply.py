"""Apply an already-validated immutable DOCX image edit plan."""

from .drawing import image_paragraph, update_image_drawing
from .image_editing import ImageEditPlan


def apply_image_plan(plan: ImageEditPlan) -> None:
    if plan.kind == "image_insert":
        assert plan.parent is not None
        assert plan.anchor is not None
        assert plan.position is not None
        assert plan.document_properties_id is not None
        assert plan.picture_properties_id is not None
        position = list(plan.parent).index(plan.anchor)
        if plan.position == "after":
            position += 1
        plan.parent.insert(
            position,
            image_paragraph(
                {**plan.image, "relationship_id": plan.relationship_id},
                document_properties_id=plan.document_properties_id,
                document_name=f"Elftia image {plan.document_properties_id}",
                picture_properties_id=plan.picture_properties_id,
                picture_name=f"elftia-image-{plan.picture_properties_id}",
            ),
        )
        return
    assert plan.drawing is not None
    update_image_drawing(plan.drawing, plan.image)
