"""Semantic matching helpers for sparkline create/edit validation."""

from __future__ import annotations

from typing import Any

_FIELDS = (
    "sheet",
    "location",
    "data",
    "type",
    "empty_cells",
    "markers",
    "high_point",
    "low_point",
    "first_point",
    "last_point",
    "negative_points",
    "right_to_left",
    "manual_min",
    "manual_max",
    "color",
    "negative_color",
    "axis_color",
    "marker_color",
    "first_color",
    "last_color",
    "high_color",
    "low_color",
)


def sparkline_edit_matches(
    projected: list[dict[str, Any]],
    edit: dict[str, Any],
    sheet_name: str,
) -> bool:
    if edit["type"] == "sparkline_delete":
        return not any(
            item["sheet"] == sheet_name
            and item["location"].casefold() == edit["ref"].casefold()
            for item in projected
        )
    expected = {"sheet": sheet_name, **edit["sparkline"]}
    return any(sparkline_matches(item, expected) for item in projected)


def missing_created_sparklines(
    projected: list[dict[str, Any]],
    workbook: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    for sheet in workbook.get("sheets", []):
        for sparkline in sheet.get("sparklines", []):
            expected = {"sheet": sheet["name"], **sparkline}
            if not any(sparkline_matches(actual, expected) for actual in projected):
                missing.append(f"sparkline:{sheet['name']}!{sparkline['location']}")
    return missing


def sparkline_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(actual.get(field) == expected.get(field) for field in _FIELDS)
