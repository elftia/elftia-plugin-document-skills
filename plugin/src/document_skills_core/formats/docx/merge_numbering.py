"""Deterministic Word numbering graph remapping for DOCX merge."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS, qn
from .package import OpcPackage
from .xml_utils import xml_bytes

NUMBERING_PART = "word/numbering.xml"


@dataclass(frozen=True)
class NumberingMergeResult:
    abstract_mappings: tuple[dict[str, Any], ...]
    num_mappings: tuple[dict[str, Any], ...]
    payload: bytes | None


class NumberingMergePlanner:
    def __init__(self, base: OpcPackage) -> None:
        self._original = base.parts.get(NUMBERING_PART)
        self._root = base.xml(NUMBERING_PART) if self._original is not None else None
        self._abstract_ids = _ids(self._root, "abstractNum", "abstractNumId", "base")
        self._num_ids = _ids(self._root, "num", "numId", "base")
        self._abstract_mappings: list[dict[str, Any]] = []
        self._num_mappings: list[dict[str, Any]] = []

    def merge_source(
        self,
        source: OpcPackage,
        source_index: int,
        copied_nodes: list[Element],
    ) -> None:
        source_payload = source.parts.get(NUMBERING_PART)
        if source_payload is None and self._root is None:
            return
        if source_payload is None or self._root is None:
            _enhancement("DOCX merge cannot synthesize a missing numbering part.")
        source_root = source.xml(NUMBERING_PART)
        source_abstract = _elements_by_id(
            source_root,
            "abstractNum",
            "abstractNumId",
            f"source-{source_index}",
        )
        source_nums = _elements_by_id(
            source_root,
            "num",
            "numId",
            f"source-{source_index}",
        )
        abstract_map = _allocate_ids(source_abstract, self._abstract_ids)
        num_map = _allocate_ids(source_nums, self._num_ids)
        abstract_insert = next(
            (
                index
                for index, child in enumerate(list(self._root))
                if child.tag == qn("w", "num")
            ),
            len(self._root),
        )
        for source_id, source_element in source_abstract.items():
            copied = deepcopy(source_element)
            _reject_relationship_bound(copied, source_index)
            target_id = abstract_map[source_id]
            copied.attrib[qn("w", "abstractNumId")] = target_id
            self._root.insert(abstract_insert, copied)
            abstract_insert += 1
            self._abstract_mappings.append(
                {
                    "source_index": source_index,
                    "source_id": source_id,
                    "target_id": target_id,
                }
            )
        for source_id, source_element in source_nums.items():
            copied = deepcopy(source_element)
            target_id = num_map[source_id]
            copied.attrib[qn("w", "numId")] = target_id
            abstract_reference = copied.find(qn("w", "abstractNumId"))
            referenced = (
                abstract_reference.attrib.get(qn("w", "val"))
                if abstract_reference is not None
                else None
            )
            if referenced not in abstract_map:
                _unsafe(
                    "DOCX numbering instance has an unknown abstract numbering id.",
                    source_index=source_index,
                    num_id=source_id,
                )
            abstract_reference.attrib[qn("w", "val")] = abstract_map[referenced]
            self._root.append(copied)
            self._num_mappings.append(
                {
                    "source_index": source_index,
                    "source_id": source_id,
                    "target_id": target_id,
                }
            )
        for node in copied_nodes:
            for reference in node.iter(qn("w", "numId")):
                source_id = reference.attrib.get(qn("w", "val"))
                if source_id in num_map:
                    reference.attrib[qn("w", "val")] = num_map[source_id]

    def finish(self) -> NumberingMergeResult:
        if self._root is None or self._original is None:
            return NumberingMergeResult((), (), None)
        payload = xml_bytes(self._root)
        return NumberingMergeResult(
            tuple(self._abstract_mappings),
            tuple(self._num_mappings),
            payload if payload != self._original else None,
        )


def _elements_by_id(
    root: Element,
    element_name: str,
    attribute_name: str,
    label: str,
) -> dict[str, Element]:
    result: dict[str, Element] = {}
    for element in root.findall(qn("w", element_name)):
        value = element.attrib.get(qn("w", attribute_name))
        if value is None or not value.isdigit() or value in result:
            _unsafe(
                "DOCX numbering contains an invalid or duplicate id.",
                source=label,
                element=element_name,
                value=value,
            )
        result[value] = element
    return result


def _ids(
    root: Element | None,
    element_name: str,
    attribute_name: str,
    label: str,
) -> set[str]:
    if root is None:
        return set()
    return set(_elements_by_id(root, element_name, attribute_name, label))


def _allocate_ids(elements: dict[str, Element], used: set[str]) -> dict[str, str]:
    current = max((int(value) for value in used), default=0)
    result: dict[str, str] = {}
    for source_id in elements:
        current += 1
        while str(current) in used:
            current += 1
        target = str(current)
        used.add(target)
        result[source_id] = target
    return result


def _reject_relationship_bound(root: Element, source_index: int) -> None:
    relationship_prefix = f"{{{NS['r']}}}"
    if any(
        name.startswith(relationship_prefix)
        for element in root.iter()
        for name in element.attrib
    ):
        _enhancement(
            f"DOCX merge source {source_index} numbering has relationship-bound content."
        )


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)


def _enhancement(message: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
    )
