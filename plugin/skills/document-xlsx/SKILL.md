---
name: document-xlsx
description: Read, inspect, create, and edit XLSX spreadsheet artifacts through the bundled document core.
---

# XLSX workbooks

Use this Skill for `.xlsx` requests. The Core XLSX capability supports four operations:
`xlsx.read`, `xlsx.inspect.structure`, `xlsx.create`, and `xlsx.edit`. All operations run
through the frozen uv/Python facade without Node, npm, LibreOffice, or dotnet.

## Formula-state policy

Every formula cell reports its cached value (when present) AND a recalculation state drawn
from a closed enum:

| State | Meaning |
| --- | --- |
| `recalculated` | A recalculation provider (LibreOffice) actually recomputed the value. Not reported without an accepted provider. |
| `stale` | A cached value exists but may not be current (e.g. `fullCalcOnLoad` set, or created with an explicit cached literal). |
| `never_calculated` | The formula has no cached value. |
| `recalculation_required` | A write or dependent invalidation requires recalculation. |

**Never report a formula as recalculated or correct unless the result explicitly proves it
through an accepted recalculation provider.** Without LibreOffice, the recalculation gate is
`unavailable` and the result status is `degraded` with an `outstanding-formula-recalculation`
degradation.

## Commands

```text
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" doctor --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" capabilities --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" run --request request.json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" validate --input artifact.xlsx --json
```

## Operations

### xlsx.read

Reads a structured projection of sheets, rows, cells, formulas, cached values, styles, number
formats, tables, data-validation rules, conditional-format rules and resolved differential
styles, defined names, hyperlinks, native chart types/anchors/series/axes/labels/colors, and
shared-string metadata. It also projects per-sheet views/print settings, inert internal
hyperlinks, legacy cell notes, and core/extended workbook properties.
Uses the normal reject-mode security policy; active/external content returns `DS_ARCHIVE_UNSAFE`
and directs the caller to structural inspection.

### xlsx.inspect.structure

Inventories package parts, content types, relationships, media, sheets, calc chain, shared
strings, styles, tables, data validations, conditional formats, pivot caches, external links,
native charts/drawings, dangerous content, and unknown parts
without executing or dereferencing anything. Worksheet print metadata, hyperlinks, cell notes,
and workbook properties are included in the inert projection. Never authorizes mutation.

### xlsx.create

Creates a workbook from bounded typed data (not raw XML). Requires an explicit output path.
The current public contract supports multiple sheets, typed cell values, formulas with optional
cached literals, workbook defined names, cell/row/column styles, custom number formats,
row height/hiding, column width/hiding, native tables, data validations, and conditional
formatting (`cellIs`, `expression`, color scales, data bars, and icon sets), native
column/bar/line/pie/scatter charts, per-sheet view/page setup/header/footer/print ranges,
inert internal hyperlinks, legacy cell notes, and workbook properties. Style and
differential-style records are deduplicated, and existing cells resolve style precedence as
column → row → cell override. Every created formula reports
`recalculation_required` (or `stale` when a cached literal is supplied).

The legacy workbook-level `page_setup` and `chart_reference` placeholders continue to fail
closed. Native page settings belong to each sheet, and native charts use the typed `charts`
array. External hyperlink authoring remains unavailable; the Core only creates relationship-free
internal workbook locations. Unsupported placeholder requests return `enhancement_required`
until a complete package and consumer-reopen path exists.
See [`references/styles.md`](references/styles.md) for the closed style contract and a request
fragment, and [`references/native-objects.md`](references/native-objects.md) for tables,
validations, and conditional formats. See [`references/charts.md`](references/charts.md) for
native chart fields and [`references/worksheet-metadata.md`](references/worksheet-metadata.md)
for views, print settings, hyperlinks, notes, and workbook properties.

### xlsx.edit

Performs bounded cell value/formula edits, cell/row/column style and dimension edits, custom
number-format addition, row/column insertion and deletion, sheet CRUD/reorder/copy, merge/
unmerge, range clear, freeze panes, auto filters, print areas, manual page breaks, and defined-
name CRUD, native table add/resize/rename/style/delete, and data-validation and conditional-
format CRUD, plus native chart add/update/delete. Chart updates replace a named chart's complete
typed definition, including its series ranges and anchor; unknown or ambiguous selectors fail
before promotion. Existing style and differential-style tables are patched append-only: untargeted
font/fill/border/xf records, themes, and indexed colors remain intact. Requires distinct input
and output paths. Editing a precedent cell invalidates dependents to
`recalculation_required`. Preserves all untargeted package parts (pivot caches, charts,
drawings, external links, custom XML, etc.) at the payload-hash level.

Worksheet edits also cover view/page setup/header/footer/print titles, internal hyperlink CRUD,
legacy cell-note CRUD, and targeted workbook-property updates. Deleting the last note removes
only its declared comments/VML parts; unrelated legacy VML remains preserved. External hyperlink
mutation and ambiguous/unsafe legacy drawing composition fail closed.

Structural edits migrate formulas, defined names, tables, charts, data-validation and
conditional-format formulas/ranges, internal hyperlinks, merged cells, drawing anchors, print
areas, page breaks, and calc state. A dangerous edit fails closed instead of emitting a repair-
prone workbook: shared/array/data-table formulas, external-workbook references, pivots, sheet
deletion with inbound references/related objects, and sheet copy with related objects return
`enhancement_required`. Plain worksheet copy is available. See
[`references/edits.md`](references/edits.md) for the closed primitive fields and examples.

The normative operation/feature status is recorded in
[`references/feature-truth-table.json`](references/feature-truth-table.json). Public regression
tests execute every feature marked `available` through this Skill's `scripts/run.py` and reopen
the promoted artifact with an independent consumer.

## Result status interpretation

| Status | Meaning |
| --- | --- |
| `success` | All required gates pass; no formulas require recalculation. |
| `degraded` | Required gates pass but formulas require recalculation (provider unavailable). |
| `enhancement_required` | The request requires an unimplemented optional provider. |
| `invalid_request` | Request arguments are invalid; no file is mutated. |
| `failed` | A provider or validation failure occurred; no output is promoted. |

## Distinct output rule

Mutations (create, edit) require an explicit output path. Output resolving to input is
rejected as `DS_OUTPUT_EQUALS_INPUT`. The source artifact is never modified.
