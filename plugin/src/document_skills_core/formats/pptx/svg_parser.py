"""Secure closed-profile SVG compiler into the shared normalized scene."""

from collections import Counter
import math
from pathlib import Path
import re
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import fromstring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .scene import SCENE_LIMITS
from .scene_normalizer import NormalizedScene
from .svg_geometry import Matrix, multiply, parse_transform
from .svg_item_projection import SvgItemProjectionMixin
from .svg_profile import SvgProfile
from .svg_values import (
    GRAPHICS,
    MAX_GROUP_DEPTH,
    MAX_NODES,
    MAX_SVG_BYTES,
    SOURCE_ID,
    SVG_NAMESPACE,
    UNSAFE_TAGS,
    local as _local,
    namespace as _namespace,
    positive_number as _positive_number,
    union_bounds as _union_bounds,
    unit_interval as _unit_interval,
)


class _SvgCompiler(SvgItemProjectionMixin):
    def __init__(self, source: Path, fallback_policy: str) -> None:
        self.source = source
        self.fallback_policy = fallback_policy
        self.assets: dict[str, dict[str, Any]] = {}
        self.profile = SvgProfile()
        self.source_ids: set[str] = set()
        self.nodes = 0
        self.path_commands = 0
        self.approximations = 0

    def compile(self) -> NormalizedScene:
        payload = self.source.read_bytes()
        if not payload or len(payload) > MAX_SVG_BYTES:
            self._invalid("SVG input is empty or exceeds the byte ceiling.")
        lowered = payload.lower()
        if b"<!doctype" in lowered or b"<!entity" in lowered:
            self._unsafe("SVG DTD and entity declarations are forbidden.")
        try:
            root = fromstring(payload)
        except Exception as error:
            self._unsafe("SVG XML is malformed.", reason=type(error).__name__)
        if _local(root.tag) != "svg" or _namespace(root.tag) != SVG_NAMESPACE:
            self._invalid("SVG root namespace is unsupported.")
        self._count_tree(root)
        viewport = self._viewport(root)
        self.profile.definitions(root)
        inherited = {
            "fill": "#000000",
            "fill-opacity": "1",
            "font-family": "Arial",
            "font-size": "16",
            "font-style": "normal",
            "font-weight": "400",
            "stroke": "transparent",
            "stroke-opacity": "1",
            "stroke-width": "0",
            "text-anchor": "start",
            "text-decoration": "none",
        }
        items: list[dict[str, Any]] = []
        for index, child in enumerate(root):
            if _local(child.tag) == "defs":
                continue
            items.extend(
                self._walk(
                    child,
                    viewport,
                    inherited,
                    1.0,
                    parent_id=None,
                    source_path=f"root-{index + 1}",
                )
            )
        if not items:
            self._invalid("SVG contains no editable drawing nodes.")
        return self._normalized_scene(payload, items)

    def _walk(
        self,
        element: Element,
        parent_matrix: Matrix,
        inherited: dict[str, str],
        parent_opacity: float,
        *,
        parent_id: str | None,
        source_path: str,
    ) -> list[dict[str, Any]]:
        tag = _local(element.tag)
        if tag in UNSAFE_TAGS or tag not in GRAPHICS | {"g"}:
            self._unsafe("SVG element is outside the closed profile.", element=tag)
        self.profile.validate_attributes(element, tag)
        source_id = self._source_id(element, source_path)
        style = self.profile.style(element, inherited)
        opacity = parent_opacity * _unit_interval(
            style.pop("opacity", "1"),
            "opacity",
        )
        matrix = multiply(
            parent_matrix,
            parse_transform(element.attrib.get("transform")),
        )
        if tag == "g":
            if "data-elftia-kind" in element.attrib:
                return [
                    self._semantic_group(
                        element,
                        source_id,
                        parent_id,
                        matrix,
                        opacity,
                    )
                ]
            children: list[dict[str, Any]] = []
            for index, child in enumerate(element):
                children.extend(
                    self._walk(
                        child,
                        matrix,
                        style,
                        opacity,
                        parent_id=source_id,
                        source_path=f"{source_path}-{index + 1}",
                    )
                )
            if not children:
                self._invalid(
                    "SVG groups must contain at least one drawing node.",
                    source_id=source_id,
                )
            geometry = _union_bounds(children)
            group = self._base_item(
                source_id,
                parent_id,
                "group",
                geometry,
                opacity=opacity,
                fill="transparent",
                stroke="transparent",
                stroke_width=0.0,
            )
            return [group, *children]
        item = self._graphic(
            element,
            tag,
            source_id,
            parent_id,
            matrix,
            style,
            opacity,
        )
        filter_value = element.attrib.get("filter")
        if filter_value is not None:
            expected = re.fullmatch(
                r"url\(#([A-Za-z][A-Za-z0-9_.:-]{0,79})\)",
                filter_value,
            )
            if expected is None or expected.group(1) not in self.profile.filter_ids:
                self._unsafe(
                    "SVG filter reference is invalid or external.",
                    source_id=source_id,
                )
            item = self._element_fallback(element, item)
        return [item]

    def _normalized_scene(
        self,
        payload: bytes,
        items: list[dict[str, Any]],
    ) -> NormalizedScene:
        outcomes = Counter(item["outcome"] for item in items)
        kinds = Counter(item["kind"] for item in items)
        text_bytes = sum(len(item["text"].encode("utf-8")) for item in items)
        asset_bytes = sum(int(asset["bytes"]) for asset in self.assets.values())
        observed = {
            "slides": 1,
            "dom_nodes": self.nodes,
            "paint_items": len(items),
            "text_bytes": text_bytes,
            "image_bytes": asset_bytes,
            "image_pixels": sum(
                asset["width"] * asset["height"] for asset in self.assets.values()
            ),
            "images": sum(item["kind"] == "image" for item in items),
            "assets": len(self.assets),
            "total_asset_bytes": asset_bytes,
            "resource_requests": len(self.assets),
            "scene_bytes": len(payload),
            "capture_bytes": len(payload) + asset_bytes,
        }
        for key, ceiling in SCENE_LIMITS.items():
            if observed.get(key, 0) > ceiling:
                self._invalid(
                    "Compiled SVG scene exceeds the shared scene policy.",
                    limit=key,
                )
        fidelity = {
            outcome: {
                "count": outcomes.get(outcome, 0),
                "area": sum(
                    item["width"] * item["height"]
                    for item in items
                    if item["outcome"] == outcome
                ),
                "by_reason": dict(
                    sorted(
                        Counter(
                            item["outcome_reason"]
                            for item in items
                            if item["outcome"] == outcome
                            and item["outcome_reason"]
                        ).items()
                    )
                ),
                "samples": [],
                "truncated": 0,
            }
            for outcome in ("native", "approximated", "rasterized")
        }
        diagnostics = {
            "outcomes": dict(sorted(outcomes.items())),
            "kinds": dict(sorted(kinds.items())),
            "reasons": dict(
                sorted(
                    Counter(
                        item["outcome_reason"]
                        for item in items
                        if item["outcome_reason"]
                    ).items()
                )
            ),
            "fidelity": fidelity,
            "unsupported_css": {
                "total": 0,
                "by_reason": {},
                "samples": [],
                "truncated": 0,
            },
            "unknown_hints": {"total": 0, "samples": [], "truncated": 0},
            "blocked_resources": {
                "total": 0,
                "by_reason": {},
                "samples": [],
                "truncated": 0,
            },
            "font_evidence": {
                "total": sum(bool(item["text"]) for item in items),
                "substitutions": 0,
                "samples": [],
                "truncated": 0,
                "capture_truncated": 0,
            },
            "duplicate_descendants_suppressed": 0,
            "limits": {"observed": observed, "ceilings": dict(SCENE_LIMITS)},
            "svg": {
                "gradients": len(self.profile.gradients),
                "nodes": self.nodes,
                "path_commands": self.path_commands,
                "whole_slide_fallbacks": 0,
            },
        }
        return NormalizedScene(
            slides=(tuple(items),),
            assets=self.assets,
            diagnostics=diagnostics,
            visual_sources=(),
            slide_fills=("transparent",),
        )

    def _viewport(self, root: Element) -> Matrix:
        allowed = {"height", "id", "viewBox", "width"}
        if set(root.attrib) - allowed:
            self._invalid(
                "SVG root attributes are outside the explicit viewport profile."
            )
        width = _positive_number(root.attrib.get("width"), "width")
        height = _positive_number(root.attrib.get("height"), "height")
        view_box = root.attrib.get("viewBox")
        values = (
            []
            if view_box is None
            else [
                float(item)
                for item in re.split(r"[ ,]+", view_box.strip())
                if item
            ]
        )
        if (
            len(values) != 4
            or values[2] <= 0
            or values[3] <= 0
            or not all(math.isfinite(item) for item in values)
        ):
            self._invalid("SVG requires an explicit finite viewBox.")
        if (
            abs(width / height - values[2] / values[3]) > 1e-6
            or abs(values[2] / values[3] - 16 / 9) > 1e-6
        ):
            self._invalid("SVG viewport must use the fixed 16:9 scene aspect ratio.")
        scale = 1920 / values[2]
        return (
            scale,
            0.0,
            0.0,
            scale,
            -values[0] * scale,
            -values[1] * scale,
        )

    def _source_id(self, element: Element, generated: str) -> str:
        source_id = element.attrib.get("id") or f"node-{generated}"
        if SOURCE_ID.fullmatch(source_id) is None or source_id in self.source_ids:
            self._invalid(
                "SVG node identity is invalid or duplicated.",
                source_id=source_id,
            )
        self.source_ids.add(source_id)
        return source_id

    def _count_tree(self, root: Element) -> None:
        stack = [(root, 0)]
        while stack:
            node, depth = stack.pop()
            if _namespace(node.tag) != SVG_NAMESPACE:
                self._unsafe("SVG contains a foreign XML namespace.")
            if depth > MAX_GROUP_DEPTH:
                raise DocumentSkillsError(
                    ErrorCode.RESOURCE_LIMIT,
                    "SVG group nesting exceeds policy.",
                    status="failed",
                    details={"limit": MAX_GROUP_DEPTH},
                )
            self.nodes += 1
            if self.nodes > MAX_NODES:
                self._invalid("SVG node count exceeds policy.")
            stack.extend((child, depth + 1) for child in reversed(list(node)))

    @staticmethod
    def _invalid(message: str, **details: Any) -> None:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            message,
            status="invalid_request",
            details=details,
        )

    @staticmethod
    def _unsafe(message: str, **details: Any) -> None:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            message,
            status="failed",
            details=details,
        )


def compile_svg_scene(source: Path, *, fallback_policy: str) -> NormalizedScene:
    candidate = source.expanduser()
    if candidate.is_symlink():
        raise DocumentSkillsError(
            ErrorCode.INPUT_NOT_FOUND,
            "SVG input must be a regular .svg file.",
        )
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or resolved.suffix.casefold() != ".svg":
        raise DocumentSkillsError(
            ErrorCode.INPUT_NOT_FOUND,
            "SVG input must be a regular .svg file.",
        )
    if fallback_policy not in {"element-rasterize", "reject"}:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "SVG fallback policy is invalid.",
            status="invalid_request",
        )
    return _SvgCompiler(resolved, fallback_policy).compile()


__all__ = ["compile_svg_scene"]
