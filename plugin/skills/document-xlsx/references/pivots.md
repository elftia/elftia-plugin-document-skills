# Native pivot creation

`xlsx.pivot.create` adds one native SpreadsheetML pivot table and saved cache to an existing
`.xlsx` or inert `.xlsm` workbook. It always writes a distinct output and creates a new target
worksheet. The Core never substitutes an ordinary summary table for this operation.

```json
{
  "schema_version": "1.0",
  "operation": "xlsx.pivot.create",
  "input": "sales.xlsx",
  "output": "sales-with-pivot.xlsx",
  "arguments": {
    "source": {"sheet": "Data", "range": "A1:D500"},
    "rows": [{"column": "Region", "sort": "asc"}],
    "columns": [{"column": "Category", "sort": "asc"}],
    "values": [
      {"column": "Revenue", "function": "sum", "as": "Total Revenue"}
    ],
    "filters": [{"column": "Segment", "value": "Retail"}],
    "target": {
      "sheet": "Sales Pivot",
      "start_cell": "A1",
      "name": "SalesPivot",
      "style": "PivotStyleMedium9"
    },
    "formula_policy": "reject",
    "numeric_policy": "strict",
    "recalculation": "skip"
  }
}
```

Current bounded shape:

- `rows`: exactly one source header plus `sort: asc|desc`;
- `columns`: zero or one distinct source header;
- `filters`: zero or one distinct page field; `value` may be string, number, boolean, or null
  (`null` means all items);
- `values`: exactly one distinct source header using `sum`, `average`, `min`, `max`, or nonblank
  `count`;
- `target.sheet`: must not already exist; `target.style` is a built-in PivotStyle;
- `formula_policy`: `reject` or explicit `cached`; `numeric_policy`: `strict` or
  `coerce-text`; `recalculation` is currently `skip`.

The output contains a workbook pivot-cache registration, pivot cache definition, saved cache
records, pivot table definition, worksheet pivot reference, internal relationships, and content
types. Validation reopens and follows the entire relationship chain, checks field/source/value
semantics and record counts, and proves untargeted parts remain byte-identical. The visible cells
are stored results for immediate display; the native pivot/cache definitions remain the source
of pivot identity and refresh metadata.

For `.xlsm`, input and output must both use `.xlsm` and `keep_vba: true` is mandatory. The Core
copies VBA bytes and relationships without parsing or execution. A package mutation explicitly
reports a preserved macro signature as invalidated.

Existing-pivot update/delete and any structural edit that would move or invalidate a pivot
remain unavailable and fail closed as `pivot_structural_edit`.
