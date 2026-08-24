---
name: document-xlsx
description: Read, inspect, create, edit, summarize, instantiate, recalculate, and convert XLSX/tabular spreadsheet artifacts through the bundled document core.
---

# XLSX workbooks

Use this Skill for `.xlsx`, inert `.xlsm`, template-as-base, grouped summaries, and bounded tabular conversion requests. The Core capability supports eight operations:
`xlsx.read`, `xlsx.inspect.structure`, `xlsx.create`, `xlsx.edit`, and
`xlsx.recalculate`, plus `xlsx.convert`, `xlsx.template.instantiate`, and
`xlsx.summary.aggregate`. The public contract and validation run through the frozen
uv/Python facade. LibreOffice is an optional isolated enhancement for read/create/edit and is
required when `xlsx.recalculate` is asked to recompute a workbook that contains formulas or
when `xlsx.convert` explicitly converts legacy `.xls` input to `.xlsx`.

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
through an accepted recalculation provider.** Create/edit default to `recalculation: "auto"`:
without LibreOffice they still publish the validated Core artifact and honestly retain the
stale/never/recalculation-required state. Such outstanding formulas produce `degraded` plus an
`outstanding-formula-recalculation` degradation. Summary aggregation that explicitly consumes
formula caches also reports `summary-cached-formula-values`. See
[`references/recalculation.md`](references/recalculation.md) for policy and gate details.

Every formula-bearing read/create/edit/recalculate candidate also receives conservative static
analysis. It checks basic token balance, A1 bounds, local sheet/defined-name/table-column
existence, and classifies normal, shared, array, data-table, dynamic-array, structured, and
external formulas. This analysis never evaluates a formula and never substitutes for Excel or
LibreOffice. See [`references/formula-analysis.md`](references/formula-analysis.md).

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
The `formula_analysis` report records static issues and special formula categories without
claiming calculated-value correctness.
`.xlsx` uses the normal reject-mode security policy. `.xlsm` permits only inert VBA inventory;
VBA is neither parsed nor executed, and formula recalculation is forced to `skip`. XLM, ActiveX,
OLE, DDE, external targets, executable parts, or external formulas still return
`DS_ARCHIVE_UNSAFE` and direct the caller to structural inspection.

### xlsx.inspect.structure

Inventories package parts, content types, relationships, media, sheets, calc chain, shared
strings, styles, tables, data validations, conditional formats, pivot caches, external links,
native charts/drawings, dangerous content, and unknown parts
without executing or dereferencing anything. Worksheet print metadata, hyperlinks, cell notes,
and workbook properties are included in the inert projection. Formula categories and external
formula references are reported inertly. For `.xlsm`, VBA/signature parts, hashes, and exact
relationships are inventoried without cryptographic verification. Never authorizes mutation.

### xlsx.create

Creates a workbook from bounded typed data (not raw XML). Requires an explicit output path.
The current public contract supports multiple sheets, typed cell values, formulas with optional
cached literals, workbook defined names, cell/row/column styles, custom number formats,
row height/hiding, column width/hiding, native tables, data validations, and conditional
formatting (`cellIs`, `expression`, color scales, data bars, and icon sets), native
column/bar/line/pie/scatter charts, per-sheet view/page setup/header/footer/print ranges,
inert internal hyperlinks, legacy cell notes, and workbook properties. Style and
differential-style records are deduplicated, and existing cells resolve style precedence as
column → row → cell override. Before an accepted provider runs, every created formula reports
`recalculation_required` (or `stale` when a cached literal is supplied). The request-level
`recalculation` policy is `auto`, `required`, or `skip`.
Formula syntax, bounds, local sheet/defined-name/table-column references, and unsupported
external references are checked before any provider call or promotion.

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

The request-level `recalculation` policy is `auto`, `required`, or `skip`. A successful accepted
provider pass updates only formula cached values/result types and workbook calculation metadata
in the Core candidate; the provider's whole-package rewrite is never published directly.
Static formula analysis runs on both the Core candidate and accepted final candidate. Existing
shared/array/data-table formulas are classified; structural edits and provider recalculation
continue to fail closed where their special semantics cannot be preserved.

Structural edits migrate formulas, defined names, tables, charts, data-validation and
conditional-format formulas/ranges, internal hyperlinks, merged cells, drawing anchors, print
areas, page breaks, and calc state. A dangerous edit fails closed instead of emitting a repair-
prone workbook: shared/array/data-table formulas, external-workbook references, pivots, sheet
deletion with inbound references/related objects, and sheet copy with related objects return
`enhancement_required`. Plain worksheet copy is available. See
[`references/edits.md`](references/edits.md) for the closed primitive fields and examples.

For `.xlsm`, input and output must both use `.xlsm`, `keep_vba: true` is mandatory, and
`recalculation` is fixed to `skip`. Mutation copy-through proves VBA payload hashes plus VBA and
signature relationships are unchanged. The Core never verifies or executes macro code. When a
signature is present, any package mutation reports `invalidated_by_package_mutation`, emits a
warning/degradation, and never implies that the preserved signature remains valid. See
[`references/macro-templates.md`](references/macro-templates.md).

### xlsx.summary.aggregate

Builds an ordinary grouped summary worksheet and native table in a distinct output. It supports
one or more group columns, `sum`/`average`/`min`/`max`/row count/nonblank count/distinct count,
stable multi-key sorting, and deterministic top-N. Source and output bounds are explicit; text
keys such as leading-zero identifiers remain text. Numeric text is accepted only with explicit
`numeric_policy: "coerce-text"`.

This operation is **not a native pivot table**. The result and validation gates report
`summary.kind: "ordinary_table"` and `native_pivot: false`; the new sheet is verified to have no
pivot relationship. Formula source cells are rejected by default. Explicit
`formula_policy: "cached"` uses only present stored results and emits a degradation because no
calculation engine verified them. `.xlsm` requires `keep_vba: true` and retains the normal inert
macro/signature preservation evidence. See [`references/summary.md`](references/summary.md).

### xlsx.recalculate

Requires distinct `input` and `output` paths and accepts an empty `arguments` object. For a
formula workbook it requires callable LibreOffice, validates that formula keys and formula text
are unchanged, rejects formula error tokens, harvests cached values/result types, reopens the
Core-patched candidate, proves source/unknown-part preservation, and only then promotes it. If
LibreOffice is unavailable or fails, no output is promoted. A workbook without formulas succeeds
as `not_applicable` without invoking LibreOffice.
Shared, array, and data-table formula workbooks are currently classified and rejected as
`enhancement_required` for provider value harvesting instead of being falsely marked recalculated.

### xlsx.convert

Converts among XLSX, CSV, TSV, and canonical typed JSON with explicit `source_format` and
`target_format`. Text inputs and outputs have closed encoding, BOM, delimiter, quote, and line-
ending options. Value policy distinguishes null from empty text, parses configurable boolean and
locale-decimal tokens, preserves leading-zero and longer-than-15-digit integers as text by
default, and handles ISO date/time/timezone values explicitly. Formula policy is one of
`preserve-text`, `evaluated`, or `reject`; evaluated mode requires a cached value and never claims
that the cache was recalculated. CSV/TSV injection safety defaults to apostrophe escaping and can
be changed only explicitly. See [`references/conversion.md`](references/conversion.md) for the
canonical JSON shape, request fields, bounded streaming strategy, and loss codes.

Delimited output contains one selected sheet. Canonical JSON keeps multiple sheets and typed cell
envelopes. Every loss—such as dropped XLSX styles/objects, extra sheets, formula expressions,
typed metadata, null representation, timezone typing, or injection escaping—is reported in
`diagnostics.operation_result.semantic_losses`, canonical degradations, and warnings. Any loss
makes the promoted result `degraded`; it is never presented as lossless conversion.

Legacy `.xls` is input-only and converts only to `.xlsx`. This path accepts no tabular value,
sheet, encoding, or delimiter options; it requires callable LibreOffice, reopens the produced
OOXML, performs consumer and static-formula validation, rejects any VBA/XLM/active/external
provider output, preserves the `.xls` source, and promotes atomically. It always reports the
`legacy-provider-conversion` compatibility loss and real LibreOffice provider diagnostics.

### xlsx.template.instantiate

Instantiates `.xltx` to `.xlsx` or `.xltm` to `.xlsm` by copy-through and an exact workbook main
content-type transition. It accepts an optional non-empty `edits` array using the same bounded
typed primitives as `xlsx.edit`; `recalculation` is currently fixed to `skip`. `.xltm` requires
explicit `keep_vba: true`. VBA/signature payloads and relationships are preserved exactly, macro
code is never executed, and a preserved signature is explicitly reported invalid after the
package mutation. Any reverse or cross-extension pairing fails contract validation. See
[`references/macro-templates.md`](references/macro-templates.md).

The normative operation/feature status is recorded in
[`references/feature-truth-table.json`](references/feature-truth-table.json). Public regression
tests execute every feature marked `available` through this Skill's `scripts/run.py` and reopen
the promoted artifact with an independent consumer.

## Result status interpretation

| Status | Meaning |
| --- | --- |
| `success` | All required gates pass; no formulas require recalculation. |
| `degraded` | Required gates pass, but formula recalculation remains outstanding, conversion reports semantic loss, or a preserved macro signature was invalidated by mutation. |
| `enhancement_required` | The request requires an unimplemented optional provider. |
| `unavailable` | A required provider, such as LibreOffice for explicit formula recalculation, is unavailable; no output is promoted. |
| `invalid_request` | Request arguments are invalid; no file is mutated. |
| `failed` | A provider or validation failure occurred; no output is promoted. |

## Distinct output rule

Mutations require an explicit output path. For `xlsx.edit`, `xlsx.recalculate`, `xlsx.convert`,
`xlsx.template.instantiate`, and `xlsx.summary.aggregate`, output
resolving to input is rejected as `DS_OUTPUT_EQUALS_INPUT`. The source artifact is never modified.
