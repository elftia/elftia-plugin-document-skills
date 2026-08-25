"""Candidate-derived vector-shape validation for PDF create promotion."""

from typing import Any

from .content_streams import extract_content_stream
from .content_tokenizer import tokenize_content_stream
from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .page_tree import PageInfo


_TOLERANCE = 0.0001
_PAINT_OPERATORS = frozenset({"S", "f", "B"})
_PATH_OPERATORS = frozenset({"re", "m", "l", "c", "h"})


def actual_shape_draws(
    model: PdfObjectModel,
    pages: list[PageInfo],
) -> list[dict[str, Any]]:
    """Read vector paths and styles from reopened page content and resources."""
    records: list[dict[str, Any]] = []
    for page in pages:
        content = extract_content_stream(model, page.contents, page.page_number)
        active: dict[str, Any] | None = None
        for operator, operands in tokenize_content_stream(content):
            if operator == "gs":
                resource = operands[-1] if operands else None
                active = {
                    "page": page.page_number,
                    "resource": resource,
                    "graphics_state": _graphics_state_record(
                        model,
                        page.resources,
                        resource,
                    ),
                    "operators": [],
                }
                continue
            if active is None:
                continue
            active["operators"].append((operator, operands))
            if operator in _PAINT_OPERATORS:
                records.append(_public_shape_record(active))
                active = None
            elif operator in {"Q", "Do", "BT", "ET", "gs"}:
                active = None
    return records


def shape_evidence_mismatches(
    document: dict[str, Any],
    creation: dict[str, Any] | None,
    actual: list[dict[str, Any]],
    *,
    candidate_page_count: int,
    dynamic_source_pages: set[int],
    mapped_shape_positions: list[tuple[int, int]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compare reopened graphics operations to request-derived shape semantics."""
    expected, placement_mismatches = _requested_shapes(
        document,
        creation,
        candidate_page_count=candidate_page_count,
        dynamic_source_pages=dynamic_source_pages,
        mapped_shape_positions=mapped_shape_positions,
    )
    if placement_mismatches:
        return placement_mismatches, []
    mismatches: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    if len(actual) != len(expected):
        mismatches.append({
            "reason": "shape-count-mismatch",
            "expected": len(expected),
            "actual": len(actual),
        })
    for index, request_shape in enumerate(expected):
        if index >= len(actual):
            break
        candidate = actual[index]
        reason = _shape_mismatch(request_shape, candidate)
        if reason is not None:
            mismatches.append({
                "reason": reason,
                "page": request_shape["page"],
                "block_index": request_shape["block_index"],
                "kind": request_shape["kind"],
            })
            continue
        evidence.append(candidate)
    return mismatches, evidence


def _graphics_state_record(
    model: PdfObjectModel,
    resources: PdfDict | None,
    resource: Any,
) -> dict[str, Any]:
    if resources is None or not isinstance(resource, str):
        return {"indirect": False}
    ext_gstates = resources.get("/ExtGState")
    if isinstance(ext_gstates, IndirectReference):
        ext_gstates = model.get_object(ext_gstates).value
    if not isinstance(ext_gstates, PdfDict):
        return {"indirect": False}
    reference = ext_gstates.get(resource)
    if not isinstance(reference, IndirectReference):
        return {"indirect": False}
    obj = model.get_object(reference)
    if not isinstance(obj.value, PdfDict):
        return {"indirect": True, "object": obj.obj_num}
    return {
        "indirect": True,
        "object": obj.obj_num,
        "object_sha256": obj.sha256,
        "type": obj.value.get("/Type"),
        "fill_opacity": obj.value.get("/ca"),
        "stroke_opacity": obj.value.get("/CA"),
    }


def _public_shape_record(active: dict[str, Any]) -> dict[str, Any]:
    operators = active["operators"]
    path = [
        (operator, operands)
        for operator, operands in operators
        if operator in _PATH_OPERATORS
    ]
    stroke = _last_operands(operators, "RG")
    fill = _last_operands(operators, "rg")
    dash_operands = _last_operands(operators, "d")
    dash = None
    if (
        isinstance(dash_operands, list)
        and len(dash_operands) == 2
        and isinstance(dash_operands[0], list)
        and _numbers_match(dash_operands[1], 0.0)
    ):
        dash = dash_operands[0]
    graphics_state = active["graphics_state"]
    return {
        "page": active["page"],
        "resource": active["resource"],
        "graphics_state_object": graphics_state.get("object"),
        "graphics_state_object_sha256": graphics_state.get("object_sha256"),
        "graphics_state_indirect": graphics_state.get("indirect", False),
        "graphics_state_type": graphics_state.get("type"),
        "fill_opacity": graphics_state.get("fill_opacity"),
        "stroke_opacity": graphics_state.get("stroke_opacity"),
        "stroke": stroke,
        "fill": fill,
        "dash": dash,
        "kind": _shape_kind(path),
        "bbox": _path_bbox(path),
        "path_operators": [operator for operator, _operands in path],
        "paint_operator": operators[-1][0] if operators else None,
        "operators": [
            [operator, operands]
            for operator, operands in operators
        ],
    }


def _requested_shapes(
    document: dict[str, Any],
    creation: dict[str, Any] | None,
    *,
    candidate_page_count: int,
    dynamic_source_pages: set[int],
    mapped_shape_positions: list[tuple[int, int]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requested: list[dict[str, Any]] = []
    for page_number, page in enumerate(document.get("pages", []), start=1):
        for block_index, block in enumerate(page.get("blocks", [])):
            if block.get("type") != "vector_shape":
                continue
            shape = block["shape"]
            requested.append({
                **shape,
                "page": page_number,
                "block_index": block_index,
                "opacity": shape.get("opacity", 1.0),
                "dash": shape.get("dash", []),
                "corner_radius": shape.get("corner_radius", 0.0),
            })
    if creation is None:
        if any(shape["page"] in dynamic_source_pages for shape in requested):
            return requested, [{
                "reason": "shape-creation-record-count",
                "expected": len(requested),
                "actual": None,
            }]
        return requested, []
    positions, mismatches = _creation_shape_positions(
        creation,
        expected_count=len(requested),
        candidate_page_count=candidate_page_count,
        mapped_shape_positions=mapped_shape_positions,
    )
    if mismatches:
        return requested, mismatches
    assert positions is not None
    for index, (shape, (page, _block_index)) in enumerate(zip(requested, positions)):
        if shape["page"] in dynamic_source_pages:
            shape["page"] = page
        elif shape["page"] != page:
            return requested, [{
                "reason": "shape-creation-page-mismatch",
                "index": index,
            }]
    return requested, []


def _creation_shape_positions(
    creation: dict[str, Any],
    *,
    expected_count: int,
    candidate_page_count: int,
    mapped_shape_positions: list[tuple[int, int]] | None,
) -> tuple[list[tuple[int, int]] | None, list[dict[str, Any]]]:
    records = creation.get("shapes")
    if not isinstance(records, list) or len(records) != expected_count:
        return None, [{
            "reason": "shape-creation-record-count",
            "expected": expected_count,
            "actual": len(records) if isinstance(records, list) else None,
        }]
    positions: list[tuple[int, int]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            return None, [{"reason": "shape-creation-record-invalid", "index": index}]
        page = record.get("page")
        block_index = record.get("block_index")
        if type(page) is not int or not 1 <= page <= candidate_page_count:
            return None, [{"reason": "shape-creation-page-invalid", "index": index}]
        if type(block_index) is not int or block_index < 0:
            return None, [{"reason": "shape-creation-record-invalid", "index": index}]
        positions.append((page, block_index))
    if any(left >= right for left, right in zip(positions, positions[1:])):
        return None, [{"reason": "shape-creation-order-mismatch"}]
    if mapped_shape_positions != positions:
        return None, [{"reason": "shape-creation-mapping-invalid"}]
    return positions, []


def _shape_mismatch(expected: dict[str, Any], actual: dict[str, Any]) -> str | None:
    graphics_valid = (
        actual["graphics_state_indirect"]
        and actual["graphics_state_type"] == "/ExtGState"
        and _numbers_match(actual["fill_opacity"], expected["opacity"])
        and _numbers_match(actual["stroke_opacity"], expected["opacity"])
    )
    if not graphics_valid:
        return "shape-graphics-state-mismatch"
    if actual["page"] != expected["page"]:
        return "shape-page-mismatch"
    if actual["kind"] != expected["kind"]:
        return "shape-kind-mismatch"
    if not _values_match(actual["stroke"], expected.get("stroke")):
        return "shape-stroke-mismatch"
    if not _values_match(actual["fill"], expected.get("fill")):
        return "shape-fill-mismatch"
    if not _values_match(actual["dash"], expected["dash"]):
        return "shape-dash-mismatch"
    expected_operators = _expected_operators(expected)
    if not _values_match(actual["operators"], expected_operators):
        return "shape-operators-mismatch"
    return None


def _expected_operators(shape: dict[str, Any]) -> list[list[Any]]:
    operators: list[list[Any]] = []
    if shape.get("stroke") is not None:
        operators.append(["RG", list(shape["stroke"])])
    if shape.get("fill") is not None:
        operators.append(["rg", list(shape["fill"])])
    operators.append(["d", [list(shape["dash"]), 0]])
    operators.extend(
        [operator, operands]
        for operator, operands in _expected_path(shape)
    )
    operators.append([_expected_paint(shape), []])
    return operators


def _expected_path(shape: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    x = float(shape["x"])
    y = float(shape["y"])
    width = float(shape["width"])
    height = float(shape["height"])
    if shape["kind"] == "rectangle":
        return [("re", [x, y, width, height])]
    if shape["kind"] == "line":
        return [("m", [x, y]), ("l", [x + width, y + height])]
    if shape["kind"] == "rounded_rectangle":
        radius = min(float(shape["corner_radius"]), width / 2.0, height / 2.0)
        control = radius * 0.5522847498307793
        return [
            ("m", [x + radius, y]),
            ("l", [x + width - radius, y]),
            ("c", [x + width - control, y, x + width, y + control, x + width, y + radius]),
            ("l", [x + width, y + height - radius]),
            ("c", [x + width, y + height - control, x + width - control, y + height, x + width - radius, y + height]),
            ("l", [x + radius, y + height]),
            ("c", [x + control, y + height, x, y + height - control, x, y + height - radius]),
            ("l", [x, y + radius]),
            ("c", [x, y + control, x + control, y, x + radius, y]),
            ("h", []),
        ]
    center_x = x + width / 2.0
    center_y = y + height / 2.0
    radius_x = width / 2.0
    radius_y = height / 2.0
    kappa = 0.5522847498307793
    return [
        ("m", [center_x - radius_x, center_y]),
        ("c", [center_x - radius_x, center_y + radius_y * kappa, center_x - radius_x * kappa, center_y + radius_y, center_x, center_y + radius_y]),
        ("c", [center_x + radius_x * kappa, center_y + radius_y, center_x + radius_x, center_y + radius_y * kappa, center_x + radius_x, center_y]),
        ("c", [center_x + radius_x, center_y - radius_y * kappa, center_x + radius_x * kappa, center_y - radius_y, center_x, center_y - radius_y]),
        ("c", [center_x - radius_x * kappa, center_y - radius_y, center_x - radius_x, center_y - radius_y * kappa, center_x - radius_x, center_y]),
        ("h", []),
    ]


def _expected_paint(shape: dict[str, Any]) -> str:
    if shape.get("stroke") is not None and shape.get("fill") is not None:
        return "B"
    if shape.get("fill") is not None:
        return "f"
    return "S"


def _last_operands(
    operators: list[tuple[str, list[Any]]],
    wanted: str,
) -> list[Any] | None:
    matches = [operands for operator, operands in operators if operator == wanted]
    return matches[-1] if matches else None


def _shape_kind(path: list[tuple[str, list[Any]]]) -> str | None:
    signature = [operator for operator, _operands in path]
    if signature == ["re"]:
        return "rectangle"
    if signature == ["m", "l"]:
        return "line"
    if signature == ["m", "c", "c", "c", "c", "h"]:
        return "ellipse"
    if signature == ["m", "l", "c", "l", "c", "l", "c", "l", "c", "h"]:
        return "rounded_rectangle"
    return None


def _path_bbox(path: list[tuple[str, list[Any]]]) -> list[float] | None:
    points: list[tuple[float, float]] = []
    for operator, operands in path:
        if operator == "re" and len(operands) == 4:
            x, y, width, height = (float(value) for value in operands)
            points.extend([(x, y), (x + width, y + height)])
        elif operator in {"m", "l", "c"} and len(operands) % 2 == 0:
            points.extend(
                (float(operands[index]), float(operands[index + 1]))
                for index in range(0, len(operands), 2)
            )
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _values_match(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return _numbers_match(left, right)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _values_match(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    if isinstance(left, tuple) and isinstance(right, tuple):
        return len(left) == len(right) and all(
            _values_match(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    return left == right


def _numbers_match(left: Any, right: Any) -> bool:
    return (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
        and abs(float(left) - float(right)) <= _TOLERANCE
    )
