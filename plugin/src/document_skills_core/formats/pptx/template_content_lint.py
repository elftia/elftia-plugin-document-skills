"""Fail-closed content checks required before template candidate promotion."""

from __future__ import annotations

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS
from .mapping import map_slides
from .package import OpcPackage
from .template_descriptor import TemplateDescriptor

_A_TEXT = f"{{{NS['a']}}}t"
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}|\[placeholder\]|lorem ipsum|\bTODO\b", re.I)
_PROMOTIONAL = re.compile(r"buy this template|download the full template|template marketplace", re.I)
_NOTES_LEAK = re.compile(r"speaker only|do not share|internal script", re.I)


def validate_binding_plan(
    pages: list[dict[str, Any]],
    descriptor: TemplateDescriptor,
) -> dict[str, Any]:
    objects = descriptor.objects_by_id
    slots_by_slide: dict[str, list[dict[str, Any]]] = {}
    slide_by_slot: dict[str, str] = {}
    for slot in descriptor.semantic_slots["slots"]:
        deck_object = objects.get(slot["sourceObjectId"])
        if deck_object is None:
            continue
        slide, _ = deck_object
        slots_by_slide.setdefault(slide["slideId"], []).append(slot)
        slide_by_slot[slot["slotId"]] = slide["slideId"]
    findings: list[dict[str, Any]] = []
    binding_counts: dict[str, int] = {}
    selected_slides = {page["source_slide_id"] for page in pages}
    for page in pages:
        bound = {item["slot_id"]: item for item in page["bindings"]}
        for binding in page["bindings"]:
            slot_id = binding["slot_id"]
            binding_counts[slot_id] = binding_counts.get(slot_id, 0) + 1
            if slide_by_slot.get(slot_id) != page["source_slide_id"]:
                findings.append({
                    "code": "slot-not-on-source-slide",
                    "severity": "error",
                    "slot_id": slot_id,
                    "source_slide_id": page["source_slide_id"],
                })
        for slot in slots_by_slide.get(page["source_slide_id"], []):
            cardinality = slot["cardinality"]
            if cardinality["kind"] == "required" and slot["slotId"] not in bound:
                findings.append({
                    "code": "unbound-required-slot",
                    "severity": "error",
                    "slot_id": slot["slotId"],
                    "source_slide_id": page["source_slide_id"],
                })
            binding = bound.get(slot["slotId"])
            if binding is not None:
                findings.extend(_binding_capacity(slot, binding["value"]))
    for slot in descriptor.semantic_slots["slots"]:
        cardinality = slot["cardinality"]
        source_slide_id = slide_by_slot.get(slot["slotId"])
        if cardinality["kind"] != "repeated" or source_slide_id not in selected_slides:
            continue
        actual = binding_counts.get(slot["slotId"], 0)
        if actual < cardinality["min"] or actual > cardinality["max"]:
            findings.append({
                "actual": actual,
                "code": "repeated-slot-cardinality",
                "maximum": cardinality["max"],
                "minimum": cardinality["min"],
                "severity": "error",
                "slot_id": slot["slotId"],
                "source_slide_id": source_slide_id,
            })
    _raise_findings(findings)
    return {"findings": findings, "status": "passed"}


def lint_materialized_content(candidate: Any) -> dict[str, Any]:
    package = candidate if isinstance(candidate, OpcPackage) else OpcPackage.open(candidate)
    findings: list[dict[str, Any]] = []
    for slide in map_slides(package):
        part = slide.get("part")
        if part is None:
            continue
        for text in _part_text(package, part):
            if _PLACEHOLDER.search(text):
                findings.append(_finding("placeholder-content", part, text))
            if text.strip() in {"...", "…"}:
                findings.append(_finding("ellipsis-content", part, text))
            if _PROMOTIONAL.search(text):
                findings.append(_finding("promotional-content", part, text))
        notes = slide.get("notes")
        notes_part = None if notes is None else notes.get("part")
        if notes_part:
            for text in _part_text(package, notes_part):
                if _NOTES_LEAK.search(text):
                    findings.append(_finding("speaker-notes-leak", notes_part, text))
    _raise_findings(findings)
    return {"findings": findings, "status": "passed"}


def _binding_capacity(slot: dict[str, Any], value: dict[str, Any]) -> list[dict[str, Any]]:
    texts = _binding_texts(value)
    if not texts:
        return []
    content = "\n".join(texts)
    capacity = slot["capacity"]
    recommended = (
        capacity["cjkRecommendedCharacters"]
        if _CJK.search(content)
        else capacity["latinRecommendedCharacters"]
    )
    if len(content) <= recommended or capacity["overflowPolicy"] != "reject":
        return []
    return [{
        "actual_characters": len(content),
        "code": "slot-capacity-exceeded",
        "recommended_characters": recommended,
        "severity": "error",
        "slot_id": slot["slotId"],
    }]


def _binding_texts(value: dict[str, Any]) -> list[str]:
    if type(value) is not dict:
        return []
    kind = value.get("type")
    if kind == "text":
        return [value.get("text", "")]
    if kind == "rich-text":
        paragraphs = value.get("paragraphs", [])
        if type(paragraphs) is not list:
            return []
        return [item for item in paragraphs if type(item) is str]
    if kind in {"date", "number"}:
        return [str(value.get("value", ""))]
    if kind == "table-data":
        rows = value.get("rows", [])
        if type(rows) is not list or any(type(row) is not list for row in rows):
            return []
        return [str(cell) for row in rows for cell in row]
    return []


def _part_text(package: OpcPackage, part: str) -> list[str]:
    root = package.xml(part)
    return [node.text or "" for node in root.iter(_A_TEXT) if node.text]


def _finding(code: str, part: str, text: str) -> dict[str, Any]:
    return {
        "code": code,
        "part": part,
        "sample": text[:80],
        "severity": "error",
    }


def _raise_findings(findings: list[dict[str, Any]]) -> None:
    errors = [item for item in findings if item["severity"] == "error"]
    if errors:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Template content lint rejected the materialized candidate.",
            status="failed",
            details={"findings": errors[:64]},
        )
