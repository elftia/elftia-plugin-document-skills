"""In-memory transactional PPTX package mutation with one final copy-through write."""

from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import fromstring

from .content_types import content_type_for, parse_content_types
from .package import OpcPackage, PreservationManifest
from .relationships import Relationship, parse_relationships


class MutablePptxPackage:
    """Accumulate a bounded edit batch without publishing partial state."""

    def __init__(self, source: OpcPackage) -> None:
        self.source = source
        self.parts = dict(source.parts)

    def xml(self, name: str) -> Element:
        payload = self.parts.get(name)
        if payload is None:
            raise KeyError(name)
        return fromstring(payload)

    @property
    def content_types(self) -> dict[str, str]:
        return parse_content_types(self.parts["[Content_Types].xml"])

    def content_type_for(self, name: str) -> str | None:
        return content_type_for(name, self.content_types)

    @property
    def relationships(self) -> list[Relationship]:
        members = set(self.parts)
        relationships: list[Relationship] = []
        for name in sorted(self.parts):
            if name.endswith(".rels"):
                relationships.extend(parse_relationships(name, self.parts[name], members))
        return relationships

    def part_rels(self, part_name: str) -> list[Relationship]:
        return [item for item in self.relationships if item.source_part == part_name]

    def set_part(self, name: str, payload: bytes) -> None:
        self.parts[name] = payload

    def remove_part(self, name: str) -> None:
        self.parts.pop(name, None)

    def emit(self, destination: str | Path) -> PreservationManifest:
        source_names = set(self.source.parts)
        output_names = set(self.parts)
        additions = {
            name: self.parts[name]
            for name in sorted(output_names - source_names)
        }
        removals = source_names - output_names
        changes = {
            name: self.parts[name]
            for name in sorted(source_names.intersection(output_names))
            if self.parts[name] != self.source.parts[name]
        }
        return self.source.write_copy(
            destination,
            changed_parts=changes,
            added_parts=additions,
            removed_parts=removals,
        )

    def as_readonly(self) -> Any:
        """Return self for projection helpers that accept the OpcPackage protocol."""

        return self
