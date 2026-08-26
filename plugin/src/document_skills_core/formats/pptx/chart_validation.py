"""Deep chart, axis, cache, and embedded-workbook consistency validation."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS, local_name
from .embedded_workbook import EmbeddedWorkbook, load_embedded_workbook

_C = f"{{{NS['c']}}}"
_CHART_TYPES_WITHOUT_AXES = {"doughnutChart", "ofPieChart", "pie3DChart", "pieChart"}
_AXIS_TYPES = {"catAx", "dateAx", "serAx", "valAx"}
_REFERENCE_TYPES = {"multiLvlStrRef", "numRef", "strRef"}
_LITERAL_TYPES = {"multiLvlStrLit", "numLit", "strLit"}
_MAX_FAILURES = 128


def validate_chart_packages(package: Any) -> dict[str, Any]:
    failures: list[str] = []
    total_axes = 0
    total_formulas = 0
    total_series = 0
    workbook_ranges_checked = 0
    workbook_ranges_unchecked = 0
    for part in package.chart_parts():
        root = package.xml(part)
        chart_space = local_name(root.tag)
        if chart_space != "chartSpace":
            failures.append(f"chart-root:{part}")
            continue
        formulas: list[tuple[str, list[Any], bool]] = []
        series, chart_types = _validate_series(part, root, formulas, failures)
        axes = _validate_axes(part, root, chart_types, failures)
        checked, unchecked = _validate_workbook(
            package,
            part,
            formulas,
            failures,
        )
        total_series += series
        total_axes += axes
        total_formulas += len(formulas)
        workbook_ranges_checked += checked
        workbook_ranges_unchecked += unchecked
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PPTX chart/cache/workbook validation failed.",
            details={"failures": failures[:_MAX_FAILURES]},
        )
    return {
        "axes": total_axes,
        "charts": len(package.chart_parts()),
        "formulas": total_formulas,
        "series": total_series,
        "workbook_ranges_checked": workbook_ranges_checked,
        "workbook_ranges_unchecked": workbook_ranges_unchecked,
    }


def _validate_series(
    part: str,
    root: Any,
    formulas: list[tuple[str, list[Any], bool]],
    failures: list[str],
) -> tuple[int, list[Any]]:
    total = 0
    chart_types = [
        node
        for node in root.iter()
        if local_name(node.tag).endswith("Chart")
        and local_name(node.tag) not in {"chart", "chartSpace"}
    ]
    for chart in chart_types:
        series = [node for node in list(chart) if local_name(node.tag) == "ser"]
        total += len(series)
        indexes = [_value(node.find(f"{_C}idx")) for node in series]
        orders = [_value(node.find(f"{_C}order")) for node in series]
        if not _unique_nonnegative(indexes):
            failures.append(f"chart-series-index:{part}:{local_name(chart.tag)}")
        if not _unique_nonnegative(orders):
            failures.append(f"chart-series-order:{part}:{local_name(chart.tag)}")
        for ordinal, item in enumerate(series, 1):
            data_containers = [
                node
                for node in item.iter()
                if local_name(node.tag) in _REFERENCE_TYPES | _LITERAL_TYPES
            ]
            if not data_containers:
                failures.append(f"chart-series-data:{part}:{ordinal}")
            for container in data_containers:
                _validate_data_container(
                    part,
                    ordinal,
                    container,
                    formulas,
                    failures,
                )
    return total, chart_types


def _validate_data_container(
    part: str,
    ordinal: int,
    container: Any,
    formulas: list[tuple[str, list[Any], bool]],
    failures: list[str],
) -> None:
    kind = local_name(container.tag)
    numeric = kind.startswith("num")
    cache = next(
        (
            node
            for node in container.iter()
            if local_name(node.tag) in {"multiLvlStrCache", "numCache", "numLit", "strCache", "strLit"}
        ),
        None,
    )
    if cache is None:
        failures.append(f"chart-cache-missing:{part}:{ordinal}:{kind}")
        return
    values = _cache_values(cache, numeric=numeric, part=part, failures=failures)
    if kind in _REFERENCE_TYPES:
        formula_node = container.find(f"{_C}f")
        formula = "" if formula_node is None else (formula_node.text or "").strip()
        if not formula:
            failures.append(f"chart-formula-missing:{part}:{ordinal}:{kind}")
        else:
            formulas.append((formula, values, numeric))


def _cache_values(
    cache: Any,
    *,
    numeric: bool,
    part: str,
    failures: list[str],
) -> list[Any]:
    points: list[tuple[int, Any]] = []
    for point in cache.iter(f"{_C}pt"):
        try:
            index = int(point.attrib.get("idx", ""))
        except ValueError:
            failures.append(f"chart-cache-index:{part}")
            continue
        value_node = point.find(f"{_C}v")
        value: Any = "" if value_node is None else value_node.text or ""
        if numeric:
            try:
                value = float(value)
            except ValueError:
                failures.append(f"chart-cache-number:{part}:{index}")
        points.append((index, value))
    indexes = [index for index, _value_item in points]
    if len(indexes) != len(set(indexes)):
        failures.append(f"chart-cache-duplicate-index:{part}")
    point_count = next(
        (node for node in list(cache) if local_name(node.tag) == "ptCount"),
        None,
    )
    try:
        declared = int(_value(point_count))
    except ValueError:
        declared = -1
    if declared != len(points):
        failures.append(f"chart-cache-count:{part}:{declared}:{len(points)}")
    return [value for _index, value in sorted(points)]


def _validate_axes(
    part: str,
    root: Any,
    chart_types: list[Any],
    failures: list[str],
) -> int:
    axes = [node for node in root.iter() if local_name(node.tag) in _AXIS_TYPES]
    identifiers = [_value(axis.find(f"{_C}axId")) for axis in axes]
    if len(identifiers) != len(set(identifiers)) or any(
        not _integer_string(item) for item in identifiers
    ):
        failures.append(f"chart-axis-id:{part}")
    defined = set(identifiers)
    for axis in axes:
        cross_axis = _value(axis.find(f"{_C}crossAx"))
        if cross_axis not in defined:
            failures.append(f"chart-cross-axis:{part}:{cross_axis or 'missing'}")
    for chart in chart_types:
        kind = local_name(chart.tag)
        references = [_value(node) for node in chart.findall(f"{_C}axId")]
        if kind in _CHART_TYPES_WITHOUT_AXES:
            if references:
                failures.append(f"chart-unexpected-axis:{part}:{kind}")
        elif len(references) < 2 or any(reference not in defined for reference in references):
            failures.append(f"chart-axis-reference:{part}:{kind}")
    return len(axes)


def _validate_workbook(
    package: Any,
    part: str,
    formulas: list[tuple[str, list[Any], bool]],
    failures: list[str],
) -> tuple[int, int]:
    workbook_relationships = [
        relationship
        for relationship in package.part_rels(part)
        if relationship.target_mode == "Internal"
        and relationship.resolved_target is not None
        and (
            relationship.resolved_target.startswith("ppt/embeddings/")
            or relationship.relationship_type.rsplit("/", 1)[-1] == "package"
        )
    ]
    if formulas and len(workbook_relationships) != 1:
        failures.append(f"chart-workbook-count:{part}:{len(workbook_relationships)}")
        return 0, len(formulas)
    if not workbook_relationships:
        return 0, 0
    target = workbook_relationships[0].resolved_target
    assert target is not None
    content_type = (package.content_type_for(target) or "").casefold()
    if (
        "spreadsheetml" not in content_type
        or not target.casefold().endswith(".xlsx")
    ):
        failures.append(f"chart-workbook-content-type:{part}")
    try:
        workbook = load_embedded_workbook(package.parts[target])
    except (KeyError, OSError, ValueError):
        failures.append(f"chart-workbook-invalid:{part}")
        return 0, len(formulas)
    checked = 0
    unchecked = 0
    for formula, cached, numeric in formulas:
        actual = workbook.values(formula, numeric=numeric)
        if actual is None:
            unchecked += 1
            continue
        checked += 1
        if not _values_equal(actual, cached, numeric=numeric):
            failures.append(f"chart-workbook-cache-mismatch:{part}:{checked}")
    return checked, unchecked


def _values_equal(left: list[Any], right: list[Any], *, numeric: bool) -> bool:
    if len(left) != len(right):
        return False
    if numeric:
        return all(
            isinstance(a, (int, float))
            and isinstance(b, (int, float))
            and abs(float(a) - float(b)) <= 1e-9
            for a, b in zip(left, right, strict=True)
        )
    return [str(value) for value in left] == [str(value) for value in right]


def _unique_nonnegative(values: list[str]) -> bool:
    return (
        len(values) == len(set(values))
        and all(value.isdigit() and int(value) >= 0 for value in values)
    )


def _integer_string(value: str) -> bool:
    return value.removeprefix("-").isdigit()


def _value(node: Any) -> str:
    return "" if node is None else node.attrib.get("val", "")
