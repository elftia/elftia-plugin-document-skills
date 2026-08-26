"""Immutable-input planning and semantic projection for DOCX table edits."""

from dataclasses import dataclass, field
from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn
from .mapping import Story, map_paragraph
from .projection import table_selector_sha256
from .table_model import cell_text


@dataclass(frozen=True)
class TableEditPlan:
    kind: str
    table: Element | None = None
    parent: Element | None = None
    anchor: Element | None = None
    position: str | None = None
    cell: Element | None = None
    row: Element | None = None
    cells: tuple[Element, ...] = ()
    rows: tuple[tuple[Element, ...], ...] = ()
    value: Any = None


@dataclass
class TableMutationState:
    body: Story
    tables: list[Element]
    parents: dict[int, Element]
    touched_cells: set[tuple[int, int, int]] = field(default_factory=set)
    deleted_rows: set[tuple[int, int]] = field(default_factory=set)
    row_insertions: set[tuple[int, int, str]] = field(default_factory=set)
    mutated_tables: set[int] = field(default_factory=set)
    exclusive_tables: set[int] = field(default_factory=set)

    @classmethod
    def open(cls, body: Story) -> "TableMutationState":
        return cls(
            body,
            list(body.root.iter(qn("w", "tbl"))),
            {id(child): parent for parent in body.root.iter() for child in parent},
        )

    def plan_insert(
        self,
        edit: dict[str, Any],
        *,
        anchor: Element,
        parent: Element,
    ) -> TableEditPlan:
        return TableEditPlan(
            kind="table_insert",
            parent=parent,
            anchor=anchor,
            position=edit["position"],
            value=edit["table"],
        )

    def plan(self, edit: dict[str, Any]) -> TableEditPlan:
        table, table_index = self._select_table(edit["target"])
        table_id = id(table)
        kind = edit["type"]
        if kind in {"table_cells_merge", "table_cell_split"}:
            if table_id in self.mutated_tables:
                _conflict(table_index, "exclusive-structure-edit")
            self.exclusive_tables.add(table_id)
        elif table_id in self.exclusive_tables:
            _conflict(table_index, "exclusive-structure-edit")
        self.mutated_tables.add(table_id)

        rows = table.findall(qn("w", "tr"))
        if kind == "table_cell_update":
            selector = edit["cell"]
            row, cell = _select_cell(rows, selector, table_index)
            identity = (table_id, selector["row_index"], selector["cell_index"])
            if identity in self.touched_cells or (table_id, selector["row_index"]) in self.deleted_rows:
                _conflict(table_index, "cell-target")
            self.touched_cells.add(identity)
            _require_editable_cell(cell, table_index)
            return TableEditPlan(kind=kind, table=table, cell=cell, value=edit["text"])

        if kind == "table_row_insert":
            selector = edit["anchor"]
            row = _select_row(rows, selector, table_index)
            insertion = (table_id, selector["row_index"], edit["position"])
            if insertion in self.row_insertions:
                _conflict(table_index, "row-insertion")
            expected_width = _table_grid_width(table)
            if len(edit["cells"]) != expected_width:
                _precondition_failed(
                    table_index,
                    "inserted-row-width",
                    expected_cells=expected_width,
                    actual_cells=len(edit["cells"]),
                )
            self.row_insertions.add(insertion)
            return TableEditPlan(
                kind=kind,
                table=table,
                parent=table,
                anchor=row,
                position=edit["position"],
                value=edit["cells"],
            )

        if kind == "table_row_delete":
            selector = edit["row"]
            row = _select_row(rows, selector, table_index)
            identity = (table_id, selector["row_index"])
            if (
                len(rows) <= 1
                or identity in self.deleted_rows
                or any(item[:2] == identity for item in self.touched_cells)
            ):
                _conflict(table_index, "row-deletion")
            self.deleted_rows.add(identity)
            return TableEditPlan(kind=kind, table=table, parent=table, row=row)

        if kind == "table_cells_merge":
            return _plan_merge(table, table_index, edit)
        if kind == "table_cell_split":
            selector = edit["cell"]
            row, cell = _select_cell(rows, selector, table_index)
            properties = cell.find(qn("w", "tcPr"))
            span = properties.find(qn("w", "gridSpan")) if properties is not None else None
            vertical = properties.find(qn("w", "vMerge")) if properties is not None else None
            raw_span = span.attrib.get(qn("w", "val"), "") if span is not None else ""
            if vertical is not None or not raw_span.isdigit() or int(raw_span) < 2:
                raise DocumentSkillsError(
                    ErrorCode.ENHANCEMENT_REQUIRED,
                    "Table cell split currently requires one horizontal gridSpan cell.",
                    status="enhancement_required",
                    details={"table_index": table_index},
                )
            if len(edit["texts"]) != int(raw_span):
                _precondition_failed(
                    table_index,
                    "split-width",
                    expected_cells=int(raw_span),
                    actual_cells=len(edit["texts"]),
                )
            _require_editable_cell(cell, table_index)
            return TableEditPlan(
                kind=kind,
                table=table,
                parent=row,
                cell=cell,
                value=edit["texts"],
            )
        raise AssertionError(f"Unexpected table edit type: {kind}")

    def _select_table(self, target: dict[str, Any]) -> tuple[Element, int]:
        index = target["table_index"]
        if index >= len(self.tables):
            _precondition_failed(index, "table-index")
        table = self.tables[index]
        body = self.body.root.find(qn("w", "body"))
        if self.parents.get(id(table)) is not body:
            _precondition_failed(index, "not-a-top-level-body-table")
        actual = table_selector_sha256(table)
        if actual != target["expected_table_sha256"]:
            _precondition_failed(
                index,
                "expected-table-sha256",
                expected_sha256=target["expected_table_sha256"],
                actual_sha256=actual,
            )
        return table, index


def _plan_merge(table: Element, table_index: int, edit: dict[str, Any]) -> TableEditPlan:
    selection = edit["range"]
    rows = table.findall(qn("w", "tr"))
    if selection["end_row"] >= len(rows):
        _precondition_failed(table_index, "merge-row-range")
    selected: list[tuple[Element, ...]] = []
    for row_offset, row_index in enumerate(
        range(selection["start_row"], selection["end_row"] + 1)
    ):
        cells = row_cells = rows[row_index].findall(qn("w", "tc"))
        if selection["end_column"] >= len(row_cells):
            _precondition_failed(table_index, "merge-column-range")
        cells = row_cells[selection["start_column"] : selection["end_column"] + 1]
        actual = [cell_text(cell) for cell in cells]
        if actual != selection["expected_texts"][row_offset]:
            _precondition_failed(
                table_index,
                "merge-expected-texts",
                expected_texts=selection["expected_texts"],
            )
        for cell in cells:
            properties = cell.find(qn("w", "tcPr"))
            if properties is not None and (
                properties.find(qn("w", "gridSpan")) is not None
                or properties.find(qn("w", "vMerge")) is not None
            ):
                raise DocumentSkillsError(
                    ErrorCode.ENHANCEMENT_REQUIRED,
                    "Table merge range must contain only currently unmerged cells.",
                    status="enhancement_required",
                    details={"table_index": table_index},
                )
            _require_editable_cell(cell, table_index)
        selected.append(tuple(cells))
    return TableEditPlan(
        kind="table_cells_merge",
        table=table,
        rows=tuple(selected),
        value={"selection": selection, "text": edit["text"]},
    )


def _select_cell(
    rows: list[Element], selector: dict[str, Any], table_index: int
) -> tuple[Element, Element]:
    row_index = selector["row_index"]
    if row_index >= len(rows):
        _precondition_failed(table_index, "cell-row-index")
    cells = rows[row_index].findall(qn("w", "tc"))
    cell_index = selector["cell_index"]
    if cell_index >= len(cells):
        _precondition_failed(table_index, "cell-index")
    cell = cells[cell_index]
    actual = cell_text(cell)
    if actual != selector["expected_text"]:
        _precondition_failed(
            table_index,
            "cell-expected-text",
            expected_text=selector["expected_text"],
            actual_text=actual,
        )
    return rows[row_index], cell


def _select_row(
    rows: list[Element], selector: dict[str, Any], table_index: int
) -> Element:
    index = selector["row_index"]
    if index >= len(rows):
        _precondition_failed(table_index, "row-index")
    actual = [cell_text(cell) for cell in rows[index].findall(qn("w", "tc"))]
    if actual != selector["expected_cells"]:
        _precondition_failed(
            table_index,
            "row-expected-cells",
            expected_cells=selector["expected_cells"],
            actual_cells=actual,
        )
    return rows[index]


def _require_editable_cell(cell: Element, table_index: int) -> None:
    paragraphs = cell.findall(qn("w", "p"))
    if cell.find(qn("w", "tbl")) is not None or len(paragraphs) != 1:
        _enhancement(table_index, "complex-cell")
    mapped = map_paragraph(paragraphs[0])
    if mapped.protected_text or mapped.hyperlink_ids:
        _enhancement(table_index, "protected-cell")


def _table_grid_width(table: Element) -> int:
    grid = table.find(qn("w", "tblGrid"))
    width = len(grid.findall(qn("w", "gridCol"))) if grid is not None else 0
    if width <= 0:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Table row insertion requires a declared table grid.",
            status="enhancement_required",
        )
    return width


def _precondition_failed(table_index: int, reason: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "DOCX table selector precondition did not match the immutable input.",
        details={"table_index": table_index, "reason": reason, **details},
    )


def _enhancement(table_index: int, reason: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        "Table edit targets a complex cell that Core cannot safely rewrite.",
        status="enhancement_required",
        details={"table_index": table_index, "reason": reason},
    )


def _conflict(table_index: int, reason: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        "DOCX edit transaction contains conflicting table edits.",
        status="invalid_request",
        details={"table_index": table_index, "reason": reason},
    )
