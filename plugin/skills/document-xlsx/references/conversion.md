# XLSX and tabular conversion

`xlsx.convert` converts among `xlsx`, `csv`, `tsv`, and `json`, and explicitly converts legacy
`.xls` input to `.xlsx` through LibreOffice. It always requires distinct
`input` and `output` paths whose extensions match `source_format` and `target_format`.

```json
{
  "schema_version": "1.0",
  "operation": "xlsx.convert",
  "input": "source.csv",
  "output": "converted.xlsx",
  "arguments": {
    "source_format": "csv",
    "target_format": "xlsx",
    "source": {"encoding": "utf-8", "delimiter": ",", "quote": "\"", "bom": "auto"},
    "target": {},
    "values": {
      "infer_types": true,
      "null_token": "\\N",
      "true_token": "TRUE",
      "false_token": "FALSE",
      "decimal_separator": ".",
      "leading_zero_policy": "preserve-text",
      "large_integer_policy": "preserve-text",
      "timezone_policy": "preserve-text",
      "formula_policy": "preserve-text",
      "csv_injection_policy": "escape"
    },
    "limits": {
      "max_input_bytes": 67108864,
      "max_output_bytes": 67108864,
      "max_rows_per_sheet": 100000,
      "max_columns": 16384,
      "max_cells": 1000000,
      "max_cell_bytes": 1048576
    }
  }
}
```

`source.encoding` and `target.encoding` accept `utf-8`, `utf-16-le`, `utf-16-be`,
`windows-1252`, or `iso-8859-1`. Source BOM policy is `auto`, `required`, or `forbid`; target BOM
is boolean. Delimited source/target delimiter and quote must each be one distinct non-newline
character. Target `line_ending` is `lf` or `crlf`. CSV defaults to comma and TSV to tab.

## Value rules

- An empty delimited field is an `empty` string; the exact `null_token` is `null`.
- Configured boolean tokens compare case-insensitively.
- Locale decimal parsing uses the configured decimal separator and does not guess thousands
  separators.
- Leading-zero integers and integers longer than 15 digits remain strings by default, avoiding
  identifier loss and Excel numeric precision loss. Large integers can instead be allowed as
  numbers or rejected; explicitly emitting one as an XLSX number reports the precision risk.
- ISO dates, times, and datetimes are typed. Offset-aware values can be preserved as ISO text,
  normalized to UTC, or rejected. XLSX has no timezone-bearing cell primitive, so such values are
  stored as text and reported.
- Formula policy `preserve-text` emits an inert leading-`=` string. `evaluated` replaces the
  formula with its existing cached value and reports that the cache was not verified by a
  calculation engine. `reject` fails without promotion. Shared, array, and data-table formula
  sources currently fail closed because their multi-cell semantics cannot be flattened safely.
- CSV/TSV injection policy defaults to `escape`: dangerous string cells beginning with `=`, `+`,
  `-`, or `@` (including leading whitespace/control prefixes) receive an apostrophe. `reject`
  fails; `allow` requires an explicit request.

## Canonical JSON

JSON uses one stable multi-sheet shape. Every cell has an explicit type, so `null`, empty text,
boolean, exact decimal text, dates, and ordinary strings do not collapse:

```json
{
  "schema_version": "1.0",
  "format": "document-skills-tabular",
  "sheets": [
    {
      "name": "Data",
      "rows": [[
        {"type": "string", "value": "00123"},
        {"type": "number", "value": "12.50"},
        {"type": "null", "value": null},
        {"type": "date", "value": "2026-08-24"}
      ]]
    }
  ]
}
```

Formula-bearing JSON input may use
`{"type":"formula","formula":"A1*2","cached":{"type":"number","value":"4"}}`.
The requested formula policy is applied before any output is written.

## Bounds, streaming, and loss reporting

CSV/TSV parsing and emission are streaming, with a bounded typed buffer between source and target.
XLSX and JSON use bounded in-memory projections. Input/output byte limits, per-sheet rows, columns,
total materialized cells, and per-cell UTF-8 bytes are required gates. A sparse XLSX whose dense
tabular rectangle would exceed `max_cells` is rejected instead of allocating it.

CSV/TSV cannot preserve multiple sheets, formulas, style, or typed metadata. XLSX-to-tabular
conversion also drops tables, charts, validations, comments, and other non-cell objects. These
differences, selected-sheet drops, null-to-blank mapping, timezone-as-text mapping, and injection
escaping are recorded as `semantic_losses`, warnings, and degradations. Loss-bearing output is
validly promoted with status `degraded`, never mislabeled as lossless success.

## Legacy `.xls` input

Legacy conversion is a separate provider-required path:

```json
{
  "schema_version": "1.0",
  "operation": "xlsx.convert",
  "input": "legacy.xls",
  "output": "converted.xlsx",
  "arguments": {
    "source_format": "xls",
    "target_format": "xlsx"
  }
}
```

Only `.xls` → `.xlsx` is accepted. `sheet`, `source`, `target`, and `values` options are rejected
because LibreOffice performs a workbook conversion rather than Core tabular projection. The
provider output must pass ZIP/XML security, SpreadsheetML identity, consumer reopen, style-table,
and static-formula gates. VBA, XLM, active objects, DDE, and external targets in provider output
fail closed. Successful output is always `degraded` with `legacy-provider-conversion`; the result
reports `provider_chain: ["libreoffice"]` at the Core service seam (the public facade also records
`core-python`).
