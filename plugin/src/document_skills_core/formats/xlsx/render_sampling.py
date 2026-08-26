"""Bounded workbook-risk sampling attached to XLSX PDF renders."""

from collections import Counter
from math import isfinite
from pathlib import Path
from typing import Any

from defusedxml.ElementTree import iterparse

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import (
    NS,
    REL_WORKSHEET,
    SHARED_STRINGS_PART,
    STYLES_PART,
    WORKBOOK_MAIN,
)
from .format_policy import assert_package_matches_path, format_id
from .mapping import col_to_num, num_to_col, parse_ref
from .render_package import RenderPackageIndex
from .relationships import relationship_map

_DEFAULT_COLUMN_WIDTH = 8.43
_WIDE_COLUMN_THRESHOLD = 80.0
_WORKSHEET_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
)
_MAIN_NS = NS["main"]
_TRUE_VALUES = frozenset({"1", "true", "on"})
_PAPER_ID_TO_SIZE = {
    "1": "letter",
    "3": "tabloid",
    "5": "legal",
    "8": "a3",
    "9": "a4",
    "11": "a5",
    "12": "b4",
    "13": "b5",
}


def sample_render_source(
    input_path: Path,
    arguments: dict[str, Any],
    *,
    package: RenderPackageIndex | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Preflight a safe XLSX and report bounded layout-risk evidence."""

    package = package or RenderPackageIndex.open(input_path)
    assert_package_matches_path(input_path, package.workbook_format)
    workbook_root, sheets = _discover_sheets(package)
    selected = sheets[: arguments["max_sheets"]]
    print_metadata = _selected_print_metadata(workbook_root, selected)
    scans = [
        _scan_sheet(
            package,
            sheet,
            print_metadata.get(sheet["order"], {}),
            max_cells=arguments["max_cells_per_sheet"],
        )
        for sheet in selected
    ]
    shared_indexes: set[int] = set()
    style_indexes: set[int] = set()
    for scan in scans:
        _resolve_cell_defaults(scan)
        for cell in scan["cells"]:
            if cell["shared_index"] is not None:
                shared_indexes.add(cell["shared_index"])
            style_indexes.add(cell["style_index"])
    shared_values = _read_selected_shared_strings(package, shared_indexes)
    alignments = _read_selected_alignments(package, style_indexes)

    findings: list[dict[str, Any]] = []
    finding_counts: Counter[str] = Counter()
    samples = []
    for scan in scans:
        sample = _finalize_sheet_sample(
            scan,
            shared_values=shared_values,
            alignments=alignments,
        )
        samples.append(sample)
        for finding in sample.pop("findings"):
            finding_counts[finding["kind"]] += 1
            if len(findings) < arguments["max_findings"]:
                findings.append(finding)
    truncated_sheets = max(0, len(sheets) - len(selected))
    truncated_findings = max(0, sum(finding_counts.values()) - len(findings))
    warnings = _sampling_warnings(
        finding_counts=finding_counts,
        truncated_sheets=truncated_sheets,
        truncated_findings=truncated_findings,
    )
    return (
        {
            "source_format": format_id(input_path),
            "workbook_format": package.workbook_format,
            "sheet_count": len(sheets),
            "visible_sheet_count": sum(
                sheet.get("state", "visible") == "visible" for sheet in sheets
            ),
            "sampled_sheet_count": len(samples),
            "truncated_sheet_count": truncated_sheets,
            "samples": samples,
            "risk_findings": findings,
            "risk_finding_counts": dict(sorted(finding_counts.items())),
            "truncated_finding_count": truncated_findings,
            "security": package.security,
            "scope": (
                "Workbook metadata and cell-risk sampling accompany the rendered PDF; "
                "they do not prove per-object visual parity."
            ),
        },
        warnings,
    )


def _discover_sheets(
    package: RenderPackageIndex,
) -> tuple[Any, list[dict[str, Any]]]:
    workbook_root = package.xml(WORKBOOK_MAIN)
    workbook_rels = relationship_map(
        package.workbook_relationships,
        WORKBOOK_MAIN,
    )
    sheets: list[dict[str, Any]] = []
    seen_relationship_ids: set[str] = set()
    seen_targets: set[str] = set()
    container = workbook_root.find(f"{{{_MAIN_NS}}}sheets")
    if container is None:
        return workbook_root, sheets
    for index, node in enumerate(container.findall(f"{{{_MAIN_NS}}}sheet")):
        relationship_id = node.attrib.get(f"{{{NS['r']}}}id", "")
        if not relationship_id or relationship_id in seen_relationship_ids:
            _unsafe(
                "Workbook sheet relationship ids must be unique and non-empty.",
                sheet_index=index,
                relationship_id=relationship_id,
            )
        seen_relationship_ids.add(relationship_id)
        relationship = workbook_rels.get(relationship_id)
        if relationship is None:
            _unsafe(
                "Workbook sheet relationship is missing.",
                sheet_index=index,
                relationship_id=relationship_id,
            )
        if (
            relationship.target_mode != "Internal"
            or relationship.resolved_target is None
        ):
            _unsafe(
                "Workbook sheet relationship must target a contained part.",
                sheet_index=index,
                relationship_id=relationship_id,
            )
        if relationship.relationship_type != REL_WORKSHEET:
            _unsafe(
                "Workbook sheet relationship type is not worksheet.",
                sheet_index=index,
                relationship_id=relationship_id,
                relationship_type=relationship.relationship_type,
            )
        part = relationship.resolved_target
        if not package.has_part(part):
            _unsafe(
                "Workbook sheet relationship target is missing.",
                sheet_index=index,
                part=part,
            )
        content_type = package.content_type_for(part)
        if content_type != _WORKSHEET_CONTENT_TYPE:
            _unsafe(
                "Workbook sheet target has an invalid content type.",
                sheet_index=index,
                part=part,
                content_type=content_type,
            )
        if part in seen_targets:
            _unsafe(
                "Workbook sheets must not share one worksheet target.",
                sheet_index=index,
                part=part,
            )
        seen_targets.add(part)
        sheets.append({
            "name": node.attrib.get("name", f"Sheet{index + 1}"),
            "order": index,
            "state": node.attrib.get("state", "visible"),
            "part": part,
        })
    return workbook_root, sheets


def _selected_print_metadata(
    workbook_root: Any,
    selected: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    by_order = {
        sheet["order"]: {
            "name": sheet["name"],
            "print_area": None,
            "print_titles": None,
        }
        for sheet in selected
    }
    defined_names = workbook_root.find(f"{{{_MAIN_NS}}}definedNames")
    if defined_names is None or not by_order:
        return by_order
    for item in defined_names.findall(f"{{{_MAIN_NS}}}definedName"):
        local_sheet_id = item.attrib.get("localSheetId")
        if local_sheet_id is None or not local_sheet_id.isdigit():
            continue
        sheet_order = int(local_sheet_id)
        metadata = by_order.get(sheet_order)
        if metadata is None:
            continue
        text = item.text or ""
        if item.attrib.get("name") == "_xlnm.Print_Area":
            metadata["print_area"] = _local_reference(text, metadata["name"])
        elif item.attrib.get("name") == "_xlnm.Print_Titles":
            rows = None
            columns = None
            for fragment in text.split(","):
                local = _local_reference(fragment, metadata["name"])
                if local is None:
                    continue
                if any(char.isdigit() for char in local):
                    rows = local.replace("$", "")
                else:
                    columns = local.replace("$", "")
            metadata["print_titles"] = {"rows": rows, "columns": columns}
    return by_order


def _scan_sheet(
    package: RenderPackageIndex,
    sheet: dict[str, Any],
    print_metadata: dict[str, Any],
    *,
    max_cells: int,
) -> dict[str, Any]:
    scan: dict[str, Any] = {
        "sheet": sheet["name"],
        "state": sheet.get("state", "visible"),
        "dimension": "",
        "cells": [],
        "observed_cells": 0,
        "cell_sampling_truncated": False,
        "hidden_rows": 0,
        "hidden_columns": 0,
        "columns": [],
        "wide_columns": [],
        "wide_column_count": 0,
        "table_count": _table_count(package, sheet.get("part")),
        "chart_count": _chart_count(package, sheet.get("part")),
        "print_area": print_metadata.get("print_area"),
        "print_titles": print_metadata.get("print_titles"),
        "page_setup": None,
        "fit_to_page": False,
        "header_footer_present": False,
    }
    sheet_part = sheet.get("part")
    if not sheet_part or not package.has_part(sheet_part):
        _unsafe("Selected worksheet part is missing.", part=sheet_part)
    try:
        with package.open_part(sheet_part) as source_stream:
            _scan_sheet_stream(source_stream, scan, max_cells=max_cells)
    except DocumentSkillsError:
        raise
    except Exception as error:
        _unsafe(
            "Selected worksheet could not be parsed safely.",
            part=sheet_part,
            reason=type(error).__name__,
        )
    if scan["page_setup"] is not None:
        scan["page_setup"]["fit_to_page"] = scan["fit_to_page"]
    return scan


def _scan_sheet_stream(
    source_stream: Any,
    scan: dict[str, Any],
    *,
    max_cells: int,
) -> None:
    inside_cell = False
    row_style_index = 0
    for event, element in iterparse(
        source_stream,
        events=("start", "end"),
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    ):
        if event == "start":
            if element.tag == f"{{{_MAIN_NS}}}c":
                inside_cell = True
            elif element.tag == f"{{{_MAIN_NS}}}row":
                row_style_index = _integer_attribute(element, "s", 0)
                if _bool_attribute(element, "hidden"):
                    scan["hidden_rows"] += 1
            elif element.tag == f"{{{_MAIN_NS}}}headerFooter":
                scan["header_footer_present"] = any(
                    _bool_attribute(element, name)
                    for name in ("differentFirst", "differentOddEven")
                )
            continue

        if inside_cell:
            if element.tag == f"{{{_MAIN_NS}}}c":
                if len(scan["cells"]) < max_cells:
                    scan["cells"].append(_sample_cell(element, row_style_index))
                    scan["observed_cells"] += 1
                elif not scan["cell_sampling_truncated"]:
                    scan["observed_cells"] += 1
                    scan["cell_sampling_truncated"] = True
                element.clear()
                inside_cell = False
            continue

        if element.tag == f"{{{_MAIN_NS}}}dimension":
            scan["dimension"] = element.attrib.get("ref", "")
        elif element.tag == f"{{{_MAIN_NS}}}col":
            column = _sample_column(element)
            scan["columns"].append(column)
            if column["hidden"]:
                scan["hidden_columns"] += column["max"] - column["min"] + 1
            if (column["width"] or 0) > _WIDE_COLUMN_THRESHOLD:
                scan["wide_column_count"] += 1
                if len(scan["wide_columns"]) < 32:
                    scan["wide_columns"].append(column["ref"])
        elif element.tag == f"{{{_MAIN_NS}}}pageSetUpPr":
            scan["fit_to_page"] = _bool_attribute(element, "fitToPage")
        elif element.tag == f"{{{_MAIN_NS}}}pageSetup":
            scan["page_setup"] = _sample_page_setup(element)
        elif element.tag in {
            f"{{{_MAIN_NS}}}{name}"
            for name in (
                "oddHeader",
                "oddFooter",
                "evenHeader",
                "evenFooter",
                "firstHeader",
                "firstFooter",
            )
        }:
            scan["header_footer_present"] = (
                scan["header_footer_present"] or bool(element.text)
            )
        elif element.tag == f"{{{_MAIN_NS}}}row":
            row_style_index = 0
        element.clear()


def _sample_cell(element: Any, row_style_index: int) -> dict[str, Any]:
    cell_type = element.attrib.get("t", "n")
    value_element = element.find(f"{{{_MAIN_NS}}}v")
    shared_index = None
    if cell_type == "s" and value_element is not None:
        text = value_element.text or ""
        shared_index = int(text) if text.isdigit() else None
        value = None
    elif cell_type == "inlineStr":
        value = "".join(
            item.text or ""
            for item in element.findall(f".//{{{_MAIN_NS}}}t")
        )
    else:
        value = None if value_element is None else value_element.text
    if "s" in element.attrib:
        style_index = _integer_attribute(element, "s", 0)
    elif row_style_index:
        style_index = row_style_index
    else:
        style_index = None
    return {
        "ref": element.attrib.get("r", ""),
        "value": value,
        "shared_index": shared_index,
        "style_index": style_index,
        "column_width": _DEFAULT_COLUMN_WIDTH,
    }


def _sample_column(element: Any) -> dict[str, Any]:
    first = _integer_attribute(element, "min", 1)
    last = _integer_attribute(element, "max", first)
    width = element.attrib.get("width")
    return {
        "min": first,
        "max": last,
        "ref": num_to_col(first) if first == last else f"{num_to_col(first)}:{num_to_col(last)}",
        "width": _optional_float(width),
        "hidden": _bool_attribute(element, "hidden"),
        "style_index": _integer_attribute(element, "style", 0),
    }


def _sample_page_setup(element: Any) -> dict[str, Any]:
    paper_size = element.attrib.get("paperSize", "1")
    return {
        "orientation": element.attrib.get("orientation", "portrait"),
        "paper_size": _PAPER_ID_TO_SIZE.get(paper_size, paper_size),
        "fit_to_width": _optional_integer(element.attrib.get("fitToWidth")),
        "fit_to_height": _optional_integer(element.attrib.get("fitToHeight")),
        "scale": _optional_integer(element.attrib.get("scale")),
    }


def _resolve_cell_defaults(scan: dict[str, Any]) -> None:
    columns = sorted(scan["columns"], key=lambda item: item["min"])
    for cell in scan["cells"]:
        column = _column_for_cell(columns, cell["ref"])
        if column is not None:
            cell["column_width"] = column["width"] or _DEFAULT_COLUMN_WIDTH
            if cell["style_index"] is None:
                cell["style_index"] = column["style_index"]
        if cell["style_index"] is None:
            cell["style_index"] = 0


def _column_for_cell(
    columns: list[dict[str, Any]],
    cell_ref: str,
) -> dict[str, Any] | None:
    parsed = parse_ref(cell_ref)
    if parsed is None:
        return None
    column_number = col_to_num(parsed[0])
    low = 0
    high = len(columns)
    while low < high:
        middle = (low + high) // 2
        if columns[middle]["min"] <= column_number:
            low = middle + 1
        else:
            high = middle
    if low:
        candidate = columns[low - 1]
        if candidate["min"] <= column_number <= candidate["max"]:
            return candidate
    return None


def _read_selected_shared_strings(
    package: RenderPackageIndex,
    selected_indexes: set[int],
) -> dict[int, str]:
    if not package.has_part(SHARED_STRINGS_PART) or not selected_indexes:
        return {}
    unresolved = set(selected_indexes)
    result: dict[int, str] = {}
    index = 0
    try:
        with package.open_part(SHARED_STRINGS_PART) as source_stream:
            for _event, element in iterparse(
                source_stream,
                events=("end",),
                forbid_dtd=True,
                forbid_entities=True,
                forbid_external=True,
            ):
                if element.tag != f"{{{_MAIN_NS}}}si":
                    continue
                if index in unresolved:
                    result[index] = "".join(
                        item.text or ""
                        for item in element.findall(f".//{{{_MAIN_NS}}}t")
                    )
                    unresolved.remove(index)
                index += 1
                element.clear()
                if not unresolved:
                    break
    except DocumentSkillsError:
        raise
    except Exception as error:
        _unsafe(
            "Shared strings could not be parsed safely.",
            part=SHARED_STRINGS_PART,
            reason=type(error).__name__,
        )
    return result


def _read_selected_alignments(
    package: RenderPackageIndex,
    selected_indexes: set[int],
) -> dict[int, dict[str, bool]]:
    result = {index: {} for index in selected_indexes}
    if not package.has_part(STYLES_PART) or not selected_indexes:
        return result
    in_cell_xfs = False
    xf_index = -1
    selected_xf = False
    try:
        with package.open_part(STYLES_PART) as source_stream:
            for event, element in iterparse(
                source_stream,
                events=("start", "end"),
                forbid_dtd=True,
                forbid_entities=True,
                forbid_external=True,
            ):
                if event == "start":
                    if element.tag == f"{{{_MAIN_NS}}}cellXfs":
                        in_cell_xfs = True
                    elif in_cell_xfs and element.tag == f"{{{_MAIN_NS}}}xf":
                        xf_index += 1
                        selected_xf = xf_index in selected_indexes
                    continue
                if selected_xf and element.tag == f"{{{_MAIN_NS}}}alignment":
                    result[xf_index] = {
                        "wrap": _bool_attribute(element, "wrapText"),
                        "shrink_to_fit": _bool_attribute(element, "shrinkToFit"),
                    }
                elif in_cell_xfs and element.tag == f"{{{_MAIN_NS}}}xf":
                    selected_xf = False
                elif element.tag == f"{{{_MAIN_NS}}}cellXfs":
                    break
                element.clear()
    except DocumentSkillsError:
        raise
    except Exception as error:
        _unsafe(
            "Workbook styles could not be parsed safely.",
            part=STYLES_PART,
            reason=type(error).__name__,
        )
    return result


def _finalize_sheet_sample(
    scan: dict[str, Any],
    *,
    shared_values: dict[int, str],
    alignments: dict[int, dict[str, bool]],
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    if scan["state"] != "visible":
        findings.append({
            "kind": "hidden-sheet",
            "sheet": scan["sheet"],
            "state": scan["state"],
        })
    if scan["hidden_rows"] or scan["hidden_columns"]:
        findings.append({
            "kind": "hidden-data",
            "sheet": scan["sheet"],
            "hidden_rows": scan["hidden_rows"],
            "hidden_columns": scan["hidden_columns"],
        })
    if scan["wide_column_count"]:
        findings.append({
            "kind": "wide-columns",
            "sheet": scan["sheet"],
            "columns": scan["wide_columns"],
            "truncated_columns": max(0, scan["wide_column_count"] - 32),
        })

    truncation_cells: list[dict[str, Any]] = []
    truncation_count = 0
    for cell in scan["cells"]:
        value = cell["value"]
        if cell["shared_index"] is not None:
            value = shared_values.get(cell["shared_index"])
        if type(value) is not str or not value:
            continue
        alignment = alignments.get(cell["style_index"], {})
        width = cell["column_width"]
        if (
            len(value) > max(40, int(width * 2))
            and not alignment.get("wrap", False)
            and not alignment.get("shrink_to_fit", False)
        ):
            truncation_count += 1
            if len(truncation_cells) < 32:
                truncation_cells.append({
                    "ref": cell["ref"],
                    "characters": len(value),
                    "column_width": width,
                })
    if truncation_count:
        findings.append({
            "kind": "potential-text-truncation",
            "sheet": scan["sheet"],
            "cells": truncation_cells,
            "truncated_cells": max(0, truncation_count - 32),
        })
    return {
        "sheet": scan["sheet"],
        "state": scan["state"],
        "dimension": scan["dimension"],
        "total_cells": scan["observed_cells"],
        "total_cells_is_lower_bound": scan["cell_sampling_truncated"],
        "sampled_cells": len(scan["cells"]),
        "cell_sampling_truncated": scan["cell_sampling_truncated"],
        "hidden_rows": scan["hidden_rows"],
        "hidden_columns": scan["hidden_columns"],
        "wide_column_count": scan["wide_column_count"],
        "table_count": scan["table_count"],
        "chart_count": scan["chart_count"],
        "print_area": scan["print_area"],
        "print_titles": scan["print_titles"],
        "page_setup": scan["page_setup"],
        "header_footer_present": scan["header_footer_present"],
        "findings": findings,
    }


def _table_count(package: RenderPackageIndex, sheet_part: str | None) -> int:
    if sheet_part is None:
        return 0
    return len({
        relationship.resolved_target
        for relationship in package.relationships_for(sheet_part)
        if relationship.source_part == sheet_part
        and _relationship_kind(relationship.relationship_type) == "table"
        and relationship.resolved_target is not None
    })


def _chart_count(package: RenderPackageIndex, sheet_part: str | None) -> int:
    if sheet_part is None:
        return 0
    drawing_parts = {
        relationship.resolved_target
        for relationship in package.relationships_for(sheet_part)
        if relationship.source_part == sheet_part
        and _relationship_kind(relationship.relationship_type) == "drawing"
        and relationship.resolved_target is not None
    }
    return len({
        relationship.resolved_target
        for drawing_part in drawing_parts
        for relationship in package.relationships_for(drawing_part)
        if _relationship_kind(relationship.relationship_type) == "chart"
        and relationship.resolved_target is not None
    })


def _local_reference(value: str, sheet_name: str) -> str | None:
    prefix, separator, reference = value.rpartition("!")
    if not separator:
        return None
    normalized_sheet = prefix.strip("'").replace("''", "'")
    return reference.replace("$", "") if normalized_sheet == sheet_name else None


def _relationship_kind(relationship_type: str) -> str:
    return relationship_type.rsplit("/", 1)[-1]


def _integer_attribute(element: Any, name: str, default: int) -> int:
    return int(element.attrib.get(name, str(default)))


def _optional_integer(value: str | None) -> int | None:
    return None if value is None else int(value)


def _optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError("numeric XML attributes must be finite")
    return parsed


def _bool_attribute(element: Any, name: str) -> bool:
    return element.attrib.get(name, "") in _TRUE_VALUES


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)


def _sampling_warnings(
    *,
    finding_counts: Counter[str],
    truncated_sheets: int,
    truncated_findings: int,
) -> list[dict[str, Any]]:
    warnings = [{
        "code": "DS_XLSX_RENDER_SCOPE_LIMITED",
        "message": (
            "The PDF was reopened, but metadata sampling does not prove Excel/"
            "LibreOffice parity or per-object chart/table visibility."
        ),
        "details": {"sampling": "bounded-metadata-plus-pdf-reopen"},
    }]
    if finding_counts or truncated_sheets or truncated_findings:
        warnings.append({
            "code": "DS_XLSX_RENDER_RISK_FINDINGS",
            "message": "The bounded render sample found layout risks or omitted evidence.",
            "details": {
                "finding_counts": dict(sorted(finding_counts.items())),
                "truncated_sheets": truncated_sheets,
                "truncated_findings": truncated_findings,
            },
        })
    return warnings
