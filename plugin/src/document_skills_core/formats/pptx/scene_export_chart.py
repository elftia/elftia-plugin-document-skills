"""Closed-world ChartML matching for strict scene export."""

from __future__ import annotations

import re
from typing import Any
from xml.etree.ElementTree import Element, fromstring

from .chart import build_chart_part, prepare_chart
from .constants import local_name

_CHART_PART = re.compile(r"^ppt/charts/chart([1-9][0-9]*)[.]xml$")


def chart_projection_issue(
    root: Element,
    model: dict[str, Any],
    part: str,
) -> str | None:
    """Require source ChartML to equal the emitter form of the projected model."""

    match = _CHART_PART.fullmatch(part)
    if match is None:
        return "unsupported-chart-part"
    try:
        value = _emitter_value(model)
        prepared = prepare_chart(value, int(match.group(1)))
        expected = fromstring(build_chart_part(prepared))
    except (KeyError, TypeError, ValueError):
        return "unsupported-chart-model"
    mismatch = _first_mismatch(root, expected)
    if mismatch is None:
        return None
    return f"unsupported-chart-{mismatch.casefold()}"


def _emitter_value(model: dict[str, Any]) -> dict[str, Any]:
    chart_type = str(model["chart_type"])
    categories = [str(value) for value in model["categories"]]
    series = model["series"]
    if chart_type == "scatter":
        projected_series = [
            {
                "name": item["name"],
                "x_values": [float(value) for value in categories],
                "y_values": item["values"],
            }
            for item in series
        ]
    else:
        projected_series = [
            {"name": item["name"], "values": item["values"]}
            for item in series
        ]
    return {
        "categories": categories,
        "chart_type": chart_type,
        "series": projected_series,
    }


def _first_mismatch(actual: Element, expected: Element) -> str | None:
    if actual.tag != expected.tag:
        return local_name(actual.tag)
    if actual.attrib != expected.attrib:
        return local_name(actual.tag)
    if _semantic_text(actual) != _semantic_text(expected):
        return local_name(actual.tag)
    actual_children = list(actual)
    expected_children = list(expected)
    for actual_child, expected_child in zip(
        actual_children,
        expected_children,
        strict=False,
    ):
        mismatch = _first_mismatch(actual_child, expected_child)
        if mismatch is not None:
            return mismatch
    if len(actual_children) == len(expected_children):
        return None
    index = min(len(actual_children), len(expected_children))
    remaining = (
        actual_children[index:]
        if len(actual_children) > len(expected_children)
        else expected_children[index:]
    )
    return local_name(remaining[0].tag)


def _semantic_text(node: Element) -> str:
    value = node.text or ""
    if list(node) and not value.strip():
        return ""
    return value


__all__ = ["chart_projection_issue"]
