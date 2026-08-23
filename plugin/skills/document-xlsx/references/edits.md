# XLSX edit primitives

Every `xlsx.edit` request uses distinct `input` and `output` paths and a non-empty bounded
`arguments.edits` array. All edits form one transaction: a contract, safety, reopen, or
preservation failure prevents promotion.

## Primitive fields

| Type | Required fields | Notes |
| --- | --- | --- |
| `cell_value`, `cell_formula` | `sheet`, `ref`, `value` | `style` may be supplied in the same edit. |
| `cell_style`, `row_style`, `column_style` | `sheet`, `ref`, `style` | Row refs use `2:4`; column refs use `B:D`. |
| `row_insert`, `row_delete`, `column_insert`, `column_delete` | `sheet`, `ref` | Optional `count`; references are migrated package-wide or the request fails closed. |
| `row_height`, `column_width` | `sheet`, `ref`, `height`/`width` | Row/column ranges are accepted. |
| `row_hidden`, `column_hidden` | `sheet`, `ref`, `hidden` | `false` explicitly unhides. |
| `sheet_add` | new `sheet` | Optional zero-based `position`. |
| `sheet_delete` | `sheet` | Refuses the last sheet, related objects, or inbound references. |
| `sheet_copy` | source `sheet`, new `name` | Optional `position`; limited to sheets without related objects. |
| `sheet_reorder` | `sheet`, zero-based `position` | Local defined-name scopes are remapped. |
| `sheet_rename` | old `sheet`, new `value` | Explicit formula/object/name/hyperlink sheet references are migrated. |
| `cells_merge`, `cells_unmerge` | `sheet`, range `ref` | Merge refuses loss of non-anchor values. |
| `range_clear` | `sheet`, range `ref` | `clear` is `contents` (default), `styles`, or `all`. |
| `freeze_panes` | `sheet`, cell `ref` | `A1` clears frozen panes. |
| `auto_filter`, `print_area` | `sheet`, range `ref` | Use the corresponding `_clear` type to remove it. |
| `row_page_break`, `column_page_break` | `sheet`, `ref` | `enabled` defaults to `true`; `false` removes an existing manual break. |
| `defined_name_add`, `defined_name_update` | `sheet`, `name`, `ref` | `scope` is `workbook` (default) or `sheet`. |
| `defined_name_delete` | `sheet`, `name` | Uses the same optional `scope`. |
| `table_add` | `sheet`, `name`, `ref` | Optional built-in `table_style`; requires unique text headers and a non-overlapping range. |
| `table_resize` | `sheet`, `name`, `ref` | Keeps the top-left header; refuses removal of referenced structured columns. |
| `table_rename` | `sheet`, old `name`, new `value` | Migrates structured-reference formulas. |
| `table_style` | `sheet`, `name`, `table_style` | Accepts supported built-in Excel table styles. |
| `table_delete` | `sheet`, `name` | Refuses deletion while structured references remain. |
| `data_validation_add` | `sheet`, `validation` | The full validation object contains its target `ref`. |
| `data_validation_update` | `sheet`, selector `ref`, `validation` | Selector must match one standard rule exactly. |
| `data_validation_delete` | `sheet`, selector `ref` | Removes one exact standard rule. |
| `conditional_format_add` | `sheet`, `rule` | Assigns the next unique worksheet priority. |
| `conditional_format_update` | `sheet`, selector `ref`/`priority`, `rule` | Replaces one exact standard rule and preserves its priority. |
| `conditional_format_delete` | `sheet`, selector `ref`/`priority` | Removes one exact standard rule. |
| `chart_add` | `sheet`, `chart` | Adds a full native chart definition; `chart.sheet` must match `sheet`. |
| `chart_update` | `sheet`, existing `name`, `chart` | Replaces the named chart, including safe series/range and anchor changes. |
| `chart_delete` | `sheet`, existing `name` | Removes the chart and any drawing parts made empty by that deletion. |
| `sheet_view` | `sheet`, `view` | Replaces gridline, zoom, and selected-cell settings. |
| `page_setup` | `sheet`, `page_setup` | Replaces orientation, paper, margins, centering, and scale/fit settings. |
| `header_footer` | `sheet`, `header_footer` | Replaces odd/even/first header and footer fields. |
| `print_titles`, `print_titles_clear` | `sheet`, optional `print_titles` | Sets or clears repeated row/column titles. |
| `hyperlink_add`, `hyperlink_update`, `hyperlink_delete` | `sheet`, exact `ref`; add/update carry `hyperlink` | CRUD for inert internal locations only. |
| `comment_add`, `comment_update`, `comment_delete` | `sheet`, exact cell `ref`; add/update carry `comment` | CRUD for legacy cell notes. |
| `workbook_properties` | empty `sheet`, partial `properties` | Updates only declared core/extended properties. |

## Example

```json
{
  "schema_version": "1.0",
  "operation": "xlsx.edit",
  "input": "source.xlsx",
  "output": "edited.xlsx",
  "arguments": {
    "edits": [
      {"sheet": "Data", "type": "row_insert", "ref": "3", "count": 2},
      {"sheet": "Data", "type": "column_width", "ref": "B:C", "width": 18},
      {"sheet": "Data", "type": "freeze_panes", "ref": "B2"},
      {"sheet": "Data", "type": "auto_filter", "ref": "A1:C20"},
      {
        "sheet": "Data",
        "type": "defined_name_add",
        "name": "InputArea",
        "ref": "Data!$A$2:$C$20"
      }
    ],
    "expected_edits": 5
  }
}
```
