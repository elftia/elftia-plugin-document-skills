# DOCX typed requests

Every request uses `schema_version: "1.0"`. Unknown top-level or operation-specific fields are
rejected before provider execution.

## Structured read

```json
{
  "schema_version": "1.0",
  "operation": "docx.read",
  "input": "<input.docx>",
  "arguments": {
    "include_headers_footers": true,
    "max_paragraphs": 5000,
    "max_tables": 500,
    "max_table_rows": 5000,
    "max_text_chars": 250000
  }
}
```

Lower caller limits are useful for unknown documents. A reached limit is reported under
`diagnostics.operation_result.truncations` and as `DS_READ_TRUNCATED`.

## Inert structural inspection

```json
{
  "schema_version": "1.0",
  "operation": "docx.inspect.structure",
  "input": "<input.docx>",
  "arguments": {
    "include_hashes": true,
    "max_parts": 2000,
    "max_relationships": 5000
  }
}
```

Inspection always reports `mutation_authorized: false`.

## Styled creation

`report.blocks` is the only required member, and the document contains exactly the blocks
it lists. `metadata`, `header`, `footer`, `sections`, and the trailing `image` are all
optional — omit what the document does not need rather than inventing a placeholder.

```json
{
  "schema_version": "1.0",
  "operation": "docx.create",
  "output": "<created.docx>",
  "arguments": {
    "report": {
      "blocks": [
        {"type": "heading", "text": "Chapter 1", "level": 1},
        {"type": "paragraph", "text": "Body text."}
      ]
    }
  }
}
```

That request produces a one-section document with no table, no image, no header, and no
footer — the package simply has no such parts.

Block types: `heading` (levels 1–6, so a `1.1.1` outline needs no flattening), `paragraph`
(the `Normal` style, or `null`), `table` (the `TableGrid` style), and `image`. The package
carries a `Heading<n>` style for every level up to the deepest one used, and always at least
`Heading1`/`Heading2`. Image blocks render where they appear, so a caller controls placement:

```json
{
  "blocks": [
    {"type": "paragraph", "text": "Figure 1 shows the pipeline."},
    {"type": "image", "path": "<local-image.png>", "alt_text": "Pipeline", "width_inches": 4},
    {"type": "paragraph", "text": "The table below lists throughput."},
    {"type": "table", "style": "TableGrid", "rows": [["Metric", "Value"], ["Status", "Ready"]]}
  ]
}
```

The optional report-level members:

```json
{
  "metadata": {"title": "Quarterly report", "creator": "Elftia"},
  "image": {"path": "<local-image.png>", "alt_text": "Status chart", "width_inches": 4},
  "header": "Quarterly report",
  "footer": "Confidential",
  "sections": [{"orientation": "portrait"}, {"orientation": "landscape"}]
}
```

`report.image` appends one image after the last block; prefer an `image` block unless the
document really wants a trailing figure. A header or footer creates the corresponding part
and section reference; omitting it creates neither. `sections` defaults to a single portrait
section and accepts 1–32.

Every image — block or trailing — must be a bounded local PNG, JPEG, or GIF between 0.25 and
10 inches wide. Remote assets and raw OOXML are not accepted.

Creation requests are also bounded in aggregate: at most 8,192 table cells, 32 images,
64 MiB of image bytes, 10,000 structured value/container nodes, and 524,288 UTF-8 bytes
across report string values. The request-file loader accepts at most 1,048,576 bytes. These
limits are enforced before provider selection and are intentionally below the 2 MiB worker
result envelope.

## Run-aware replacement

```json
{
  "schema_version": "1.0",
  "operation": "docx.edit.replace-text",
  "input": "<input.docx>",
  "output": "<replaced.docx>",
  "arguments": {
    "case_sensitive": true,
    "replacements": [
      {"search": "DRAFT", "replace": "FINAL", "expected_matches": 3}
    ]
  }
}
```

`expected_matches` is checked against the immutable original streams before any XML mutation.

## Scalar template

```json
{
  "schema_version": "1.0",
  "operation": "docx.template.apply",
  "input": "<template.docx>",
  "output": "<rendered.docx>",
  "arguments": {
    "missing_policy": "error",
    "variables": {
      "customer": {"name": "Ada"},
      "region": "APAC"
    }
  }
}
```

Only scalar values are accepted. Nested objects are flattened for dot lookup; arrays, functions,
raw XML, loops, conditions, and expression syntax are rejected.
