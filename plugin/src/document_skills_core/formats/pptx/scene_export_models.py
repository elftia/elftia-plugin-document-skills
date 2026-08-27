"""Small shared models for PPTX scene export."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SceneObjectProjection:
    slides: list[dict[str, Any]]
    svg_members: dict[str, bytes]
    asset_members: dict[str, bytes]
    source_mapping: list[dict[str, Any]]
    unsupported: list[dict[str, Any]]


class SceneProjectionUnsupported(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


__all__ = ["SceneObjectProjection", "SceneProjectionUnsupported"]
