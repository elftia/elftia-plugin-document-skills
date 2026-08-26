"""DrawingML custom-path and approved-gradient emission for shared scenes."""

import math
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from .constants import NS

_A = NS["a"]


def append_shape_geometry(parent: Element, item: dict[str, Any], emu) -> None:
    commands = item.get("path_commands")
    points = item.get("points")
    if commands is None and points is None:
        preset = {
            "rounded-rectangle": "roundRect",
            "ellipse": "ellipse",
            "line": "line",
        }.get(item["kind"], "rect")
        geometry = SubElement(parent, f"{{{_A}}}prstGeom", {"prst": preset})
        adjustments = SubElement(geometry, f"{{{_A}}}avLst")
        if item["kind"] == "rounded-rectangle":
            short_side = min(item["width"], item["height"])
            adjustment = max(
                0,
                min(50_000, int(round(item["radius"] / short_side * 100_000))),
            )
            SubElement(
                adjustments,
                f"{{{_A}}}gd",
                {"name": "adj", "fmla": f"val {adjustment}"},
            )
        return
    geometry = SubElement(parent, f"{{{_A}}}custGeom")
    for tag in ("avLst", "gdLst", "ahLst", "cxnLst"):
        SubElement(geometry, f"{{{_A}}}{tag}")
    SubElement(
        geometry,
        f"{{{_A}}}rect",
        {"l": "l", "t": "t", "r": "r", "b": "b"},
    )
    path_list = SubElement(geometry, f"{{{_A}}}pathLst")
    width = max(1, emu(item["width"]))
    height = max(1, emu(item["height"]))
    path = SubElement(
        path_list,
        f"{{{_A}}}path",
        {"w": str(width), "h": str(height)},
    )
    if points is not None:
        _point_command(path, "moveTo", _local_point(points[0], item, emu))
        for point in points[1:]:
            _point_command(path, "lnTo", _local_point(point, item, emu))
        SubElement(path, f"{{{_A}}}close")
        return
    for command in commands or []:
        operation = command["op"]
        local_points = [_local_point(point, item, emu) for point in command["points"]]
        if operation == "move":
            _point_command(path, "moveTo", local_points[0])
        elif operation == "line":
            _point_command(path, "lnTo", local_points[0])
        elif operation == "quad":
            node = SubElement(path, f"{{{_A}}}quadBezTo")
            for point in local_points:
                SubElement(node, f"{{{_A}}}pt", _coordinates(point))
        elif operation == "cubic":
            node = SubElement(path, f"{{{_A}}}cubicBezTo")
            for point in local_points:
                SubElement(node, f"{{{_A}}}pt", _coordinates(point))
        elif operation == "close":
            SubElement(path, f"{{{_A}}}close")


def append_gradient_fill(parent: Element, gradient: dict[str, Any], opacity: float) -> None:
    fill = SubElement(parent, f"{{{_A}}}gradFill", {"rotWithShape": "1"})
    stops = SubElement(fill, f"{{{_A}}}gsLst")
    for stop in gradient["stops"]:
        node = SubElement(
            stops,
            f"{{{_A}}}gs",
            {"pos": str(max(0, min(100_000, round(stop["offset"] * 100_000))))},
        )
        color = SubElement(node, f"{{{_A}}}srgbClr", {"val": stop["color"][1:].upper()})
        effective = max(
            0,
            min(100_000, round(stop["opacity"] * opacity * 100_000)),
        )
        if effective < 100_000:
            SubElement(color, f"{{{_A}}}alpha", {"val": str(effective)})
    angle = math.degrees(
        math.atan2(
            gradient["y2"] - gradient["y1"],
            gradient["x2"] - gradient["x1"],
        )
    )
    SubElement(
        fill,
        f"{{{_A}}}lin",
        {"ang": str(round((angle % 360) * 60_000)), "scaled": "1"},
    )


def _local_point(point: tuple[float, float], item: dict[str, Any], emu) -> tuple[int, int]:
    return (
        max(0, min(emu(item["width"]), emu(point[0] - item["x"]))),
        max(0, min(emu(item["height"]), emu(point[1] - item["y"]))),
    )


def _point_command(parent: Element, tag: str, point: tuple[int, int]) -> None:
    command = SubElement(parent, f"{{{_A}}}{tag}")
    SubElement(command, f"{{{_A}}}pt", _coordinates(point))


def _coordinates(point: tuple[int, int]) -> dict[str, str]:
    return {"x": str(point[0]), "y": str(point[1])}


__all__ = ["append_gradient_fill", "append_shape_geometry"]
