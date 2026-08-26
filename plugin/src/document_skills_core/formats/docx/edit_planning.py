"""Immutable-input planning for the composite typed DOCX edit transaction."""

from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .content_control_editing import (
    ContentControlEditPlan,
    ContentControlMutationState,
)
from .constants import qn
from .field_editing import FieldEditPlan, FieldMutationState
from .formatting import available_paragraph_styles
from .image_editing import ImageEditPlan, ImageMutationState
from .link_editing import LinkEditPlan, LinkMutationState
from .mapping import Story, document_stories, iter_paragraphs, map_paragraph
from .note_editing import NoteEditPlan, NoteMutationState
from .numbering_editing import NumberingEditPlan, NumberingMutationState
from .package import OpcPackage
from .run_editing import plan_run_matches
from .section_editing import SectionEditPlan, SectionMutationState
from .table_editing import TableEditPlan, TableMutationState


@dataclass(frozen=True)
class PlannedEdit:
    value: dict[str, Any]
    paragraph: Element | None = None
    parent: Element | None = None
    runs: tuple[Element, ...] = ()
    image: ImageEditPlan | None = None
    table: TableEditPlan | None = None
    section: SectionEditPlan | None = None
    link: LinkEditPlan | None = None
    field: FieldEditPlan | None = None
    note: NoteEditPlan | None = None
    content_control: ContentControlEditPlan | None = None
    numbering: NumberingEditPlan | None = None
    part: str | None = None
    story_root: Element | None = None


def plan_edits(
    package: OpcPackage,
    body: Story,
    edits: list[dict[str, Any]],
) -> tuple[
    list[PlannedEdit],
    ImageMutationState | None,
    TableMutationState | None,
    SectionMutationState | None,
    LinkMutationState | None,
    FieldMutationState | None,
    NoteMutationState | None,
    ContentControlMutationState | None,
    NumberingMutationState | None,
]:
    paragraphs = list(iter_paragraphs(body.root))
    direct_parent = body.root.find(qn("w", "body"))
    if direct_parent is None:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "DOCX body is missing during edit planning.",
        )
    parents = {id(child): parent for parent in body.root.iter() for child in parent}
    stories_by_part = {
        story.part: story
        for story in document_stories(package, include_headers_footers=True)
    }
    stories_by_part[body.part] = body
    available_styles = available_paragraph_styles(package)
    plan: list[PlannedEdit] = []
    deleted: set[int] = set()
    inserted: set[tuple[int, str]] = set()
    paragraph_styled: set[int] = set()
    image_state = (
        ImageMutationState.open(package, body)
        if any(edit["type"].startswith("image_") for edit in edits)
        else None
    )
    table_state = (
        TableMutationState.open(body)
        if any(edit["type"].startswith("table_") for edit in edits)
        else None
    )
    section_state = (
        SectionMutationState.open(package, body)
        if any(
            edit["type"] in {"header_footer_update", "section_update"}
            for edit in edits
        )
        else None
    )
    link_state = (
        LinkMutationState.open(body)
        if any(
            edit["type"]
            in {"bookmark_insert", "hyperlink_insert", "hyperlink_update"}
            for edit in edits
        )
        else None
    )
    field_state = (
        FieldMutationState(body)
        if any(
            edit["type"] in {"field_insert", "field_refresh", "toc_insert"}
            for edit in edits
        )
        else None
    )
    note_state = (
        NoteMutationState(package, body)
        if any(edit["type"] in {"note_delete", "note_insert"} for edit in edits)
        else None
    )
    content_control_state = (
        ContentControlMutationState(body)
        if any(edit["type"] == "content_control_text_update" for edit in edits)
        else None
    )
    numbering_state = (
        NumberingMutationState(package)
        if any(edit["type"] == "paragraph_numbering_update" for edit in edits)
        else None
    )
    if image_state is not None and any(
        edit["type"] == "header_footer_update" for edit in edits
    ):
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Image and header/footer graph edits must use separate transactions.",
            status="invalid_request",
        )

    for edit in edits:
        edit_type = edit["type"]
        if edit_type == "field_refresh":
            assert field_state is not None
            plan.append(
                PlannedEdit(edit, field=field_state.plan_refresh(edit))
            )
            continue
        if edit_type == "note_delete":
            assert note_state is not None
            plan.append(PlannedEdit(edit, note=note_state.plan_delete(edit)))
            continue
        if edit_type == "content_control_text_update":
            assert content_control_state is not None
            plan.append(
                PlannedEdit(
                    edit,
                    content_control=content_control_state.plan(edit),
                )
            )
            continue
        if edit_type == "image_replace":
            assert image_state is not None
            plan.append(PlannedEdit(edit, image=image_state.plan_replace(edit)))
            continue
        if edit_type.startswith("table_") and edit_type != "table_insert":
            assert table_state is not None
            plan.append(PlannedEdit(edit, table=table_state.plan(edit)))
            continue
        if edit_type in {"header_footer_update", "section_update"}:
            assert section_state is not None
            plan.append(PlannedEdit(edit, section=section_state.plan(edit)))
            continue
        target = edit["target"]
        target_story = body
        target_paragraphs = paragraphs
        target_parents = parents
        if edit_type in {"paragraph_style", "run_style"}:
            target_part = target.get("part", body.part)
            target_story = stories_by_part.get(target_part)
            if target_story is None or target_story.kind != target["story"]:
                _precondition_failed(
                    target["paragraph_index"],
                    "story-part",
                    story=target["story"],
                    part=target_part,
                )
            target_paragraphs = list(iter_paragraphs(target_story.root))
            target_parents = {
                id(child): parent
                for parent in target_story.root.iter()
                for child in parent
            }
        index = target["paragraph_index"]
        if index >= len(target_paragraphs):
            _precondition_failed(index, "paragraph-index")
        target_paragraph = target_paragraphs[index]
        mapped = map_paragraph(target_paragraph)
        actual_text = "".join(group.text for group in mapped.groups)
        if actual_text != target["expected_text"]:
            _precondition_failed(
                index,
                "expected-text",
                expected_text=target["expected_text"],
                actual_text=actual_text,
            )
        parent = target_parents.get(id(target_paragraph))
        if edit_type not in {"paragraph_style", "run_style"} and parent is not direct_parent:
            _precondition_failed(index, "not-a-top-level-body-paragraph")
        if target_paragraph.find(f"./{qn('w', 'pPr')}/{qn('w', 'sectPr')}") is not None:
            _precondition_failed(index, "section-boundary")
        if mapped.protected_text or mapped.hyperlink_ids:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Formatting edits do not target protected or hyperlink content.",
                status="enhancement_required",
                details={"paragraph_index": index},
            )

        paragraph_identity = id(target_paragraph)
        if edit_type == "paragraph_delete":
            if paragraph_identity in deleted or any(
                item.paragraph is target_paragraph for item in plan
            ):
                _conflicting_edit(index)
            deleted.add(paragraph_identity)
        elif paragraph_identity in deleted:
            _conflicting_edit(index)

        if edit_type in {"paragraph_insert", "paragraph_style"}:
            style = edit["style"]
            if style not in available_styles:
                _precondition_failed(index, "style-not-present", style=style)
        if edit_type in {"image_insert", "paragraph_insert", "table_insert"}:
            insertion = (paragraph_identity, edit["position"])
            if insertion in inserted:
                _conflicting_edit(index)
            inserted.add(insertion)
        if edit_type == "paragraph_style":
            if paragraph_identity in paragraph_styled:
                _conflicting_edit(index)
            paragraph_styled.add(paragraph_identity)

        runs: tuple[Element, ...] = ()
        image_plan = None
        table_plan = None
        link_plan = None
        field_plan = None
        note_plan = None
        numbering_plan = None
        if edit_type == "run_style":
            runs = plan_run_matches(mapped, edit, paragraph_index=index)
        elif edit_type == "image_insert":
            assert image_state is not None
            image_plan = image_state.plan_insert(
                edit,
                anchor=target_paragraph,
                parent=parent,
            )
        elif edit_type == "table_insert":
            assert table_state is not None
            table_plan = table_state.plan_insert(
                edit,
                anchor=target_paragraph,
                parent=parent,
            )
        elif edit_type in {"bookmark_insert", "hyperlink_insert", "hyperlink_update"}:
            assert link_state is not None
            link_plan = link_state.plan(
                edit,
                paragraph=target_paragraph,
                paragraph_index=index,
            )
        elif edit_type in {"field_insert", "toc_insert"}:
            assert field_state is not None
            field_plan = field_state.plan_insert(
                edit,
                paragraph=target_paragraph,
                parent=parent,
            )
        elif edit_type == "note_insert":
            assert note_state is not None
            note_plan = note_state.plan_insert(edit, target_paragraph)
        elif edit_type == "paragraph_numbering_update":
            assert numbering_state is not None
            numbering_plan = numbering_state.plan(
                edit,
                target_paragraph,
                index,
            )
        plan.append(
            PlannedEdit(
                edit,
                target_paragraph,
                parent,
                runs,
                image_plan,
                table_plan,
                None,
                link_plan,
                field_plan,
                note_plan,
                None,
                numbering_plan,
                target_story.part,
                target_story.root,
            )
        )
    return (
        plan,
        image_state,
        table_state,
        section_state,
        link_state,
        field_state,
        note_state,
        content_control_state,
        numbering_state,
    )


def _precondition_failed(
    paragraph_index: int,
    reason: str,
    **details: Any,
) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "DOCX edit selector precondition did not match the immutable input.",
        details={"paragraph_index": paragraph_index, "reason": reason, **details},
    )


def _conflicting_edit(paragraph_index: int) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        "DOCX edit transaction contains conflicting paragraph edits.",
        status="invalid_request",
        details={"paragraph_index": paragraph_index},
    )
