# Macro-enabled workbooks and templates

## Inert `.xlsm` read and inspection

`xlsx.read` accepts `.xlsm` but authorizes only the `vba` security category. VBA payloads are
copied/inventoried as bytes and never parsed or executed. LibreOffice recalculation is not called
for `.xlsm`. XLM macro sheets, ActiveX, OLE embeddings, DDE, external relationship targets, and
executable package parts remain rejected. `xlsx.inspect.structure` can inventory every dangerous
category but always returns `mutation_authorized: false`.

Macro evidence includes payload and signature part SHA-256 values plus exact relationship source,
id, type, target, and target mode. `cryptographic_verification` is always `not_performed`.

## keep-VBA mutation

```json
{
  "schema_version": "1.0",
  "operation": "xlsx.edit",
  "input": "input.xlsm",
  "output": "output.xlsm",
  "arguments": {
    "keep_vba": true,
    "recalculation": "skip",
    "edits": [
      {"sheet": "Sheet1", "type": "cell_value", "ref": "A1", "value": "42"}
    ]
  }
}
```

Both paths must use `.xlsm`; `keep_vba: true` is mandatory. The staged and reopened output must
retain every VBA/signature payload hash and exact related relationship. A signed input reports
`signature_state: invalidated_by_package_mutation`, because preserving signature bytes is not the
same as preserving signature validity.

## Template-as-base

`xlsx.template.instantiate` accepts only `.xltx` → `.xlsx` or `.xltm` → `.xlsm`. It changes the
workbook main content type, optionally applies the normal bounded edit primitives, reopens the
candidate, proves source/copy-through preservation, and atomically promotes it.

```json
{
  "schema_version": "1.0",
  "operation": "xlsx.template.instantiate",
  "input": "base.xltm",
  "output": "instance.xlsm",
  "arguments": {
    "keep_vba": true,
    "recalculation": "skip"
  }
}
```

Template code and macros are never executed. `.xltm` uses the same VBA/signature preservation and
signature-invalidation disclosure as `.xlsm` edit.
