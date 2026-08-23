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
formats, tables, defined names, hyperlinks, chart references, and shared-string metadata.
Uses the normal reject-mode security policy; active/external content returns `DS_ARCHIVE_UNSAFE`
and directs the caller to structural inspection.

### xlsx.inspect.structure

Inventories package parts, content types, relationships, media, sheets, calc chain, shared
strings, styles, tables, pivot caches, external links, dangerous content, and unknown parts
without executing or dereferencing anything. Never authorizes mutation.

### xlsx.create

Creates a workbook from bounded typed data (not raw XML). Requires an explicit output path.
The current public contract supports multiple sheets, typed cell values, formulas with optional
cached literals, workbook defined names, cell/row/column styles, custom number formats,
row height/hiding, and column width/hiding. Style records are deduplicated, and existing cells
resolve style precedence as column → row → cell override. Every created formula reports
`recalculation_required` (or `stale` when a cached literal is supplied).

Tables, charts, validation, conditional formatting, and page setup are not public create
capabilities yet. Requests for the legacy placeholder fields fail closed with
`enhancement_required` until their complete package and consumer-reopen paths are implemented.
See [`references/styles.md`](references/styles.md) for the closed style contract and a request
fragment.

### xlsx.edit

Performs bounded cell value/formula edits, cell/row/column style edits, custom number-format
addition, and sheet-label rename. Existing style tables are patched append-only: untargeted
font/fill/border/xf records, themes, and indexed colors remain intact. Requires distinct input
and output paths. Editing a precedent cell invalidates dependents to
`recalculation_required`. Preserves all untargeted package parts (pivot caches, charts,
drawings, external links, custom XML, etc.) at the payload-hash level.

Row/column structural operations and full sheet CRUD/reorder/copy are not public edit
capabilities yet and fail closed with `enhancement_required`.

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
