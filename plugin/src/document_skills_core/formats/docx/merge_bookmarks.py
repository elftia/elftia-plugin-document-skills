"""Bookmark id/name and internal-link remapping for merged DOCX bodies."""

from dataclasses import dataclass
import re
from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn

_BOOKMARK_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")


@dataclass(frozen=True)
class BookmarkMergeResult:
    mappings: tuple[dict[str, Any], ...]


class BookmarkMergePlanner:
    def __init__(self, base_body: Element) -> None:
        starts = _bookmark_starts([base_body], "base")
        _assert_matching_ends([base_body], starts, "base")
        self._used_ids = {int(bookmark_id) for bookmark_id in starts}
        self._used_names = set(starts.values())
        self._mappings: list[dict[str, Any]] = []

    def merge_source(
        self,
        source_index: int,
        copied_nodes: list[Element],
    ) -> None:
        starts = _bookmark_starts(copied_nodes, f"source-{source_index}")
        ends = _assert_matching_ends(
            copied_nodes,
            starts,
            f"source-{source_index}",
        )
        id_map: dict[str, str] = {}
        name_map: dict[str, str] = {}
        for source_id, source_name in starts.items():
            target_id = str(_allocate_number(self._used_ids))
            target_name = _allocate_name(
                source_name,
                source_index,
                self._used_names,
            )
            id_map[source_id] = target_id
            name_map[source_name] = target_name
            self._mappings.append(
                {
                    "source_index": source_index,
                    "source_id": source_id,
                    "target_id": target_id,
                    "source_name": source_name,
                    "target_name": target_name,
                }
            )
        for node in _iter_nodes(copied_nodes, qn("w", "bookmarkStart")):
            source_id = node.attrib[qn("w", "id")]
            source_name = node.attrib[qn("w", "name")]
            node.attrib[qn("w", "id")] = id_map[source_id]
            node.attrib[qn("w", "name")] = name_map[source_name]
        for node in ends:
            node.attrib[qn("w", "id")] = id_map[node.attrib[qn("w", "id")]]
        for hyperlink in _iter_nodes(copied_nodes, qn("w", "hyperlink")):
            anchor = hyperlink.attrib.get(qn("w", "anchor"))
            if hyperlink.attrib.get(qn("r", "id")) is not None or anchor not in name_map:
                _enhancement(
                    "DOCX merge supports only source-local internal bookmark hyperlinks.",
                    source_index=source_index,
                    anchor=anchor,
                )
            hyperlink.attrib[qn("w", "anchor")] = name_map[anchor]

    def finish(self) -> BookmarkMergeResult:
        return BookmarkMergeResult(tuple(self._mappings))


def _bookmark_starts(nodes: list[Element], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    names: set[str] = set()
    for node in _iter_nodes(nodes, qn("w", "bookmarkStart")):
        bookmark_id = node.attrib.get(qn("w", "id"))
        name = node.attrib.get(qn("w", "name"))
        if (
            bookmark_id is None
            or not bookmark_id.isdigit()
            or not name
            or bookmark_id in result
            or name in names
        ):
            _unsafe(
                "DOCX merge found invalid or duplicate bookmarks.",
                source=label,
                bookmark_id=bookmark_id,
                bookmark_name=name,
            )
        result[bookmark_id] = name
        names.add(name)
    return result


def _assert_matching_ends(
    nodes: list[Element],
    starts: dict[str, str],
    label: str,
) -> list[Element]:
    ends = list(_iter_nodes(nodes, qn("w", "bookmarkEnd")))
    end_ids = [node.attrib.get(qn("w", "id")) for node in ends]
    if len(end_ids) != len(set(end_ids)) or set(end_ids) != set(starts):
        _unsafe(
            "DOCX merge bookmarks do not have exact start/end pairs.",
            source=label,
        )
    return ends


def _iter_nodes(nodes: list[Element], tag: str):
    for root in nodes:
        yield from root.iter(tag)


def _allocate_number(used: set[int]) -> int:
    candidate = 0
    while candidate in used:
        candidate += 1
    used.add(candidate)
    return candidate


def _allocate_name(source: str, source_index: int, used: set[str]) -> str:
    if source not in used:
        used.add(source)
        return source
    if _BOOKMARK_NAME.fullmatch(source) is None:
        _enhancement(
            "DOCX merge cannot safely rename a colliding non-portable bookmark.",
            bookmark_name=source,
        )
    prefix = f"Merge{source_index}_"
    base = f"{prefix}{source}"[:40]
    for suffix in ("", *(f"_{index}" for index in range(2, 10_001))):
        candidate = f"{base[: 40 - len(suffix)]}{suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "DOCX merge bookmark name space is exhausted.",
    )


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
