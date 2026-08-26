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
from .svg_assets import load_svg_asset
from .svg_geometry import (
    IDENTITY,
    Matrix,
    apply,
    bounds,
    multiply,
    parse_path,
    parse_polygon,
    parse_transform,
    transform_frame,
)
from .svg_profile import SvgProfile
from .svg_semantics import decode_semantic_model
from .svg_values import (
    GRAPHICS,
    MAX_NODES,
    MAX_SVG_BYTES,
    SOURCE_ID,
    SVG_NAMESPACE,
    UNSAFE_TAGS,
    alignment as _alignment,
    assert_canvas_geometry as _assert_canvas_geometry,
    color as _color,
    href as _href,
    invalid as _invalid,
    length as _length,
    length_value as _length_value,
    local as _local,
    namespace as _namespace,
    number as _number,
    positive_length as _positive_length,
    positive_number as _positive_number,
    text_style as _text_style,
    union_bounds as _union_bounds,
    unit_interval as _unit_interval,
    unsafe as _unsafe,
)


class _SvgCompiler:
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
            "fill": "#000000", "fill-opacity": "1", "font-family": "Arial",
            "font-size": "16", "font-style": "normal", "font-weight": "400",
            "stroke": "transparent", "stroke-opacity": "1", "stroke-width": "0",
            "text-anchor": "start", "text-decoration": "none",
        }
        items: list[dict[str, Any]] = []
        for index, child in enumerate(root):
            tag = _local(child.tag)
            if tag == "defs":
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
            "image_pixels": sum(asset["width"] * asset["height"] for asset in self.assets.values()),
            "images": sum(item["kind"] == "image" for item in items),
            "assets": len(self.assets),
            "total_asset_bytes": asset_bytes,
            "resource_requests": len(self.assets),
            "scene_bytes": len(payload),
            "capture_bytes": len(payload) + asset_bytes,
        }
        for key, ceiling in SCENE_LIMITS.items():
            if observed.get(key, 0) > ceiling:
                self._invalid("Compiled SVG scene exceeds the shared scene policy.", limit=key)
        fidelity = {
            outcome: {
                "count": outcomes.get(outcome, 0),
                "area": sum(
                    item["width"] * item["height"]
                    for item in items
                    if item["outcome"] == outcome
                ),
                "by_reason": dict(sorted(Counter(
                    item["outcome_reason"]
                    for item in items
                    if item["outcome"] == outcome and item["outcome_reason"]
                ).items())),
                "samples": [],
                "truncated": 0,
            }
            for outcome in ("native", "approximated", "rasterized")
        }
        return NormalizedScene(
            slides=(tuple(items),),
            assets=self.assets,
            diagnostics={
                "outcomes": dict(sorted(outcomes.items())),
                "kinds": dict(sorted(kinds.items())),
                "reasons": dict(sorted(Counter(
                    item["outcome_reason"] for item in items if item["outcome_reason"]
                ).items())),
                "fidelity": fidelity,
                "unsupported_css": {"total": 0, "by_reason": {}, "samples": [], "truncated": 0},
                "unknown_hints": {"total": 0, "samples": [], "truncated": 0},
                "blocked_resources": {"total": 0, "by_reason": {}, "samples": [], "truncated": 0},
                "font_evidence": {"total": sum(bool(item["text"]) for item in items), "substitutions": 0, "samples": [], "truncated": 0, "capture_truncated": 0},
                "duplicate_descendants_suppressed": 0,
                "limits": {"observed": observed, "ceilings": dict(SCENE_LIMITS)},
                "svg": {
                    "gradients": len(self.profile.gradients),
                    "nodes": self.nodes,
                    "path_commands": self.path_commands,
                    "whole_slide_fallbacks": 0,
                },
            },
            visual_sources=(),
            slide_fills=("transparent",),
        )

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
        opacity = parent_opacity * _unit_interval(style.pop("opacity", "1"), "opacity")
        matrix = multiply(parent_matrix, parse_transform(element.attrib.get("transform")))
        if tag == "g":
            if "data-elftia-kind" in element.attrib:
                return [self._semantic_group(
                    element,
                    source_id,
                    parent_id,
                    matrix,
                    opacity,
                )]
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
                self._invalid("SVG groups must contain at least one drawing node.", source_id=source_id)
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
        item = self._graphic(element, tag, source_id, parent_id, matrix, style, opacity)
        filter_value = element.attrib.get("filter")
        if filter_value is not None:
            expected = re.fullmatch(r"url\(#([A-Za-z][A-Za-z0-9_.:-]{0,79})\)", filter_value)
            if expected is None or expected.group(1) not in self.profile.filter_ids:
                self._unsafe("SVG filter reference is invalid or external.", source_id=source_id)
            item = self._element_fallback(element, item)
        return [item]

    def _semantic_group(
        self,
        element: Element,
        source_id: str,
        parent_id: str | None,
        matrix: Matrix,
        opacity: float,
    ) -> dict[str, Any]:
        kind = element.attrib.get("data-elftia-kind", "")
        model = decode_semantic_model(
            kind,
            element.attrib.get("data-elftia-model", ""),
        )
        raw_bounds = element.attrib.get("data-elftia-bounds", "")
        values = [item.strip() for item in raw_bounds.split(",")]
        if len(values) != 4:
            self._invalid("SVG semantic bounds must contain x, y, width, and height.")
        x, y, width, height = (_number(value, "data-elftia-bounds") for value in values)
        if width <= 0 or height <= 0:
            self._invalid("SVG semantic bounds must be positive.")
        for child in element:
            child_tag = _local(child.tag)
            if child_tag not in {"ellipse", "line", "path", "polygon", "rect", "text"}:
                self._unsafe("SVG semantic preview contains an unsupported element.")
            self.profile.validate_attributes(child, child_tag)
            if child_tag == "text":
                for descendant in child:
                    if _local(descendant.tag) != "tspan":
                        self._unsafe("SVG semantic text preview accepts only tspan children.")
                    self.profile.validate_attributes(descendant, "tspan")
        item = self._base_item(
            source_id,
            parent_id,
            kind,
            transform_frame(x, y, width, height, matrix),
            opacity=opacity,
            fill="transparent",
            stroke="transparent",
            stroke_width=0.0,
        )
        item["table"] = model if kind == "table" else None
        item["chart"] = model if kind == "chart" else None
        return item

    def _graphic(
        self,
        element: Element,
        tag: str,
        source_id: str,
        parent_id: str | None,
        matrix: Matrix,
        style: dict[str, str],
        opacity: float,
    ) -> dict[str, Any]:
        path_commands = None
        polygon_points = None
        if tag == "rect":
            x, y = _length(element, "x", 0), _length(element, "y", 0)
            width, height = _positive_length(element, "width"), _positive_length(element, "height")
            geometry = transform_frame(x, y, width, height, matrix)
            radius = _length(element, "rx", 0) * math.hypot(matrix[0], matrix[1])
            kind = "rounded-rectangle" if radius > 0 else "rectangle"
        elif tag == "ellipse":
            cx, cy = _length(element, "cx"), _length(element, "cy")
            rx, ry = _positive_length(element, "rx"), _positive_length(element, "ry")
            geometry = transform_frame(cx - rx, cy - ry, rx * 2, ry * 2, matrix)
            radius, kind = 0.0, "ellipse"
        elif tag == "line":
            points = [
                apply(matrix, (_length(element, "x1"), _length(element, "y1"))),
                apply(matrix, (_length(element, "x2"), _length(element, "y2"))),
            ]
            geometry = bounds(points)
            path_commands = [
                {"op": "move", "points": [points[0]]},
                {"op": "line", "points": [points[1]]},
            ]
            radius, kind = 0.0, "path"
        elif tag == "polygon":
            polygon_points, geometry = parse_polygon(element.attrib.get("points", ""), matrix)
            radius, kind = 0.0, "polygon"
        elif tag == "path":
            path_commands, geometry = parse_path(element.attrib.get("d", ""), matrix)
            self.path_commands += len(path_commands)
            radius, kind = 0.0, "path"
        elif tag == "text":
            item = self._text_item(element, source_id, parent_id, matrix, style, opacity)
            return item
        elif tag == "image":
            geometry = transform_frame(
                _length(element, "x", 0),
                _length(element, "y", 0),
                _positive_length(element, "width"),
                _positive_length(element, "height"),
                matrix,
            )
            asset = load_svg_asset(
                self.source,
                _href(element),
                purpose="source-image",
                assets=self.assets,
            )
            item = self._base_item(
                source_id, parent_id, "image", geometry, opacity=opacity,
                fill="transparent", stroke=style["stroke"],
                stroke_width=_length_value(style["stroke-width"]),
            )
            item.update({"asset_id": asset["id"], "image_crop": {"left": 0, "top": 0, "right": 0, "bottom": 0}})
            return item
        else:  # pragma: no cover - guarded by caller
            self._invalid("SVG graphic element is unsupported.")
        item = self._base_item(
            source_id,
            parent_id,
            kind,
            geometry,
            opacity=opacity,
            fill=style["fill"],
            stroke=style["stroke"],
            stroke_width=_length_value(style["stroke-width"]),
            radius=radius,
        )
        item["path_commands"] = path_commands
        item["points"] = polygon_points
        item["gradient"] = self.profile.gradient(style["fill"])
        return item

    def _text_item(
        self,
        element: Element,
        source_id: str,
        parent_id: str | None,
        matrix: Matrix,
        style: dict[str, str],
        opacity: float,
    ) -> dict[str, Any]:
        runs: list[dict[str, Any]] = []
        if element.text:
            runs.append({"text": element.text, "style": _text_style(style)})
        for index, child in enumerate(element):
            if _local(child.tag) != "tspan":
                self._unsafe("SVG text accepts only bounded tspan children.")
            self.profile.validate_attributes(child, "tspan")
            self._source_id(child, f"{source_id}-tspan-{index + 1}")
            child_style = self.profile.style(child, style)
            if child.text:
                runs.append({"text": child.text, "style": _text_style(child_style)})
            if child.tail:
                runs.append({"text": child.tail, "style": _text_style(style)})
        runs = [run for run in runs if run["text"]]
        text = "".join(run["text"] for run in runs)
        if not text or len(text.encode("utf-8")) > 64_000:
            self._invalid("SVG text is empty or exceeds policy.", source_id=source_id)
        size = _positive_number(style["font-size"], "font-size")
        width_value = element.attrib.get("textLength")
        if width_value is None:
            width = max(size, len(text) * size * 0.6)
            outcome, reason = "approximated", "text_length_estimated"
            self.approximations += 1
        else:
            width = _positive_number(width_value, "textLength")
            outcome, reason = "native", None
        geometry = transform_frame(
            _length(element, "x", 0),
            _length(element, "y", 0) - size,
            width,
            size * 1.25,
            matrix,
        )
        item = self._base_item(
            source_id, parent_id, "text", geometry, opacity=opacity,
            fill="transparent", stroke="transparent", stroke_width=0.0,
        )
        item.update({
            "outcome": outcome,
            "outcome_reason": reason,
            "paragraphs": [{"alignment": _alignment(style["text-anchor"]), "line_height": "normal", "runs": runs}],
            "text": text,
            "text_style": _text_style(style),
        })
        return item

    def _base_item(
        self,
        source_id: str,
        parent_id: str | None,
        kind: str,
        geometry: dict[str, float],
        *,
        opacity: float,
        fill: str,
        stroke: str,
        stroke_width: float,
        radius: float = 0.0,
    ) -> dict[str, Any]:
        _assert_canvas_geometry(geometry)
        return {
            "asset_id": None,
            "border_color": _color(stroke, "stroke"),
            "border_width": max(0.0, stroke_width),
            "fill": "transparent" if fill.startswith("url(") else _color(fill, "fill"),
            "gradient": None,
            "height": geometry["height"],
            "image_crop": None,
            "kind": kind,
            "opacity": opacity,
            "outcome": "native",
            "outcome_reason": None,
            "paragraphs": [],
            "parent_source_id": parent_id,
            "path_commands": None,
            "points": None,
            "radius": max(0.0, radius),
            "rotation": geometry.get("rotation", 0.0),
            "source_id": source_id,
            "text": "",
            "text_insets": {"bottom": 0, "left": 0, "right": 0, "top": 0},
            "text_style": _text_style({}),
            "table": None,
            "chart": None,
            "width": geometry["width"],
            "x": geometry["x"],
            "y": geometry["y"],
        }

    def _element_fallback(self, element: Element, item: dict[str, Any]) -> dict[str, Any]:
        relative = element.attrib.get("data-pptx-fallback-image")
        if self.fallback_policy != "element-rasterize" or not relative:
            self._invalid("Unsupported SVG filter requires an explicit element fallback asset.")
        area = item["width"] * item["height"]
        if area >= 1920 * 1080 * 0.8:
            self._invalid("Whole-slide or near-whole-slide SVG fallback is forbidden.")
        asset = load_svg_asset(
            self.source,
            relative,
            purpose="element-fallback",
            assets=self.assets,
        )
        return {
            **item,
            "asset_id": asset["id"],
            "fill": "transparent",
            "gradient": None,
            "image_crop": {"left": 0, "top": 0, "right": 0, "bottom": 0},
            "kind": "image",
            "outcome": "rasterized",
            "outcome_reason": "unsupported_filter",
            "path_commands": None,
            "points": None,
        }

    def _viewport(self, root: Element) -> Matrix:
        allowed = {"height", "id", "viewBox", "width"}
        if set(root.attrib) - allowed:
            self._invalid("SVG root attributes are outside the explicit viewport profile.")
        width = _positive_number(root.attrib.get("width"), "width")
        height = _positive_number(root.attrib.get("height"), "height")
        view_box = root.attrib.get("viewBox")
        values = [] if view_box is None else [float(item) for item in re.split(r"[ ,]+", view_box.strip()) if item]
        if len(values) != 4 or values[2] <= 0 or values[3] <= 0 or not all(math.isfinite(item) for item in values):
            self._invalid("SVG requires an explicit finite viewBox.")
        if abs(width / height - values[2] / values[3]) > 1e-6 or abs(values[2] / values[3] - 16 / 9) > 1e-6:
            self._invalid("SVG viewport must use the fixed 16:9 scene aspect ratio.")
        scale = 1920 / values[2]
        return (scale, 0.0, 0.0, scale, -values[0] * scale, -values[1] * scale)

    def _source_id(self, element: Element, generated: str) -> str:
        source_id = element.attrib.get("id") or f"node-{generated}"
        if SOURCE_ID.fullmatch(source_id) is None or source_id in self.source_ids:
            self._invalid("SVG node identity is invalid or duplicated.", source_id=source_id)
        self.source_ids.add(source_id)
        return source_id

    def _count_tree(self, root: Element) -> None:
        for node in root.iter():
            namespace = _namespace(node.tag)
            if namespace != SVG_NAMESPACE:
                self._unsafe("SVG contains a foreign XML namespace.")
            self.nodes += 1
            if self.nodes > MAX_NODES:
                self._invalid("SVG node count exceeds policy.")

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
    resolved = source.expanduser().resolve(strict=True)
    if resolved.is_symlink() or not resolved.is_file() or resolved.suffix.casefold() != ".svg":
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
