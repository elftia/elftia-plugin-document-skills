# XLSX worksheet metadata and annotations

Page and view settings are sheet-local. The legacy workbook-level `page_setup` placeholder is
not the native contract and remains fail-closed.

## Create fields

Each sheet may contain:

- `view`: `show_grid_lines`, `zoom_scale` (10–400), and `selected_cell`.
- `page_setup`: `orientation`, named `paper_size`, six `margins`, horizontal/vertical centering,
  and either `scale` or the `fit_to_width`/`fit_to_height` pair.
- `header_footer`: odd/even/first headers and footers plus `different_first`,
  `different_odd_even`, `scale_with_doc`, and `align_with_margins`.
- `print_area`: one bounded cell range.
- `print_titles`: optional `rows` and/or `columns` ranges.
- `hyperlinks`: relationship-free internal workbook locations with `ref`, `location`, optional
  `display`, and optional `tooltip`.
- `comments`: legacy Excel cell notes with exact cell `ref`, plain `text`, and `author`.

Workbook `metadata` supports `title`, `creator`, `subject`, `description`, `keywords`, `category`,
`last_modified_by`, timezone-qualified `created`/`modified` ISO-8601 timestamps, `company`, and
`manager`.

## Edit primitives

| Type | Selector/payload |
| --- | --- |
| `sheet_view` | `sheet`, full `view` |
| `page_setup` | `sheet`, full `page_setup` |
| `header_footer` | `sheet`, full `header_footer` |
| `print_titles` / `print_titles_clear` | `sheet`, optional full `print_titles` |
| `hyperlink_add` | `sheet`, full `hyperlink` |
| `hyperlink_update` | `sheet`, existing `ref`, full replacement `hyperlink` |
| `hyperlink_delete` | `sheet`, existing `ref` |
| `comment_add` | `sheet`, full `comment` |
| `comment_update` | `sheet`, existing `ref`, full replacement `comment` at that ref |
| `comment_delete` | `sheet`, existing `ref` |
| `workbook_properties` | empty `sheet`, non-empty partial `properties` object |

All edits run in one staged transaction and are reopened before atomic promotion. Internal
hyperlinks have no external relationship. URL/scheme/external-workbook targets return
`enhancement_required`; they are not silently rewritten. Cell notes use the standard comments
part plus legacy VML drawing, and deleting the final note cleans up only those declared parts.
