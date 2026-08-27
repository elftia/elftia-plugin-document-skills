# Inert template sanitization

`pptx.template.sanitize` creates an independent `.pptx` candidate without
executing, activating, downloading, or dereferencing anything in the source.
It accepts `.pptx` and `.potx`; template identity is always downgraded to the
ordinary presentation main content type before promotion.

The policy is intentionally fixed. No weaker combination is accepted:

```json
{
  "schema_version": "1.0",
  "operation": "pptx.template.sanitize",
  "input": "template.potx",
  "output": "template.sanitized.pptx",
  "arguments": {
    "expected_input_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "policy": {
      "active_content": "reject",
      "external_relationships": "remove",
      "hidden_or_unselected_content": "keep",
      "ole_and_embedded_files": "remove",
      "signatures": "reject",
      "unreachable_parts": "purge"
    }
  }
}
```

`expected_input_sha256` is optional, but when supplied it is a lowercase
64-character SHA-256 precondition. A mismatch returns
`DS_STALE_PRECONDITION` before staging. Input and output must be distinct.

Successful diagnostics contain:

- removed relationship records with source part, relationship id/type,
  original relationship hash, and hashed—not plaintext—target;
- removed part names, byte sizes, original hashes, and purge reasons;
- changed/preserved/removed part mappings and the copy-through manifest;
- physical-purge evidence proving removed relationships/parts are absent and
  the candidate has no orphan, dangling, external, active, or embedded graph;
- `.potx` input and `.pptx` output content-type identities;
- truthful Core, schema, visual, LibreOffice, PowerPoint, and license states.

External relationships and OLE/package relationships are removed together
with their XML references. If a chart uses an embedded workbook, every
supported cached `numRef`/`strRef` is converted to `numLit`/`strLit` before the
workbook is purged. A missing cache or unsupported reference form returns
`DS_UNSUPPORTED_FEATURE`; it never drops the workbook while leaving an invalid
chart.

Signed packages, VBA, XLM, ActiveX, DDE, executable content, ambiguous
relationship ids, dangling internal targets, ZIP/XML bombs, and unsafe package
paths fail closed with no output. Hidden/unselected slides and notes are kept
by B1 policy; their later semantic selection and physical purge belong to
`pptx.create.from-template`.
