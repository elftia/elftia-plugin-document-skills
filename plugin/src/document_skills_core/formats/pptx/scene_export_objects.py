"""PPTX object projection into A-Contract objects and constrained SVG."""

from __future__ import annotations

import hashlib
from typing import Any
from xml.etree.ElementTree import Element, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS, local_name
from .presentation_contracts import PresentationContractConsumer
from .projection import project_charts
from .scene_export_geometry import (
    geometry as _geometry,
    group_transform as _group_transform,
    object_base as _object_base,
    ordered_slides as _ordered_slides,
    pixels as _pixels,
    source_identity as _source_identity,
)
from .scene_export_models import (
    SceneObjectProjection,
    SceneProjectionUnsupported as _Unsupported,
)
from .scene_export_svg import (
    asset_extension as _asset_extension,
    line_svg as _line_svg,
    number as _number,
    semantic_svg as _semantic_svg,
    shape_svg as _shape_svg,
    table_model as _table_model,
    text_svg as _text_svg,
)

_P = NS["p"]
_A = NS["a"]
_R = NS["r"]
_SVG = "http://www.w3.org/2000/svg"
_SUPPORTED_CHARTS = {"bar", "column", "line", "pie", "scatter"}


def P(tag: str) -> str:
    return f"{{{_P}}}{tag}"


def A(tag: str) -> str:
    return f"{{{_A}}}{tag}"


def R(tag: str) -> str:
    return f"{{{_R}}}{tag}"


class _Projector:
    def __init__(
        self,
        package: Any,
        consumer: PresentationContractConsumer,
        *,
        deck_id: str,
        source_template_id: str,
        mode: str,
        slide_cx: int,
        slide_cy: int,
    ) -> None:
        self.package = package
        self.consumer = consumer
        self.deck_id = deck_id
        self.source_template_id = source_template_id
        self.mode = mode
        self.slide_cx = slide_cx
        self.slide_cy = slide_cy
        self.svg_members: dict[str, bytes] = {}
        self.asset_members: dict[str, bytes] = {}
        self.source_mapping: list[dict[str, Any]] = []
        self.unsupported: list[dict[str, Any]] = []
        self.chart_by_part = {item["part"]: item for item in project_charts(package)}

    def project(self) -> SceneObjectProjection:
        slides = []
        for index, source in enumerate(_ordered_slides(self.package), 1):
            slides.append(self._slide(source, index))
        return SceneObjectProjection(
            slides=slides,
            svg_members=self.svg_members,
            asset_members=self.asset_members,
            source_mapping=self.source_mapping,
            unsupported=self.unsupported,
        )

    def _slide(self, source: dict[str, str], index: int) -> dict[str, Any]:
        slide_id = self.consumer.stable_slide_id(
            deck_id=self.deck_id,
            source_template_id=self.source_template_id,
            semantic_key=f"source-slide-{source['numeric_id']}",
        )
        root = self.package.xml(source["part"])
        tree = root.find(f"{P('cSld')}/{P('spTree')}")
        if tree is None:
            self._unsupported(source, None, "missing-shape-tree", None)
            elements: list[Element] = []
        else:
            elements = [
                element
                for element in tree
                if local_name(element.tag)
                not in {"nvGrpSpPr", "grpSpPr", "extLst"}
            ]
        svg = Element(
            f"{{{_SVG}}}svg",
            {
                "height": "1080",
                "viewBox": "0 0 1920 1080",
                "width": "1920",
            },
        )
        objects: list[dict[str, Any]] = []
        transform = (1.0, 1.0, 0.0, 0.0)
        for element in elements:
            self._element(
                element,
                source,
                slide_id,
                objects,
                svg,
                transform,
                parent_id=None,
                group_id=None,
            )
        relative = f"slide-{index:04d}-{slide_id}.svg"
        self.svg_members[relative] = tostring(
            svg,
            encoding="utf-8",
            xml_declaration=True,
        )
        return {
            "slideId": slide_id,
            "role": "content",
            "canvasProfileId": "source-canvas",
            "objects": objects,
        }

    def _element(
        self,
        element: Element,
        slide: dict[str, str],
        slide_id: str,
        objects: list[dict[str, Any]],
        svg_parent: Element,
        transform: tuple[float, float, float, float],
        *,
        parent_id: str | None,
        group_id: str | None,
    ) -> None:
        tag = local_name(element.tag)
        source_id, source_name = _source_identity(element)
        geometry = _geometry(element, transform)
        if source_id is None or geometry is None:
            self._unsupported(slide, source_id, "missing-stable-geometry", geometry)
            return
        object_id = self.consumer.stable_object_id(
            slide_id=slide_id,
            semantic_key=f"source-object-{source_id}",
        )
        try:
            if tag == "grpSp":
                projected, svg_node = self._group(
                    element,
                    object_id,
                    geometry,
                    len(objects),
                    parent_id=parent_id,
                    group_id=group_id,
                )
                objects.append(projected)
                svg_parent.append(svg_node)
                child_transform = _group_transform(element, transform)
                for child in element:
                    if local_name(child.tag) in {"nvGrpSpPr", "grpSpPr", "extLst"}:
                        continue
                    self._element(
                        child,
                        slide,
                        slide_id,
                        objects,
                        svg_node,
                        child_transform,
                        parent_id=object_id,
                        group_id=object_id,
                    )
            else:
                projected, svg_node = self._leaf(
                    element,
                    slide["part"],
                    object_id,
                    geometry,
                    len(objects),
                    parent_id=parent_id,
                    group_id=group_id,
                )
                objects.append(projected)
                svg_parent.append(svg_node)
        except _Unsupported as error:
            self._unsupported(slide, source_id, error.reason, geometry)
            if self.mode == "tolerant":
                opaque = _object_base(
                    object_id,
                    geometry,
                    len(objects),
                    parent_id=parent_id,
                    group_id=group_id,
                    editability="none",
                    unsupported=[error.reason],
                )
                opaque.update({"type": "shape", "content": {"shapeKind": "opaque"}})
                objects.append(opaque)
        self.source_mapping.append({
            "object_id": object_id,
            "source_name": source_name,
            "source_object_id": source_id,
            "source_part": slide["part"],
            "type": tag,
        })

    def _group(
        self,
        element: Element,
        object_id: str,
        geometry: dict[str, float],
        z_order: int,
        *,
        parent_id: str | None,
        group_id: str | None,
    ) -> tuple[dict[str, Any], Element]:
        projected = _object_base(
            object_id,
            geometry,
            z_order,
            parent_id=parent_id,
            group_id=group_id,
        )
        projected.update({"type": "shape", "content": {"shapeKind": "group"}})
        return projected, Element(f"{{{_SVG}}}g", {"id": object_id})

    def _leaf(
        self,
        element: Element,
        slide_part: str,
        object_id: str,
        geometry: dict[str, float],
        z_order: int,
        *,
        parent_id: str | None,
        group_id: str | None,
    ) -> tuple[dict[str, Any], Element]:
        tag = local_name(element.tag)
        projected = _object_base(
            object_id,
            geometry,
            z_order,
            parent_id=parent_id,
            group_id=group_id,
        )
        pixel = _pixels(geometry, self.slide_cx, self.slide_cy)
        if tag == "sp":
            text = "".join(node.text or "" for node in element.iter(A("t")))
            if text:
                projected.update({"type": "text", "content": {"text": text}})
                return projected, _text_svg(element, object_id, pixel, text)
            kind, svg = _shape_svg(element, object_id, pixel)
            projected.update({"type": "shape", "content": {"shapeKind": kind}})
            return projected, svg
        if tag == "cxnSp":
            projected.update({"type": "shape", "content": {"shapeKind": "line"}})
            return projected, _line_svg(element, object_id, pixel)
        if tag == "pic":
            asset_ref, relative = self._image_asset(element, slide_part)
            projected.update({
                "type": "image",
                "content": {"altText": _source_identity(element)[1], "assetRef": asset_ref, "fit": "fill"},
                "refs": {"assetRef": asset_ref, "licenseStatus": "not_evaluated"},
            })
            return projected, Element(
                f"{{{_SVG}}}image",
                {
                    "height": _number(pixel["height"]),
                    "href": relative,
                    "id": object_id,
                    "width": _number(pixel["width"]),
                    "x": _number(pixel["x"]),
                    "y": _number(pixel["y"]),
                },
            )
        if tag == "graphicFrame":
            table = element.find(f"{A('graphic')}/{A('graphicData')}/{A('tbl')}")
            if table is not None:
                model = _table_model(table)
                projected.update({
                    "type": "table",
                    "content": {"headerRows": model["header_rows"], "rows": model["rows"]},
                })
                return projected, _semantic_svg(object_id, "table", model, pixel)
            chart = next(
                (node for node in element.iter() if local_name(node.tag) == "chart"),
                None,
            )
            if chart is not None:
                model = self._chart_model(slide_part, chart.attrib.get(R("id"), ""))
                projected.update({
                    "type": "chart",
                    "content": {
                        "categories": model["categories"],
                        "chartKind": model["chart_type"],
                        "series": model["series"],
                    },
                })
                return projected, _semantic_svg(object_id, "chart", model, pixel)
            raise _Unsupported("unsupported-graphic-frame")
        raise _Unsupported(f"unsupported-{tag.casefold()}")

    def _image_asset(
        self,
        element: Element,
        slide_part: str,
    ) -> tuple[dict[str, str], str]:
        blip = element.find(f"{P('blipFill')}/{A('blip')}")
        relationship_id = None if blip is None else blip.attrib.get(R("embed"))
        relationship = next(
            (
                item
                for item in self.package.part_rels(slide_part)
                if item.relationship_id == relationship_id
            ),
            None,
        )
        target = None if relationship is None else relationship.resolved_target
        if target is None or target not in self.package.parts:
            raise _Unsupported("missing-image-relationship")
        payload = self.package.parts[target]
        digest = hashlib.sha256(payload).hexdigest()
        extension = _asset_extension(
            self.package.content_type_for(target) or "",
            target,
        )
        relative = f"assets/{digest}.{extension}"
        self.asset_members.setdefault(relative, payload)
        ref = {
            "assetId": f"asset-{digest[:32]}",
            "catalogId": "pptx-scene-export",
            "sha256": f"sha256:{digest}",
            "version": "1.0.0",
        }
        return ref, relative

    def _chart_model(self, slide_part: str, relationship_id: str) -> dict[str, Any]:
        relationship = next(
            (
                item
                for item in self.package.part_rels(slide_part)
                if item.relationship_id == relationship_id
            ),
            None,
        )
        chart_part = None if relationship is None else relationship.resolved_target
        chart = self.chart_by_part.get(chart_part or "")
        if chart is None or chart["chart_type"] not in _SUPPORTED_CHARTS:
            raise _Unsupported("unsupported-chart")
        raw_series = chart.get("series") or []
        if not raw_series:
            raise _Unsupported("empty-chart")
        categories = raw_series[0].get("categories") or [
            str(value) for value in raw_series[0].get("x_values", [])
        ]
        if not categories:
            raise _Unsupported("chart-categories-unavailable")
        series = []
        for index, item in enumerate(raw_series, 1):
            values = item.get("values") or item.get("y_values") or []
            if len(values) != len(categories):
                raise _Unsupported("chart-series-misaligned")
            series.append({
                "name": item.get("name") or f"Series {index}",
                "values": [None if value is None else float(value) for value in values],
            })
        return {
            "categories": [str(value) for value in categories],
            "chart_type": chart["chart_type"],
            "series": series,
        }

    def _unsupported(
        self,
        slide: dict[str, str],
        source_id: str | None,
        reason: str,
        geometry: dict[str, float] | None,
    ) -> None:
        record = {
            "bbox": geometry,
            "reason": reason,
            "source_object_id": source_id,
            "source_part": slide["part"],
            "source_slide_id": slide["numeric_id"],
        }
        if self.mode == "strict":
            raise DocumentSkillsError(
                ErrorCode.UNSUPPORTED_FEATURE,
                "Strict scene export encountered an unsupported PresentationML object.",
                status="enhancement_required",
                details=record,
            )
        self.unsupported.append(record)


def project_scene_objects(
    package: Any,
    consumer: PresentationContractConsumer,
    *,
    deck_id: str,
    source_template_id: str,
    mode: str,
    slide_cx: int,
    slide_cy: int,
) -> SceneObjectProjection:
    return _Projector(
        package,
        consumer,
        deck_id=deck_id,
        source_template_id=source_template_id,
        mode=mode,
        slide_cx=slide_cx,
        slide_cy=slide_cy,
    ).project()


__all__ = ["SceneObjectProjection", "project_scene_objects"]
