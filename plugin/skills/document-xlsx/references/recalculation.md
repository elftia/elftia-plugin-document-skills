# Formula recalculation

`xlsx.create` and `xlsx.edit` accept a request-level `recalculation` field:

| Policy | Behavior when formulas exist |
| --- | --- |
| `auto` | Use LibreOffice when callable. If it is absent, crashes, or times out, publish the validated Core candidate as `degraded` with truthful formula states. |
| `required` | Require an accepted LibreOffice pass. Provider absence/failure prevents promotion and preserves an existing destination. |
| `skip` | Never call LibreOffice. Publish the Core candidate and retain stale, never-calculated, or recalculation-required states. |

The default is `auto`. If the workbook contains no formulas, all three policies are
`not_applicable` and no provider is invoked.

```json
{
  "schema_version": "1.0",
  "operation": "xlsx.create",
  "output": "calculated.xlsx",
  "arguments": {
    "recalculation": "required",
    "workbook": {
      "metadata": {},
      "sheets": [
        {
          "name": "Sheet1",
          "rows": [
            {
              "cells": [
                {"ref": "A1", "value": "10", "type": "n"},
                {"ref": "A2", "formula": "A1*2", "type": "n"}
              ]
            }
          ],
          "number_formats": []
        }
      ],
      "defined_names": [],
      "tables": []
    }
  }
}
```

## Explicit operation

Use `xlsx.recalculate` to recalculate an existing workbook:

```json
{
  "schema_version": "1.0",
  "operation": "xlsx.recalculate",
  "input": "source.xlsx",
  "output": "recalculated.xlsx",
  "arguments": {}
}
```

Input and output must be distinct. Formula workbooks require LibreOffice; provider
absence, crash, timeout, malformed output, formula identity changes, or detected formula errors
fail without promotion. Workbooks without formulas succeed without invoking a provider.

## Acceptance boundary

The Core never publishes LibreOffice's complete rewritten package. Instead it:

1. validates the Core staged candidate;
2. runs LibreOffice in its isolated temporary profile;
3. independently reopens the provider artifact;
4. proves formula cell keys and formula text are unchanged;
5. rejects `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#N/A`, and `#NUM!` results;
6. copies only accepted cached values/result types into the original Core candidate;
7. reopens and validates formula, source, destination, and part-preservation evidence;
8. atomically promotes the exact validated bytes.

Only this accepted path may report formula state `recalculated`, set
`recalculation_provider` to `libreoffice`, append `libreoffice` to `provider_chain`, and report
`achieved_fidelity: "enhanced"`.
