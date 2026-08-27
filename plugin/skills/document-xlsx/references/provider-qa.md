# Provider-gated schema and render QA

These operations are present in capability reports even when their optional provider is absent.
They are callable only when detection proves that the corresponding contained provider can run.

## OpenXML schema validation

```json
{
  "schema_version": "1.0",
  "operation": "xlsx.validate.schema",
  "input": "book.xlsx",
  "arguments": {"max_errors": 100}
}
```

- Provider: `dotnet-openxml` with .NET 8 and the pinned OpenXML SDK helper.
- Input: `.xlsx` or inert `.xlsm`; output is forbidden.
- `max_errors`: integer from 1 through 1000, default 100.
- `schema.full: pass` means the SpreadsheetDocument validator actually ran and returned no
  errors. A Core reopen alone never satisfies this gate.
- Invalid packages retain a bounded part/path/description/error-type report and return
  `failed`; provider absence returns `unavailable`.
- Formula calculation and visual fidelity are outside this operation.

## XLSX to PDF render

```json
{
  "schema_version": "1.0",
  "operation": "xlsx.render",
  "input": "book.xlsx",
  "output": "book.pdf",
  "arguments": {
    "max_sheets": 50,
    "max_cells_per_sheet": 1000,
    "max_findings": 100
  }
}
```

- Provider: `libreoffice`; input is `.xlsx` and output is a distinct `.pdf` path.
- Bounds: `max_sheets` 1–100, `max_cells_per_sheet` 1–10000, and `max_findings` 1–1000.
- The source package is screened before LibreOffice loads it. External/active content remains
  rejected, and macros are not accepted on this render path.
- The PDF is promoted only after magic, object structure, page tree, source preservation, and
  PDF reopen gates pass.
- `visual.render: pass` proves only that LibreOffice produced a PDF which the Core reopened.
  It does not prove Excel-versus-LibreOffice parity, text visibility, or chart/table appearance.
- Per-sheet evidence is metadata-based and bounded. It reports hidden data, wide columns,
  potential unwrapped-text truncation, print settings, and declared chart/table counts as risks,
  not as visual-pass assertions.
- Current public output is PDF only. PNG output and exact PDF-page-to-sheet attribution remain
  unavailable.
