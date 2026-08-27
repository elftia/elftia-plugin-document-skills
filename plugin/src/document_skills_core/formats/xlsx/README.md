# XLSX Format Module

## Purpose

The XLSX module owns bounded spreadsheet read, inert inspection, authoring, editing, formula-state truth, tabular conversion, templates, summaries, native pivots, and provider-backed recalculation, schema, and render paths.

## Ownership and boundaries

Core Python owns the OOXML/tabular contracts, styles and native objects, conservative formula analysis, mutation/reference migration, semantic-loss receipts, and atomic publication. LibreOffice may supply recalculated caches, render output, or legacy conversion only after its result is independently accepted. .NET/OpenXML owns full schema validation.

The module never evaluates formulas itself, treats stored caches as current, executes VBA/XLM, or reports provider-produced whole-package bytes without Core reconstruction and validation. Detailed agent policy remains in the [XLSX Skill](../../../../skills/document-xlsx/SKILL.md).

## Entry points

Use the shared Skill façade. Check `capabilities --json` before formula recalculation, rendering, legacy `.xls` conversion, or full schema validation. The normative feature matrix is [`feature-truth-table.json`](../../../../skills/document-xlsx/references/feature-truth-table.json).

## Operations and availability

| Operation | Availability | Contract summary |
| --- | --- | --- |
| `xlsx.read` | Core Python | Structured workbook projection including formulas, styles, tables, validations, charts, pivots, metadata, notes, and hyperlinks |
| `xlsx.inspect.structure` | Core Python | Inert package/object/dangerous-content inventory |
| `xlsx.create` | Core Python; optional LibreOffice recalculation | Typed workbooks with formulas, styles, native tables/validations/formatting/charts/sparklines and worksheet metadata |
| `xlsx.edit` | Core Python; optional LibreOffice recalculation | Typed cell/style/structure/sheet/object/metadata edits with reference migration and preservation gates |
| `xlsx.recalculate` | Core operation; LibreOffice required for formula workbooks | Accept provider caches only after formula identity, error, reopen, and preservation validation; no-formula input is `not_applicable` |
| `xlsx.convert` | Core for XLSX/CSV/TSV/canonical JSON; LibreOffice for `.xls` input | Explicit value/formula/injection/loss policy with typed semantic-loss receipts |
| `xlsx.template.instantiate` | Core Python | Exact `.xltx`/`.xltm` identity transition with optional typed edits and inert macro copy-through |
| `xlsx.summary.aggregate` | Core Python | Deterministic ordinary grouped summary table; explicitly not a native pivot |
| `xlsx.pivot.create` | Core Python | Native worksheet pivot table/cache/records with bounded axes, filter, and value field |
| `xlsx.validate.schema` | .NET/OpenXML | Full SpreadsheetDocument OpenXML SDK validation |
| `xlsx.render` | LibreOffice | Distinct PDF plus bounded worksheet risk evidence; not visual parity proof |

## Safety and failure semantics

Formula states are only `recalculated`, `stale`, `never_calculated`, or `recalculation_required`; only an accepted recalculation-provider result may produce `recalculated`. Static analysis checks syntax and references but never evaluates a formula.

Mutations use distinct outputs and preserve untargeted parts. Dangerous structural edits, unsupported special formulas, external references, macro content outside inert policy, provider errors, schema failures, and ambiguous object selectors fail closed. Any conversion loss or unverified formula-cache use is disclosed as degradation.

## Verification

The [plugin test suite](../../../../tests/README.md) owns the public XLSX contract and operation coverage. Exact focused and aggregate commands belong to the [producer verification guide](../../../../../scripts/README.md); the distribution E2E is documented in [`e2e/README.md`](../../../../../e2e/README.md).

## Related documentation

- [XLSX Skill and references](../../../../skills/document-xlsx/SKILL.md)
- [Shared Core](../../README.md)
- [Providers](../../providers/README.md)
- [Schemas](../../../../schemas/README.md)
- [Tests](../../../../tests/README.md)
- [Distribution E2E](../../../../../e2e/README.md)
