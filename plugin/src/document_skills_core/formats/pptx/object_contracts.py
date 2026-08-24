"""Bounded contracts for stable-selector PPTX object edits."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT, MAX_SLIDES
from .typed_object_contracts import parse_chart_reference, parse_image_reference

OBJECT_EDIT_TYPES = frozenset({
    "action_add", "action_remove", "action_update",
    "chart_add", "chart_delete", "chart_update",
    "hyperlink_add", "hyperlink_remove", "hyperlink_update",
    "image_add", "image_crop", "image_delete", "image_replace",
    "notes_update",
    "shape_add", "shape_delete", "shape_update",
    "table_add", "table_delete", "table_update",
    "text_style", "text_update",
})

_GEOMETRIES = {
    "ellipse", "hexagon", "line", "rect", "roundRect", "triangle",
}


def parse_object_edit(edit: dict[str, Any], index: int) -> dict[str, Any]:
    edit_type = edit.get("type")
    if edit_type not in OBJECT_EDIT_TYPES:
        _invalid("Unknown PPTX object edit type.", field=f"edits.{index}.type")
    field = f"edits.{index}"
    if edit_type == "notes_update":
        _exact_keys(edit, {"precondition_sha256", "slide", "type", "value"}, field)
        return {
            "precondition_sha256": _precondition(edit.get("precondition_sha256"), field),
            "slide": _integer(edit.get("slide"), 1, MAX_SLIDES, f"{field}.slide"),
            "type": edit_type,
            "value": _text(edit.get("value", ""), f"{field}.value"),
        }
    if edit_type.endswith("_add") and edit_type not in {"action_add", "hyperlink_add"}:
        _exact_keys(edit, {"object", "slide", "type"}, field)
        return {
            "object": _parse_added_object(edit_type, edit.get("object"), f"{field}.object"),
            "slide": _integer(edit.get("slide"), 1, MAX_SLIDES, f"{field}.slide"),
            "type": edit_type,
        }
    if edit_type in {"shape_delete", "image_delete", "table_delete", "chart_delete"}:
        _exact_keys(edit, {"precondition_sha256", "selector", "slide", "type"}, field)
        return _selected_edit(edit, edit_type, field)
    if edit_type in {"shape_update", "image_crop", "image_replace", "table_update", "chart_update", "text_style", "text_update"}:
        key = "object" if edit_type in {"image_replace", "chart_update"} else "properties"
        _exact_keys(edit, {key, "precondition_sha256", "selector", "slide", "type"}, field)
        result = _selected_edit(edit, edit_type, field)
        value = edit.get(key)
        if edit_type == "image_replace":
            result[key] = _parse_image_object(value, f"{field}.{key}", partial=False)
        elif edit_type == "chart_update":
            result[key] = _parse_chart_object(value, f"{field}.{key}", partial=False)
        elif edit_type == "shape_update":
            result[key] = _parse_shape_object(value, f"{field}.{key}", partial=True)
        elif edit_type == "image_crop":
            result[key] = _parse_image_crop(value, f"{field}.{key}")
        elif edit_type == "table_update":
            result[key] = _parse_table_object(value, f"{field}.{key}", partial=True)
        elif edit_type == "text_update":
            result[key] = _parse_text_update(value, f"{field}.{key}")
        else:
            result[key] = _parse_text_style(value, f"{field}.{key}")
        return result
    if edit_type.startswith("hyperlink_"):
        allowed = {"precondition_sha256", "selector", "slide", "type"}
        if edit_type != "hyperlink_remove":
            allowed.add("target_slide")
        _exact_keys(edit, allowed, field)
        result = _selected_edit(edit, edit_type, field)
        if edit_type != "hyperlink_remove":
            result["target_slide"] = _integer(
                edit.get("target_slide"), 1, MAX_SLIDES, f"{field}.target_slide"
            )
        return result
    allowed = {"precondition_sha256", "selector", "slide", "type"}
    if edit_type != "action_remove":
        allowed.add("action")
    _exact_keys(edit, allowed, field)
    result = _selected_edit(edit, edit_type, field)
    if edit_type != "action_remove":
        action = _text(edit.get("action"), f"{field}.action", False)
        if action not in {"first", "last", "next", "previous"}:
            _invalid("Action must be first, last, next, or previous.", field=f"{field}.action")
        result["action"] = action
    return result


def _selected_edit(edit: dict[str, Any], edit_type: str, field: str) -> dict[str, Any]:
    return {
        "precondition_sha256": _precondition(edit.get("precondition_sha256"), field),
        "selector": _parse_selector(edit.get("selector"), f"{field}.selector"),
        "slide": _integer(edit.get("slide"), 1, MAX_SLIDES, f"{field}.slide"),
        "type": edit_type,
    }


def _parse_selector(value: Any, field: str) -> dict[str, str | None]:
    if type(value) is not dict:
        _invalid("Object selector must be an object.", field=field)
    _exact_keys(value, {"id", "name", "type"}, field)
    object_id = value.get("id")
    if type(object_id) is int and not isinstance(object_id, bool):
        object_id = str(object_id)
    if object_id is not None:
        object_id = _text(object_id, f"{field}.id", False)
    name = value.get("name")
    if name is not None:
        name = _text(name, f"{field}.name", False)
    if object_id is None and name is None:
        _invalid("Object selector requires id or name.", field=field)
    object_type = value.get("type")
    if object_type is not None:
        object_type = _text(object_type, f"{field}.type", False)
        if object_type not in {"chart", "image", "shape", "table"}:
            _invalid("Object selector type is unsupported.", field=f"{field}.type")
    return {"id": object_id, "name": name, "type": object_type}


def _parse_added_object(edit_type: str, value: Any, field: str) -> dict[str, Any]:
    if edit_type == "shape_add":
        return _parse_shape_object(value, field, partial=False)
    if edit_type == "image_add":
        return _parse_image_object(value, field, partial=False)
    if edit_type == "table_add":
        return _parse_table_object(value, field, partial=False)
    return _parse_chart_object(value, field, partial=False)


def _parse_shape_object(value: Any, field: str, *, partial: bool) -> dict[str, Any]:
    if type(value) is not dict or (partial and not value):
        _invalid("Shape object must be a non-empty object.", field=field)
    allowed = {"fill", "frame", "geometry", "line", "name", "opacity", "rotation", "shadow", "text", "z_order"}
    _exact_keys(value, allowed, field)
    result: dict[str, Any] = {}
    if not partial or "name" in value:
        result["name"] = _text(value.get("name", "Shape"), f"{field}.name", False)
    if not partial or "geometry" in value:
        geometry = _text(value.get("geometry", "rect"), f"{field}.geometry", False)
        if geometry not in _GEOMETRIES:
            _invalid("Unsupported shape geometry.", field=f"{field}.geometry")
        result["geometry"] = geometry
    for key in ("fill", "line", "shadow"):
        if key in value:
            result[key] = _parse_style_value(value[key], f"{field}.{key}", key)
    if not partial or "frame" in value:
        result["frame"] = _parse_frame(
            value.get("frame", {"x": 457_200, "y": 1_600_200, "cx": 3_657_600, "cy": 1_371_600}),
            f"{field}.frame",
        )
    for key, default, minimum, maximum in (
        ("opacity", 1.0, 0.0, 1.0),
        ("rotation", 0.0, -360.0, 360.0),
    ):
        if not partial or key in value:
            result[key] = _number(value.get(key, default), minimum, maximum, f"{field}.{key}")
    if not partial or "z_order" in value:
        result["z_order"] = _integer(value.get("z_order", 100), 0, 10_000, f"{field}.z_order")
    if "text" in value or not partial:
        result["text"] = _text(value.get("text", ""), f"{field}.text")
    return result


def _parse_image_object(value: Any, field: str, *, partial: bool) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Image object must be an object.", field=field)
    _exact_keys(value, {"alt_text", "content_type", "crop", "fit", "frame", "name", "opacity", "path", "rotation", "z_order"}, field)
    image_value = {key: item for key, item in value.items() if key != "name"}
    parsed = parse_image_reference(image_value, field)
    assert parsed is not None
    parsed["name"] = _text(value.get("name", "Image"), f"{field}.name", False)
    return parsed


def _parse_chart_object(value: Any, field: str, *, partial: bool) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Chart object must be an object.", field=field)
    _exact_keys(value, {"axes", "categories", "chart_type", "colors", "data_labels", "frame", "legend", "name", "series", "title", "z_order"}, field)
    chart_value = {key: item for key, item in value.items() if key not in {"frame", "name", "z_order"}}
    parsed = parse_chart_reference(chart_value, field)
    assert parsed is not None
    parsed["frame"] = _parse_frame(
        value.get("frame", {"x": 457_200, "y": 1_746_250, "cx": 8_229_600, "cy": 4_572_000}),
        f"{field}.frame",
    )
    parsed["name"] = _text(value.get("name", "Chart"), f"{field}.name", False)
    parsed["z_order"] = _integer(value.get("z_order", 100), 0, 10_000, f"{field}.z_order")
    return parsed


def _parse_table_object(value: Any, field: str, *, partial: bool) -> dict[str, Any]:
    if type(value) is not dict or (partial and not value):
        _invalid("Table object must be a non-empty object.", field=field)
    _exact_keys(value, {"frame", "heights", "merges", "name", "rows", "widths", "z_order"}, field)
    result: dict[str, Any] = {}
    if "name" in value or not partial:
        result["name"] = _text(value.get("name", "Table"), f"{field}.name", False)
    if "frame" in value or not partial:
        result["frame"] = _parse_frame(
            value.get("frame", {"x": 457_200, "y": 1_746_250, "cx": 8_229_600, "cy": 2_746_380}),
            f"{field}.frame",
        )
    if "z_order" in value or not partial:
        result["z_order"] = _integer(value.get("z_order", 100), 0, 10_000, f"{field}.z_order")
    if "rows" in value or not partial:
        rows = value.get("rows", [])
        if type(rows) is not list or not rows or len(rows) > 1_000:
            _invalid("Table rows must be a non-empty bounded array.", field=f"{field}.rows")
        parsed_rows = []
        width = None
        for row_index, row in enumerate(rows):
            if type(row) is not list or not row or len(row) > 1_000:
                _invalid("Each table row must be a non-empty bounded array.", field=f"{field}.rows.{row_index}")
            if width is None:
                width = len(row)
            if len(row) != width:
                _invalid("All table rows must have equal width.", field=f"{field}.rows.{row_index}")
            parsed_rows.append([_text(cell, f"{field}.rows.{row_index}") for cell in row])
        result["rows"] = parsed_rows
    for key in ("widths", "heights"):
        if key in value:
            raw = value[key]
            if type(raw) is not list or not raw:
                _invalid(f"Table {key} must be a non-empty array.", field=f"{field}.{key}")
            result[key] = [_integer(item, 1, 100_000_000, f"{field}.{key}") for item in raw]
    if "merges" in value:
        merges = value["merges"]
        if type(merges) is not list or len(merges) > 256:
            _invalid("Table merges must be a bounded array.", field=f"{field}.merges")
        result["merges"] = [_parse_merge(item, f"{field}.merges") for item in merges]
    return result


def _parse_merge(value: Any, field: str) -> dict[str, int]:
    if type(value) is not dict:
        _invalid("Table merge must be an object.", field=field)
    _exact_keys(value, {"column", "column_span", "row", "row_span"}, field)
    return {
        key: _integer(value.get(key), 1, 1_000, f"{field}.{key}")
        for key in ("row", "column", "row_span", "column_span")
    }


def _parse_image_crop(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict or not value:
        _invalid("Image crop update must be a non-empty object.", field=field)
    _exact_keys(value, {"crop", "fit", "frame", "opacity", "rotation", "z_order"}, field)
    result: dict[str, Any] = {}
    if "crop" in value:
        parsed = parse_image_reference({"path": "placeholder.png", "crop": value["crop"]}, field)
        assert parsed is not None
        result["crop"] = parsed["crop"]
    if "fit" in value:
        fit = _text(value["fit"], f"{field}.fit", False)
        if fit not in {"contain", "cover", "stretch"}:
            _invalid("Image fit must be contain, cover, or stretch.", field=f"{field}.fit")
        result["fit"] = fit
    if "frame" in value:
        result["frame"] = _parse_frame(value["frame"], f"{field}.frame")
    if "opacity" in value:
        result["opacity"] = _number(value["opacity"], 0.0, 1.0, f"{field}.opacity")
    if "rotation" in value:
        result["rotation"] = _number(value["rotation"], -360.0, 360.0, f"{field}.rotation")
    if "z_order" in value:
        result["z_order"] = _integer(value["z_order"], 0, 10_000, f"{field}.z_order")
    return result


def _parse_text_update(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Text update must be an object.", field=field)
    _exact_keys(value, {"paragraphs", "text"}, field)
    if "paragraphs" in value:
        paragraphs = value["paragraphs"]
        if type(paragraphs) is not list or not paragraphs:
            _invalid("Text paragraphs must be a non-empty array.", field=f"{field}.paragraphs")
        return {"paragraphs": [_text(item, f"{field}.paragraphs") for item in paragraphs]}
    return {"text": _text(value.get("text", ""), f"{field}.text")}


def _parse_text_style(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict or not value:
        _invalid("Text style must be a non-empty object.", field=field)
    allowed = {"alignment", "autofit", "bold", "bullet", "color", "font", "font_size", "italic", "line_spacing", "numbering", "underline"}
    _exact_keys(value, allowed, field)
    result = dict(value)
    for key in ("bold", "italic", "underline", "autofit", "bullet", "numbering"):
        if key in result and type(result[key]) is not bool:
            _invalid("Text style boolean is invalid.", field=f"{field}.{key}")
    if "font_size" in result:
        result["font_size"] = _number(result["font_size"], 1.0, 400.0, f"{field}.font_size")
    if "line_spacing" in result:
        result["line_spacing"] = _number(result["line_spacing"], 0.5, 10.0, f"{field}.line_spacing")
    if "alignment" in result and result["alignment"] not in {"center", "justify", "left", "right"}:
        _invalid("Text alignment is unsupported.", field=f"{field}.alignment")
    if result.get("bullet") is True and result.get("numbering") is True:
        _invalid("Text cannot be both bulleted and numbered.", field=field)
    if "color" in result:
        result["color"] = _color(result["color"], f"{field}.color")
    if "font" in result:
        result["font"] = _text(result["font"], f"{field}.font", False)
    return result


def _parse_frame(value: Any, field: str) -> dict[str, int]:
    if type(value) is not dict:
        _invalid("Object frame must be an object.", field=field)
    _exact_keys(value, {"cx", "cy", "x", "y"}, field)
    return {
        "x": _integer(value.get("x"), 0, 100_000_000, f"{field}.x"),
        "y": _integer(value.get("y"), 0, 100_000_000, f"{field}.y"),
        "cx": _integer(value.get("cx"), 1, 100_000_000, f"{field}.cx"),
        "cy": _integer(value.get("cy"), 1, 100_000_000, f"{field}.cy"),
    }


def _parse_style_value(value: Any, field: str, kind: str) -> Any:
    if type(value) not in {str, dict}:
        _invalid("Shape style must be a color string or object.", field=field)
    if type(value) is str:
        return "none" if value == "none" else _color(value, field)
    allowed = {
        "fill": {"color"},
        "line": {"color", "dash", "opacity", "width"},
        "shadow": {"angle", "blur", "color", "distance", "opacity"},
    }[kind]
    _exact_keys(value, allowed, field)
    result = dict(value)
    if "color" in result:
        result["color"] = _color(result["color"], f"{field}.color")
    if "opacity" in result:
        result["opacity"] = _number(
            result["opacity"], 0.0, 1.0, f"{field}.opacity"
        )
    if "width" in result:
        result["width"] = _integer(
            result["width"], 0, 10_000_000, f"{field}.width"
        )
    for key, maximum in (("blur", 100_000_000), ("distance", 100_000_000)):
        if key in result:
            result[key] = _integer(result[key], 0, maximum, f"{field}.{key}")
    if "angle" in result:
        result["angle"] = _number(
            result["angle"], -360.0, 360.0, f"{field}.angle"
        )
    if "dash" in result:
        result["dash"] = _text(result["dash"], f"{field}.dash", False)
        if result["dash"] not in {
            "dash", "dashDot", "dot", "lgDash", "lgDashDot", "lgDashDotDot",
            "solid", "sysDash", "sysDashDot", "sysDashDotDot", "sysDot",
        }:
            _invalid("Shape line dash is unsupported.", field=f"{field}.dash")
    return result


def _color(value: Any, field: str) -> str:
    normalized = _text(value, field, False).lstrip("#").upper()
    if len(normalized) != 6 or any(
        character not in "0123456789ABCDEF" for character in normalized
    ):
        _invalid("Color must be a six-digit RGB value.", field=field)
    return normalized


def _precondition(value: Any, field: str) -> str | None:
    if value is None:
        return None
    digest = _text(value, f"{field}.precondition_sha256", False).casefold()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        _invalid("precondition_sha256 must be a SHA-256 hex digest.", field=field)
    return digest


def _exact_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown PPTX object argument.", field=field, unknown=unknown)


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.", field=field)
    return value


def _number(value: Any, minimum: float, maximum: float, field: str) -> float:
    if type(value) not in {int, float} or isinstance(value, bool) or not minimum <= float(value) <= maximum:
        _invalid(f"Number must be between {minimum} and {maximum}.", field=field)
    return float(value)


def _text(value: Any, field: str, allow_empty: bool = True) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _invalid("Value must be a string.", field=field)
    if len(value.encode("utf-8", errors="strict")) > MAX_ARGUMENT_TEXT:
        _invalid("Text exceeds the byte limit.", field=field)
    return value


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
