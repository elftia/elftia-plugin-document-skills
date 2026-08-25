"""Deterministic style import and source-reference remapping for DOCX merge."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn
from .package import OpcPackage
from .xml_utils import xml_bytes

STYLES_PART = "word/styles.xml"
_DEPENDENCY_NAMES = ("basedOn", "link", "next")
_REFERENCE_NAMES = ("pStyle", "rStyle", "tblStyle")


@dataclass(frozen=True)
class StyleMergeResult:
    mappings: tuple[dict[str, Any], ...]
    payload: bytes | None


class StyleMergePlanner:
    def __init__(self, base: OpcPackage) -> None:
        self._original = base.parts.get(STYLES_PART)
        self._root = base.xml(STYLES_PART) if self._original is not None else None
        self._styles = _style_map(self._root, "base") if self._root is not None else {}
        self._mappings: list[dict[str, Any]] = []

    def merge_source(
        self,
        source: OpcPackage,
        source_index: int,
        copied_nodes: list[Element],
    ) -> None:
        source_payload = source.parts.get(STYLES_PART)
        if source_payload is None and self._root is None:
            return
        if source_payload is None or self._root is None:
            _enhancement("DOCX merge cannot synthesize a missing styles part.")
        source_root = source.xml(STYLES_PART)
        source_styles = _style_map(source_root, f"source-{source_index}")
        identities: dict[str, str] = {}
        actions: dict[str, str] = {}
        for style_id, source_style in source_styles.items():
            base_style = self._styles.get(style_id)
            if base_style is None:
                identities[style_id] = style_id
                actions[style_id] = "imported"
            elif xml_bytes(base_style) == xml_bytes(source_style):
                identities[style_id] = style_id
            else:
                identities[style_id] = _allocate_style_id(
                    style_id,
                    source_index,
                    set(self._styles) | set(identities.values()),
                )
                actions[style_id] = "renamed"
        for style_id, action in actions.items():
            target_id = identities[style_id]
            copied = deepcopy(source_styles[style_id])
            copied.attrib[qn("w", "styleId")] = target_id
            _rewrite_dependencies(copied, identities)
            self._root.append(copied)
            self._styles[target_id] = copied
            self._mappings.append(
                {
                    "source_index": source_index,
                    "source_style_id": style_id,
                    "target_style_id": target_id,
                    "action": action,
                }
            )
        for node in copied_nodes:
            _rewrite_references(node, identities)

    def finish(self) -> StyleMergeResult:
        if self._root is None or self._original is None:
            return StyleMergeResult(tuple(self._mappings), None)
        payload = xml_bytes(self._root)
        return StyleMergeResult(
            tuple(self._mappings),
            payload if payload != self._original else None,
        )


def _style_map(root: Element, label: str) -> dict[str, Element]:
    result: dict[str, Element] = {}
    for style in root.findall(qn("w", "style")):
        style_id = style.attrib.get(qn("w", "styleId"))
        if not style_id or style_id in result:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "DOCX styles contain an invalid or duplicate style id.",
                details={"source": label, "style_id": style_id},
            )
        result[style_id] = style
    return result


def _allocate_style_id(style_id: str, source_index: int, used: set[str]) -> str:
    prefix = f"Merge{source_index}_"
    base = f"{prefix}{style_id}"[:240]
    for suffix in ("", *(f"_{index}" for index in range(2, 10_001))):
        candidate = f"{base}{suffix}"
        if candidate not in used:
            return candidate
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "DOCX merge style id space is exhausted.",
    )


def _rewrite_dependencies(style: Element, identities: dict[str, str]) -> None:
    for name in _DEPENDENCY_NAMES:
        for node in style.iter(qn("w", name)):
            value = node.attrib.get(qn("w", "val"))
            if value in identities:
                node.attrib[qn("w", "val")] = identities[value]


def _rewrite_references(root: Element, identities: dict[str, str]) -> None:
    for name in _REFERENCE_NAMES:
        for node in root.iter(qn("w", name)):
            value = node.attrib.get(qn("w", "val"))
            if value in identities:
                node.attrib[qn("w", "val")] = identities[value]


def _enhancement(message: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
    )
