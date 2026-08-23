"""Transactional row/column mutation with package-wide reference maintenance."""

from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS
from .package import OpcPackage
from .structural_refs import (
    AxisMutation,
    has_external_workbook_reference,
    rewrite_formula,
    rewrite_reference,
    shift_coordinate,
)

_MAIN_NS = NS["main"]
_CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_UNSUPPORTED_RELATIONSHIP_SUFFIXES = {
    "comments",
    "ctrlProp",
    "oleObject",
    "pivotTable",
    "slicer",
    "slicerCache",
    "threadedComment",
    "vmlDrawing",
}


class StructuralEditContext:
    """Own mutable XML roots and serialize only declared changed parts."""

    def __init__(self, package: OpcPackage, workbook: dict[str, Any]) -> None:
        self.package = package
        self.workbook = workbook
        self.roots: dict[str, Element] = {
            "xl/workbook.xml": package.xml("xl/workbook.xml")
        }
        self.dirty: set[str] = set()
        self.added: set[str] = set()
        self.removed: set[str] = set()
        self.sheet_parts = {
            sheet["name"]: sheet["part"]
            for sheet in workbook["sheets"]
            if sheet.get("part")
        }
        self.sheet_names_by_part = {
            part: name for name, part in self.sheet_parts.items()
        }

    @property
    def workbook_root(self) -> Element:
        return self.roots["xl/workbook.xml"]

    def worksheet(self, part: str) -> Element:
        return self.root(part)

    def root(self, part: str) -> Element:
        if part not in self.roots:
            self.roots[part] = self.package.xml(part)
        return self.roots[part]

    def mark_dirty(self, part: str) -> None:
        self.dirty.add(part)

    def add_root(self, part: str, root: Element) -> None:
        if part in self.package.parts or part in self.roots:
            raise ValueError(f"Package part already exists: {part}")
        self.roots[part] = root
        self.added.add(part)

    def remove_part(self, part: str) -> None:
        if part in self.added:
            self.added.remove(part)
            self.roots.pop(part, None)
            return
        if part not in self.package.parts:
            raise ValueError(f"Package part does not exist: {part}")
        self.removed.add(part)
        self.dirty.discard(part)

    def apply_axis_mutation(
        self,
        *,
        sheet_name: str,
        axis: str,
        index: int,
        count: int,
        delete: bool,
    ) -> AxisMutation:
        mutation = AxisMutation(sheet_name, axis, index, count, delete)
        target_part = self.sheet_parts[sheet_name]
        self._preflight(mutation, target_part)
        target_root = self.worksheet(target_part)
        self._shift_cells(target_root, mutation)
        self._rewrite_all_formulas(mutation)
        self._rewrite_worksheet_metadata(target_root, mutation)
        self._rewrite_metadata_formulas(mutation)
        self._rewrite_hyperlink_locations(mutation)
        self._rewrite_defined_names(mutation)
        self._rewrite_tables(target_part, mutation)
        self._rewrite_charts(mutation)
        self._rewrite_drawing_anchors(target_part, mutation)
        self._invalidate_calc_chain()
        self._force_full_calculation()
        self.mark_dirty(target_part)
        return mutation

    def changed_parts(self) -> dict[str, bytes]:
        return {
            part: tostring(
                self.roots[part],
                encoding="UTF-8",
                xml_declaration=True,
            )
            for part in sorted(self.dirty - self.added - self.removed)
        }

    def added_parts(self) -> dict[str, bytes]:
        return {
            part: tostring(
                self.roots[part],
                encoding="UTF-8",
                xml_declaration=True,
            )
            for part in sorted(self.added)
        }

    def _preflight(self, mutation: AxisMutation, target_part: str) -> None:
        for part, sheet_name in self.sheet_names_by_part.items():
            root = self.worksheet(part)
            for formula in root.findall(f".//{{{_MAIN_NS}}}f"):
                formula_type = formula.attrib.get("t", "normal")
                if formula_type not in {"", "normal"}:
                    _enhancement(
                        "Structural edits do not yet rewrite shared, array, or data-table formulas.",
                        capability="xlsx.special-formula-structural-edit",
                        formula_type=formula_type,
                        sheet=sheet_name,
                    )
                if has_external_workbook_reference(formula.text or ""):
                    _enhancement(
                        "Structural edits do not rewrite external-workbook formulas.",
                        capability="xlsx.external-reference-structural-edit",
                        sheet=sheet_name,
                    )
        if any(name.startswith("xl/pivotCache/") for name in self.package.parts):
            _enhancement(
                "Structural edits are blocked when native pivot caches are present.",
                capability="xlsx.pivot-structural-edit",
            )
        for relationship in self.package.sheet_rels(target_part):
            suffix = relationship.relationship_type.rsplit("/", 1)[-1]
            if suffix in _UNSUPPORTED_RELATIONSHIP_SUFFIXES:
                _enhancement(
                    "Structural edit cannot safely migrate a worksheet relationship.",
                    capability="xlsx.relationship-structural-edit",
                    relationship_type=suffix,
                )

    def _shift_cells(self, root: Element, mutation: AxisMutation) -> None:
        sheet_data = root.find(f"{{{_MAIN_NS}}}sheetData")
        if sheet_data is None:
            return
        if mutation.axis == "row":
            for row in list(sheet_data.findall(f"{{{_MAIN_NS}}}row")):
                row_number = int(row.attrib.get("r", "0"))
                shifted = _shift_index(row_number, mutation)
                if shifted is None:
                    if not mutation.delete:
                        _enhancement(
                            "Row insertion would move stored cells outside the XLSX range.",
                            capability="xlsx.structural-range-overflow",
                        )
                    sheet_data.remove(row)
                    continue
                row.attrib["r"] = str(shifted)
                for cell in row.findall(f"{{{_MAIN_NS}}}c"):
                    column, _row = _parse_cell_ref(cell.attrib.get("r", ""))
                    cell.attrib["r"] = f"{_column_name(column)}{shifted}"
        else:
            for row in sheet_data.findall(f"{{{_MAIN_NS}}}row"):
                for cell in list(row.findall(f"{{{_MAIN_NS}}}c")):
                    column, row_number = _parse_cell_ref(cell.attrib.get("r", ""))
                    shifted = _shift_index(column, mutation)
                    if shifted is None:
                        if not mutation.delete:
                            _enhancement(
                                "Column insertion would move stored cells outside the XLSX range.",
                                capability="xlsx.structural-range-overflow",
                            )
                        row.remove(cell)
                        continue
                    cell.attrib["r"] = f"{_column_name(shifted)}{row_number}"
            self._shift_column_dimensions(root, mutation)
        _sort_rows_and_cells(sheet_data)
        _update_dimension(root)

    def _rewrite_all_formulas(self, mutation: AxisMutation) -> None:
        for part, sheet_name in self.sheet_names_by_part.items():
            root = self.worksheet(part)
            changed = False
            for formula in root.findall(f".//{{{_MAIN_NS}}}f"):
                original = formula.text or ""
                rewritten = rewrite_formula(
                    original,
                    current_sheet=sheet_name,
                    mutation=mutation,
                )
                if "#REF!" in rewritten:
                    _enhancement(
                        "Structural edit would create a #REF! formula.",
                        capability="xlsx.formula-reference-migration",
                        sheet=sheet_name,
                        formula=original,
                    )
                if rewritten != original:
                    formula.text = rewritten
                    changed = True
            if changed:
                self.mark_dirty(part)

    def _rewrite_worksheet_metadata(self, root: Element, mutation: AxisMutation) -> None:
        removable = [
            (f".//{{{_MAIN_NS}}}mergeCells", f"{{{_MAIN_NS}}}mergeCell", "ref"),
            (f".//{{{_MAIN_NS}}}dataValidations", f"{{{_MAIN_NS}}}dataValidation", "sqref"),
            (".", f"{{{_MAIN_NS}}}conditionalFormatting", "sqref"),
            (f".//{{{_MAIN_NS}}}hyperlinks", f"{{{_MAIN_NS}}}hyperlink", "ref"),
        ]
        for parent_path, child_tag, attribute in removable:
            parents = [root] if parent_path == "." else root.findall(parent_path)
            for parent in parents:
                for child in list(parent.findall(child_tag)):
                    shifted = _rewrite_sqref(child.attrib.get(attribute, ""), mutation)
                    if shifted:
                        child.attrib[attribute] = shifted
                    else:
                        parent.remove(child)
                if "count" in parent.attrib:
                    parent.attrib["count"] = str(len(parent))
        auto_filter = root.find(f"{{{_MAIN_NS}}}autoFilter")
        if auto_filter is not None and "ref" in auto_filter.attrib:
            shifted = _rewrite_sqref(auto_filter.attrib["ref"], mutation)
            if shifted:
                auto_filter.attrib["ref"] = shifted
            else:
                root.remove(auto_filter)
        for selection in root.findall(f".//{{{_MAIN_NS}}}selection"):
            for attribute in ("activeCell", "sqref"):
                if attribute in selection.attrib:
                    shifted = _rewrite_sqref(selection.attrib[attribute], mutation)
                    if shifted:
                        selection.attrib[attribute] = shifted
        for pane in root.findall(f".//{{{_MAIN_NS}}}pane"):
            top_left = pane.attrib.get("topLeftCell")
            if not top_left:
                continue
            if pane.attrib.get("state", "split") not in {"frozen", "frozenSplit"}:
                _enhancement(
                    "Structural edit encountered a non-frozen worksheet split pane.",
                    capability="xlsx.split-pane-structural-edit",
                )
            shifted = rewrite_reference(
                top_left,
                current_sheet=mutation.sheet,
                mutation=mutation,
            )
            if shifted == "#REF!":
                _enhancement(
                    "Structural edit would remove the frozen-pane boundary.",
                    capability="xlsx.freeze-pane-structural-edit",
                )
            column, row = _parse_cell_ref(shifted)
            pane.attrib["topLeftCell"] = shifted
            if "xSplit" in pane.attrib:
                pane.attrib["xSplit"] = str(column - 1)
            if "ySplit" in pane.attrib:
                pane.attrib["ySplit"] = str(row - 1)
        self._rewrite_breaks(root, mutation)
        _update_dimension(root)

    def _rewrite_metadata_formulas(self, mutation: AxisMutation) -> None:
        for part, sheet_name in self.sheet_names_by_part.items():
            root = self.worksheet(part)
            changed = False
            for formula_tag, capability in (
                ("formula1", "xlsx.data-validation-structural-edit"),
                ("formula2", "xlsx.data-validation-structural-edit"),
                ("formula", "xlsx.conditional-format-structural-edit"),
            ):
                for formula in root.findall(f".//{{{_MAIN_NS}}}{formula_tag}"):
                    original = formula.text or ""
                    if has_external_workbook_reference(original):
                        _enhancement(
                            "Structural edits do not rewrite external-workbook metadata formulas.",
                            capability="xlsx.external-reference-structural-edit",
                            sheet=sheet_name,
                        )
                    rewritten = rewrite_formula(
                        original,
                        current_sheet=sheet_name,
                        mutation=mutation,
                    )
                    if "#REF!" in rewritten:
                        _enhancement(
                            "Structural edit would invalidate a worksheet metadata formula.",
                            capability=capability,
                            sheet=sheet_name,
                        )
                    if rewritten != original:
                        formula.text = rewritten
                        changed = True
            if changed:
                self.mark_dirty(part)

    def _rewrite_defined_names(self, mutation: AxisMutation) -> None:
        sheets = self.workbook["sheets"]
        for defined_name in self.workbook_root.findall(
            f".//{{{_MAIN_NS}}}definedName"
        ):
            local_sheet = None
            if "localSheetId" in defined_name.attrib:
                local_index = int(defined_name.attrib["localSheetId"])
                if 0 <= local_index < len(sheets):
                    local_sheet = sheets[local_index]["name"]
            original = defined_name.text or ""
            if has_external_workbook_reference(original):
                _enhancement(
                    "Structural edits do not rewrite external-workbook defined names.",
                    capability="xlsx.external-reference-structural-edit",
                    name=defined_name.attrib.get("name", ""),
                )
            rewritten = rewrite_reference(
                original,
                current_sheet=local_sheet,
                mutation=mutation,
            )
            if "#REF!" in rewritten:
                _enhancement(
                    "Structural edit would invalidate a defined name or print area.",
                    capability="xlsx.defined-name-structural-edit",
                    name=defined_name.attrib.get("name", ""),
                )
            defined_name.text = rewritten
        self.mark_dirty("xl/workbook.xml")

    def _rewrite_hyperlink_locations(self, mutation: AxisMutation) -> None:
        for part, sheet_name in self.sheet_names_by_part.items():
            root = self.worksheet(part)
            changed = False
            for hyperlink in root.findall(f".//{{{_MAIN_NS}}}hyperlink"):
                original = hyperlink.attrib.get("location")
                if not original:
                    continue
                if has_external_workbook_reference(original):
                    _enhancement(
                        "Structural edits do not rewrite external-workbook hyperlinks.",
                        capability="xlsx.external-reference-structural-edit",
                        sheet=sheet_name,
                    )
                rewritten = rewrite_reference(
                    original,
                    current_sheet=sheet_name,
                    mutation=mutation,
                )
                if "#REF!" in rewritten:
                    _enhancement(
                        "Structural edit would invalidate an internal hyperlink.",
                        capability="xlsx.hyperlink-structural-edit",
                        sheet=sheet_name,
                        location=original,
                    )
                if rewritten != original:
                    hyperlink.attrib["location"] = rewritten
                    changed = True
            if changed:
                self.mark_dirty(part)

    def _rewrite_tables(self, target_part: str, mutation: AxisMutation) -> None:
        for relationship in self.package.sheet_rels(target_part):
            if relationship.relationship_type.rsplit("/", 1)[-1] != "table":
                continue
            table_part = relationship.resolved_target
            if not table_part:
                continue
            root = self.root(table_part)
            if mutation.axis == "row" and mutation.delete:
                _assert_table_row_delete_safe(root, mutation)
            for element in [root, *root.findall(f".//{{{_MAIN_NS}}}autoFilter")]:
                if "ref" not in element.attrib:
                    continue
                shifted = rewrite_reference(
                    element.attrib["ref"],
                    current_sheet=mutation.sheet,
                    mutation=mutation,
                )
                if "#REF!" in shifted:
                    _enhancement(
                        "Structural edit would remove an entire native table.",
                        capability="xlsx.table-structural-edit",
                        table=root.attrib.get("name", ""),
                    )
                if (
                    mutation.axis == "column"
                    and _reference_width(element.attrib["ref"])
                    != _reference_width(shifted)
                ):
                    _enhancement(
                        "Structural column edit would require native table-column mutation.",
                        capability="xlsx.table-column-structural-edit",
                        table=root.attrib.get("name", ""),
                    )
                element.attrib["ref"] = shifted
            for formula_tag in ("calculatedColumnFormula", "totalsRowFormula"):
                for formula in root.findall(f".//{{{_MAIN_NS}}}{formula_tag}"):
                    original = formula.text or ""
                    if has_external_workbook_reference(original):
                        _enhancement(
                            "Structural edits do not rewrite external-workbook table formulas.",
                            capability="xlsx.external-reference-structural-edit",
                            table=root.attrib.get("name", ""),
                        )
                    rewritten = rewrite_formula(
                        original,
                        current_sheet=mutation.sheet,
                        mutation=mutation,
                    )
                    if "#REF!" in rewritten:
                        _enhancement(
                            "Structural edit would invalidate a table formula.",
                            capability="xlsx.table-formula-structural-edit",
                            table=root.attrib.get("name", ""),
                        )
                    formula.text = rewritten
            self.mark_dirty(table_part)

    def _rewrite_charts(self, mutation: AxisMutation) -> None:
        for part in sorted(self.package.parts):
            if not part.startswith("xl/charts/") or not part.endswith(".xml"):
                continue
            root = self.root(part)
            changed = False
            for formula in root.findall(f".//{{{_CHART_NS}}}f"):
                original = formula.text or ""
                if has_external_workbook_reference(original):
                    _enhancement(
                        "Structural edits do not rewrite external-workbook chart formulas.",
                        capability="xlsx.external-reference-structural-edit",
                        part=part,
                    )
                rewritten = rewrite_reference(
                    original,
                    current_sheet=None,
                    mutation=mutation,
                )
                if "#REF!" in rewritten:
                    _enhancement(
                        "Structural edit would invalidate a chart series.",
                        capability="xlsx.chart-structural-edit",
                        part=part,
                    )
                if rewritten != original:
                    formula.text = rewritten
                    changed = True
            if changed:
                self.mark_dirty(part)

    def _rewrite_drawing_anchors(self, target_part: str, mutation: AxisMutation) -> None:
        for relationship in self.package.sheet_rels(target_part):
            if relationship.relationship_type.rsplit("/", 1)[-1] != "drawing":
                continue
            drawing_part = relationship.resolved_target
            if not drawing_part:
                continue
            root = self.root(drawing_part)
            for marker_name in ("from", "to"):
                for marker in root.findall(f".//{{{_DRAWING_NS}}}{marker_name}"):
                    column = marker.find(f"{{{_DRAWING_NS}}}col")
                    row = marker.find(f"{{{_DRAWING_NS}}}row")
                    if column is None or row is None:
                        continue
                    coordinate = shift_coordinate(
                        int(column.text or "0") + 1,
                        int(row.text or "0") + 1,
                        mutation,
                    )
                    if coordinate is None:
                        _enhancement(
                            "Structural delete intersects a drawing anchor.",
                            capability="xlsx.drawing-anchor-structural-edit",
                            part=drawing_part,
                        )
                    column.text = str(coordinate[0] - 1)
                    row.text = str(coordinate[1] - 1)
            self.mark_dirty(drawing_part)

    def _rewrite_breaks(self, root: Element, mutation: AxisMutation) -> None:
        tag = "rowBreaks" if mutation.axis == "row" else "colBreaks"
        container = root.find(f"{{{_MAIN_NS}}}{tag}")
        if container is None:
            return
        for item in list(container.findall(f"{{{_MAIN_NS}}}brk")):
            shifted = _shift_index(int(item.attrib.get("id", "0")), mutation)
            if shifted is None:
                if not mutation.delete:
                    _enhancement(
                        "Insertion would move a manual page break outside the XLSX range.",
                        capability="xlsx.structural-range-overflow",
                    )
                container.remove(item)
            else:
                item.attrib["id"] = str(shifted)
        container.attrib["count"] = str(len(container))
        container.attrib["manualBreakCount"] = str(len(container))

    def _shift_column_dimensions(self, root: Element, mutation: AxisMutation) -> None:
        container = root.find(f"{{{_MAIN_NS}}}cols")
        if container is None:
            return
        for column in list(container.findall(f"{{{_MAIN_NS}}}col")):
            reference = (
                f"{_column_name(int(column.attrib.get('min', '1')))}:"
                f"{_column_name(int(column.attrib.get('max', column.attrib.get('min', '1'))))}"
            )
            shifted = rewrite_reference(
                reference,
                current_sheet=mutation.sheet,
                mutation=mutation,
            )
            if shifted == "#REF!":
                if not mutation.delete:
                    _enhancement(
                        "Insertion would move a column definition outside the XLSX range.",
                        capability="xlsx.structural-range-overflow",
                    )
                container.remove(column)
                continue
            first_text, last_text = shifted.split(":", 1)
            column.attrib["min"] = str(_column_number(first_text.replace("$", "")))
            column.attrib["max"] = str(_column_number(last_text.replace("$", "")))

    def _invalidate_calc_chain(self) -> None:
        part = "xl/calcChain.xml"
        if part in self.package.parts:
            root = self.root(part)
            for child in list(root):
                root.remove(child)
            self.mark_dirty(part)

    def _force_full_calculation(self) -> None:
        calc_pr = self.workbook_root.find(f"{{{_MAIN_NS}}}calcPr")
        if calc_pr is None:
            calc_pr = Element(f"{{{_MAIN_NS}}}calcPr")
            self.workbook_root.append(calc_pr)
        calc_pr.attrib.update(
            {"calcId": "0", "fullCalcOnLoad": "1", "forceFullCalc": "1"}
        )
        self.mark_dirty("xl/workbook.xml")


def _rewrite_sqref(value: str, mutation: AxisMutation) -> str:
    shifted: list[str] = []
    for reference in value.split():
        rewritten = rewrite_reference(
            reference,
            current_sheet=mutation.sheet,
            mutation=mutation,
        )
        if rewritten == "#REF!":
            if not mutation.delete:
                _enhancement(
                    "Insertion would move worksheet metadata outside the XLSX range.",
                    capability="xlsx.structural-range-overflow",
                )
            continue
        shifted.append(rewritten)
    return " ".join(shifted)


def _shift_index(value: int, mutation: AxisMutation) -> int | None:
    coordinate = (
        shift_coordinate(1, value, mutation)
        if mutation.axis == "row"
        else shift_coordinate(value, 1, mutation)
    )
    if coordinate is None:
        return None
    return coordinate[1] if mutation.axis == "row" else coordinate[0]


def _parse_cell_ref(ref: str) -> tuple[int, int]:
    letters = ""
    digits = ""
    for char in ref.replace("$", ""):
        if char.isalpha() and not digits:
            letters += char
        elif char.isdigit():
            digits += char
        else:
            break
    if not letters or not digits:
        _enhancement(
            "Structural edit encountered an unsupported cell reference.",
            capability="xlsx.structural-reference",
            ref=ref,
        )
    return _column_number(letters), int(digits)


def _sort_rows_and_cells(sheet_data: Element) -> None:
    rows = list(sheet_data.findall(f"{{{_MAIN_NS}}}row"))
    for row in rows:
        cells = list(row.findall(f"{{{_MAIN_NS}}}c"))
        cells.sort(key=lambda cell: _parse_cell_ref(cell.attrib.get("r", ""))[0])
        for cell in list(row):
            if cell.tag == f"{{{_MAIN_NS}}}c":
                row.remove(cell)
        row.extend(cells)
    rows.sort(key=lambda row: int(row.attrib.get("r", "0")))
    for row in list(sheet_data):
        if row.tag == f"{{{_MAIN_NS}}}row":
            sheet_data.remove(row)
    sheet_data.extend(rows)


def _update_dimension(root: Element) -> None:
    sheet_data = root.find(f"{{{_MAIN_NS}}}sheetData")
    if sheet_data is None:
        return
    coordinates = [
        _parse_cell_ref(cell.attrib.get("r", ""))
        for cell in sheet_data.findall(f".//{{{_MAIN_NS}}}c")
    ]
    reference = "A1"
    if coordinates:
        min_column = min(item[0] for item in coordinates)
        max_column = max(item[0] for item in coordinates)
        min_row = min(item[1] for item in coordinates)
        max_row = max(item[1] for item in coordinates)
        first = f"{_column_name(min_column)}{min_row}"
        last = f"{_column_name(max_column)}{max_row}"
        reference = first if first == last else f"{first}:{last}"
    dimension = root.find(f"{{{_MAIN_NS}}}dimension")
    if dimension is None:
        dimension = Element(f"{{{_MAIN_NS}}}dimension")
        root.insert(0, dimension)
    dimension.attrib["ref"] = reference


def _column_number(value: str) -> int:
    result = 0
    for char in value.upper():
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def _column_name(value: int) -> str:
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _reference_width(ref: str) -> int:
    first, separator, last = ref.partition(":")
    first_column, _ = _parse_cell_ref(first)
    last_column, _ = _parse_cell_ref(last if separator else first)
    return last_column - first_column + 1


def _assert_table_row_delete_safe(root: Element, mutation: AxisMutation) -> None:
    ref = root.attrib.get("ref", "")
    first, separator, last = ref.partition(":")
    _, first_row = _parse_cell_ref(first)
    _, last_row = _parse_cell_ref(last if separator else first)
    deleted_last = mutation.index + mutation.count - 1
    deletes_header = mutation.index <= first_row <= deleted_last
    has_totals = root.attrib.get("totalsRowCount", "0") != "0"
    deletes_totals = has_totals and mutation.index <= last_row <= deleted_last
    if deletes_header or deletes_totals:
        _enhancement(
            "Structural row delete would remove a native table header or totals row.",
            capability="xlsx.table-boundary-row-delete",
            table=root.attrib.get("name", ""),
        )


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details=details,
    )
