"""Leaf object projection for PPTX scene export."""

from __future__ import annotations

import hashlib
from typing import Any
from xml.etree.ElementTree import Element

from .constants import NS, local_name
from .scene_export_chart import chart_projection_issue
from .scene_export_geometry import (
    object_base as _object_base,
    pixels as _pixels,
    source_identity as _source_identity,
)
from .scene_export_models import SceneProjectionUnsupported as _Unsupported
from .scene_export_svg import (
    asset_extension as _asset_extension,
    line_svg as _line_svg,
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


def _p(tag: str) -> str:
    return f"{{{_P}}}{tag}"


def _a(tag: str) -> str:
    return f"{{{_A}}}{tag}"


def _r(tag: str) -> str:
    return f"{{{_R}}}{tag}"


class SceneExportLeafMixin:
    """Leaf projection methods mixed into the state-owning scene projector."""

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
            text = "".join(node.text or "" for node in element.iter(_a("t")))
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
            projected.update(
                {
                    "type": "image",
                    "content": {
                        "altText": _source_identity(element)[1],
                        "assetRef": asset_ref,
                        "fit": "fill",
                    },
                    "refs": {
                        "assetRef": asset_ref,
                        "licenseStatus": "not_evaluated",
                    },
                }
            )
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
            table = element.find(f"{_a('graphic')}/{_a('graphicData')}/{_a('tbl')}")
            if table is not None:
                model = _table_model(table)
                projected.update(
                    {
                        "type": "table",
                        "content": {
                            "headerRows": model["header_rows"],
                            "rows": model["rows"],
                        },
                    }
                )
                return projected, _semantic_svg(object_id, "table", model, pixel)
            chart = next(
                (
                    node
                    for node in element.iter()
                    if local_name(node.tag) == "chart"
                ),
                None,
            )
            if chart is not None:
                model = self._chart_model(
                    slide_part,
                    chart.attrib.get(_r("id"), ""),
                )
                projected.update(
                    {
                        "type": "chart",
                        "content": {
                            "categories": model["categories"],
                            "chartKind": model["chart_type"],
                            "series": model["series"],
                        },
                    }
                )
                return projected, _semantic_svg(object_id, "chart", model, pixel)
            raise _Unsupported("unsupported-graphic-frame")
        raise _Unsupported(f"unsupported-{tag.casefold()}")

    def _image_asset(
        self,
        element: Element,
        slide_part: str,
    ) -> tuple[dict[str, str], str]:
        blip = element.find(f"{_p('blipFill')}/{_a('blip')}")
        relationship_id = None if blip is None else blip.attrib.get(_r("embed"))
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
            series.append(
                {
                    "name": item.get("name") or f"Series {index}",
                    "values": [
                        None if value is None else float(value) for value in values
                    ],
                }
            )
        model = {
            "categories": [str(value) for value in categories],
            "chart_type": chart["chart_type"],
            "series": series,
        }
        issue = chart_projection_issue(
            self.package.xml(chart_part),
            model,
            chart_part or "",
        )
        if issue is not None:
            raise _Unsupported(issue)
        return model


def _number(value: float) -> str:
    return str(round(value, 6)).rstrip("0").rstrip(".") or "0"


__all__ = ["SceneExportLeafMixin"]
