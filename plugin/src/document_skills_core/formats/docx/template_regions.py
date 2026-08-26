"""Restricted declarative paragraph repetition and conditions for templates."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import WORD_MAIN, qn
from .mapping import iter_paragraphs, map_paragraph
from .package import OpcPackage
from .template import TOKEN_PATTERN, _expected_node_texts, _valid_tokens
from .xml_utils import set_text, xml_bytes


@dataclass(frozen=True)
class TemplateRegionPlan:
    requested: int
    emitted_paragraphs: int
    removed_paragraphs: int
    regions: tuple[dict[str, Any], ...]
    changed_parts: dict[str, bytes]

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "emitted_paragraphs": self.emitted_paragraphs,
            "removed_paragraphs": self.removed_paragraphs,
            "regions": [dict(item) for item in self.regions],
        }


def plan_template_regions(
    package: OpcPackage,
    regions: list[dict[str, Any]],
) -> TemplateRegionPlan:
    if not regions:
        return TemplateRegionPlan(0, 0, 0, (), {})
    document = package.xml(WORD_MAIN)
    body = document.find(qn("w", "body"))
    if body is None:
        _failed("body-missing")
    paragraphs = list(iter_paragraphs(document))
    body_paragraphs = {id(item) for item in body.findall(qn("w", "p"))}
    selected: list[tuple[dict[str, Any], Any]] = []
    diagnostics: list[dict[str, Any]] = []
    emitted = 0
    removed = 0
    for region in regions:
        target = region["target"]
        index = target["paragraph_index"]
        if index >= len(paragraphs):
            _failed("paragraph-index", paragraph_index=index)
        paragraph = paragraphs[index]
        if id(paragraph) not in body_paragraphs:
            _failed("not-a-top-level-body-paragraph", paragraph_index=index)
        if paragraph.find(f"./{qn('w', 'pPr')}/{qn('w', 'sectPr')}") is not None:
            _failed("section-boundary", paragraph_index=index)
        mapped = map_paragraph(paragraph)
        if mapped.full_text != target["expected_text"]:
            _failed(
                "expected-text",
                paragraph_index=index,
                actual_text=mapped.full_text,
            )
        if mapped.protected_text:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Template regions do not clone or remove protected Word structures.",
                status="enhancement_required",
                details={"paragraph_index": index},
            )
        if region["type"] == "paragraph_repeat":
            used = _paragraph_tokens(paragraph)
            for item_index, item in enumerate(region["items"]):
                missing = sorted(used - set(item))
                unused = sorted(set(item) - used)
                if missing or unused:
                    raise DocumentSkillsError(
                        ErrorCode.VALIDATION_FAILED,
                        "Template repeat item keys must exactly match its paragraph tokens.",
                        details={
                            "paragraph_index": index,
                            "item_index": item_index,
                            "missing_variables": missing,
                            "unused_variables": unused,
                        },
                    )
            count = len(region["items"])
            emitted += count
            removed += 1
        else:
            count = 1 if region["include"] else 0
            emitted += count
            removed += 0 if region["include"] else 1
        diagnostics.append(
            {"type": region["type"], "paragraph_index": index, "emitted": count}
        )
        selected.append((region, paragraph))
    for region, paragraph in sorted(
        selected,
        key=lambda item: item[0]["target"]["paragraph_index"],
        reverse=True,
    ):
        if region["type"] == "paragraph_condition" and region["include"]:
            continue
        child_index = list(body).index(paragraph)
        body.remove(paragraph)
        if region["type"] == "paragraph_repeat":
            for offset, item in enumerate(region["items"]):
                clone = deepcopy(paragraph)
                _substitute_paragraph(clone, item)
                body.insert(child_index + offset, clone)
    changed = {WORD_MAIN: xml_bytes(document)} if removed or emitted else {}
    return TemplateRegionPlan(
        len(regions),
        emitted,
        removed,
        tuple(diagnostics),
        changed,
    )


def _paragraph_tokens(paragraph: Any) -> set[str]:
    tokens: set[str] = set()
    for group in map_paragraph(paragraph).groups:
        tokens.update(_valid_tokens(group.text))
    return tokens


def _substitute_paragraph(paragraph: Any, variables: dict[str, str]) -> None:
    for group in map_paragraph(paragraph).groups:
        matches = tuple(TOKEN_PATTERN.finditer(group.text))
        if not matches:
            _valid_tokens(group.text)
            continue
        expected = _expected_node_texts(group, matches, variables)
        for reference, text in zip(group.refs, expected, strict=True):
            set_text(reference.node, text)


def _failed(reason: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Template region selector did not match the immutable input.",
        details={"reason": reason, **details},
    )
