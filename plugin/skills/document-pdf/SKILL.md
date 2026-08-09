---
name: document-pdf
description: Read, inspect, create, edit, rewrite, and validate PDF artifacts through the bundled document core.
---

# PDF documents

Use this Skill for `.pdf` requests. The Core provides five accepted operations through
a frozen uv/Python facade. Every operation runs in a one-shot isolated worker, validates
before output, and defaults to a distinct output path (source preserved).

## Commands

All agent-visible commands use the exact frozen uv family. Do NOT invoke Node, npm,
dotnet, LibreOffice, Poppler, Tesseract, an MCP tool, or a provider script directly.

```text
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" doctor --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" capabilities --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" run --request request.json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" validate --input artifact.pdf --json
```

## Operations

| Operation | Mutation | Description |
| --- | --- | --- |
| `pdf.read` | no | Structured read: page count, page boxes, metadata, fonts, images, text, AcroForm, annotations, embedded files |
| `pdf.inspect.structure` | no | Inert structural inspection: objects, xref, streams, fonts, images, actions (classified inert, never executed) |
| `pdf.create` | yes | Styled PDF with headings/paragraphs, table, image, vector shapes, 2+ pages |
| `pdf.edit` | yes | Edit primitives: merge, split, rotate, watermark, form-fill with page-level preservation |
| `pdf.rewrite.apply` | yes | Block extract/rewrite/apply with page-layout preservation and CJK/RTL glyph-degradation honesty |

## Distinct output

Mutations require an explicit output path distinct from the input. `in_place` is not
supported. The source SHA-256 is verified after every operation.

## Page-layout preservation (rewrite)

`pdf.rewrite.apply` preserves the targeted page's MediaBox/CropBox, Rotation, all
resources (font subsetting, image XObjects, ExtGState), and all surrounding text-showing
operators. Non-targeted pages match the input at the object level.

## CJK/RTL glyph-degradation honesty

When rewritten text contains a CJK/RTL codepoint not covered by the embedded font subset,
the result reports each uncovered codepoint under
`diagnostics.operation_result.rewrite.glyph_degradation` and sets `status: degraded`.
The rewrite never silently emits `.notdef` or wrong glyphs.

## Page-level preservation (edit)

Each edit primitive preserves every untargeted page, object, stream, font, image,
annotation, form field, outline item, XMP metadata, and embedded file byte-for-byte
at the object payload level.

## Validation

The `validate --input` command reopens the PDF, checks header/xref/object/stream integrity,
and reports a canonical validation report. Visual/render/OCR gates honestly report
`unavailable` without Poppler/LibreOffice/Tesseract.

## Result status

| Status | Meaning |
| --- | --- |
| `success` | Operation completed and all required gates passed |
| `degraded` | Operation completed with honest glyph degradation (rewrite) |
| `failed` | Operation failed; no output promoted |
| `invalid_request` | Request was rejected before execution |
| `unavailable` | Required provider is not available |
