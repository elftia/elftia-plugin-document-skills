"""Deterministic ID and name remapping for validated revision graphs."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from xml.etree.ElementTree import Element

from .constants import qn
from .merge_revision_graph import audit_revision_graph
from .merge_revision_types import MAX_REVISIONS, RevisionGraph, unsupported


@dataclass(frozen=True)
class RevisionMergeResult:
    mappings: tuple[dict[str, Any], ...]
    move_range_mappings: tuple[dict[str, Any], ...]
    move_name_mappings: tuple[dict[str, Any], ...]
    expected_count: int
    expected_move_range_count: int


class RevisionMergePlanner:
    def __init__(self, base_body: Element) -> None:
        base = audit_revision_graph(
            [base_body],
            document="base",
            source_index=None,
        )
        self.used_ids = set(base.annotation_ids)
        self.used_move_names = {
            move_range.name
            for move_range in base.move_ranges
            if move_range.range_type == "moveFrom"
        }
        self.mappings: list[dict[str, Any]] = []
        self.move_range_mappings: list[dict[str, Any]] = []
        self.move_name_mappings: list[dict[str, Any]] = []
        self.expected_count = len(base.revisions)
        self.expected_move_range_count = len(base.move_ranges)

    def merge_source(self, source_index: int, copied_nodes: list[Element]) -> None:
        graph = audit_revision_graph(
            copied_nodes,
            document="source",
            source_index=source_index,
        )
        self._remap_move_names(graph, source_index)
        for revision in graph.revisions:
            target_id = _allocate_revision_id(
                self.used_ids,
                int(revision.source_id),
            )
            revision.element.attrib[qn("w", "id")] = target_id
            self.mappings.append(
                {
                    "source_id": revision.source_id,
                    "source_index": source_index,
                    "target_id": target_id,
                    "type": revision.revision_type,
                }
            )
        for move_range in graph.move_ranges:
            target_id = _allocate_revision_id(
                self.used_ids,
                int(move_range.source_id),
            )
            move_range.start.attrib[qn("w", "id")] = target_id
            move_range.end.attrib[qn("w", "id")] = target_id
            self.move_range_mappings.append(
                {
                    "source_id": move_range.source_id,
                    "source_index": source_index,
                    "target_id": target_id,
                    "type": f"{move_range.range_type}Range",
                }
            )
        self.expected_count += len(graph.revisions)
        self.expected_move_range_count += len(graph.move_ranges)
        if len(self.used_ids) > MAX_REVISIONS:
            unsupported("DOCX merge revision count exceeds the supported bound.")

    def finish(self) -> RevisionMergeResult:
        return RevisionMergeResult(
            tuple(self.mappings),
            tuple(self.move_range_mappings),
            tuple(self.move_name_mappings),
            self.expected_count,
            self.expected_move_range_count,
        )

    def _remap_move_names(
        self,
        graph: RevisionGraph,
        source_index: int,
    ) -> None:
        names = sorted(
            {
                move_range.name
                for move_range in graph.move_ranges
                if move_range.range_type == "moveFrom"
            }
        )
        for source_name in names:
            target_name = _allocate_move_name(
                self.used_move_names,
                source_name,
                source_index,
            )
            if target_name == source_name:
                continue
            for move_range in graph.move_ranges:
                if move_range.name == source_name:
                    move_range.start.attrib[qn("w", "name")] = target_name
            self.move_name_mappings.append(
                {
                    "source_index": source_index,
                    "source_name": source_name,
                    "target_name": target_name,
                }
            )


def _allocate_revision_id(used: set[int], preferred: int) -> str:
    candidate = preferred
    if candidate in used:
        candidate = 1
        while candidate in used:
            candidate += 1
    used.add(candidate)
    return str(candidate)


def _allocate_move_name(
    used: set[str],
    preferred: str,
    source_index: int,
) -> str:
    if preferred not in used:
        used.add(preferred)
        return preferred
    digest = sha256(preferred.encode("utf-8", errors="strict")).hexdigest()[:16]
    base = f"move_{source_index}_{digest}"
    candidate = base
    counter = 2
    while candidate in used:
        candidate = f"{base}_{counter}"
        counter += 1
    used.add(candidate)
    return candidate
