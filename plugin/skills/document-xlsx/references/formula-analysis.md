# Static formula analysis

The XLSX Core performs conservative, non-evaluating formula checks on read and on every staged
create/edit/recalculate candidate. The result is exposed as
`diagnostics.operation_result.formula_analysis`.

The report contains:

- `valid`: whether the checks found invalid syntax or references;
- `formula_cells`: the number of physical `<f>` elements, including shared-formula followers;
- category counts for `active_provider`, `normal`, `shared`, `array`, `data_table`,
  `dynamic_array`, `structured_reference`, and `external_reference`;
- counts for cell/range, defined-name, table, and external references;
- deterministic per-cell categories plus top-level issue records keyed by cell `ref`;
- `scope: "static-token-reference-checks-only"` and `calculation_engine: false`.

## Checks

The checker validates:

- balanced parentheses, array-constant braces, and string literals;
- formula text without a leading `=` (SpreadsheetML `<f>` stores the expression only);
- absence of control characters and embedded error tokens;
- A1 cell, row, and column bounds (`A1:XFD1048576`);
- existence of explicitly referenced local sheets;
- existence of ordinary workbook/sheet defined names;
- existence of named tables and simple table columns;
- external-workbook formula references are classified and rejected for mutation.

Mutation candidates (`xlsx.create`, `xlsx.edit`, `xlsx.recalculate`) use a required
`operation.formula-static-analysis` gate. A failure prevents provider invocation and atomic
promotion. `xlsx.read` uses the same gate as optional evidence so malformed legacy formulas can
still be inspected; its report does not claim that formulas calculate successfully.

## Deliberate limits

This is not a full Excel grammar or calculation engine. It does not evaluate functions, resolve
LET/LAMBDA local variables, prove cached values, fetch external workbooks, or replace LibreOffice
recalculation. LET/LAMBDA local-name existence is deliberately not guessed.

Shared, array, data-table, dynamic-array, structured, and external formulas are reported by type.
Structural mutation already rejects special formula types it cannot migrate. Provider cached-value
harvesting currently rejects shared/array/data-table formulas as `enhancement_required`, because
publishing only a master cell's value would be misleading.
