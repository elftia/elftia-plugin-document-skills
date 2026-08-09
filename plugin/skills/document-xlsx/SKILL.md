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

Creates a styled workbook from bounded typed data (not raw XML). Requires an explicit output
path. Supports multiple sheets, styled cells, formulas, number formats, tables, chart
references, defined names, and header/footer/page-setup metadata. Every created formula
reports `recalculation_required` (or `stale` when a cached literal is supplied).

### xlsx.edit

Performs cell value/formula edits, row/column operations, and sheet operations with
run-aware style preservation. Requires distinct input and output paths. Editing a precedent
cell invalidates all transitive dependents to `recalculation_required`. Preserves all
untargeted package parts (pivot caches, charts, drawings, external links, custom XML, etc.)
at the payload-hash level.

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
