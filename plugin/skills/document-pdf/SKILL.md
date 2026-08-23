---
name: document-pdf
description: Read, inspect, create, edit, rewrite, extract, secure, optimize, render, OCR, and validate PDF artifacts through accepted providers.
---

# PDF documents

Use this Skill for `.pdf` requests. Core and optional accepted providers expose twelve
operations through a frozen uv/Python facade. Every operation runs in a one-shot isolated
worker. Mutations validate before output and require a distinct output path (source preserved).

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
| `pdf.create` | yes | One-or-more-page PDF with requested Latin text, PNG/JPEG images, tables, styled text, and styled vector shapes |
| `pdf.edit` | yes | Atomic bounded primitive lists: merge, split, rotate, flat outline and safe Text-annotation add/update/delete, styled/positioned opacity-aware text/image watermark, and AcroForm text/checkbox/radio/choice fill with appearances and safe text/choice flatten |
| `pdf.rewrite.apply` | yes | Latin block extract/rewrite/apply with page-layout preservation; unsupported Unicode is rejected before a candidate is written |
| `pdf.images.extract` | no | Extract directly invoked Image XObjects to an atomic deterministic `.zip`; copies JPEG and rebuilds 8-bit Gray/RGB PNG, including compatible soft-mask alpha |
| `pdf.table.extract` | no | Low-confidence geometric content-stream table heuristic with page/cell bboxes and an explicit `core-stream-heuristic` source |
| `pdf.encrypt` | yes | pypdf-backed AES-256-R5 encryption with distinct user/owner passwords, explicit permissions, and encrypted metadata |
| `pdf.decrypt` | yes | Explicit password-gated decryption; ordinary `pdf.read` remains fail-closed for encrypted input |
| `pdf.compress` | yes | Evidence-backed lossless content-stream/deduplication optimization; publishes only when output bytes are strictly smaller and semantics round-trip |
| `pdf.render` | yes | Optional Poppler page rasterization to a bounded deterministic PNG/JPEG ZIP; unavailable when `pdftoppm` is not callable |
| `pdf.ocr` | yes | Optional Poppler + Tesseract OCR to bounded text/JSON sidecars with language, confidence, and pixel bboxes; unavailable unless both executables are callable |

The canonical callable `pdf.create` smoke request is
[create-minimal.json](assets/examples/create-minimal.json). Replace its output
placeholder with a local `.pdf` path before running it.
The bounded image extraction request template is
[extract-images.json](assets/examples/extract-images.json); replace both path
placeholders before running it.
Provider and extraction templates are also available for
[table extraction](assets/examples/extract-tables.json),
[encryption](assets/examples/encrypt.json),
[decryption](assets/examples/decrypt.json),
[lossless compression](assets/examples/compress.json),
[rendering](assets/examples/render.json), and
[OCR](assets/examples/ocr.json).

## Distinct output

Mutations require an explicit output path distinct from the input. `in_place` is not
supported. The source SHA-256 is verified after every operation.

## Page-layout preservation (rewrite)

`pdf.rewrite.apply` preserves the targeted page's MediaBox/CropBox, Rotation, all
resources (font subsetting, image XObjects, ExtGState), and all surrounding text-showing
operators. Non-targeted pages match the input at the object level.

## Unicode font boundary

Core creation and rewrite currently use the built-in WinAnsi Helvetica family. CJK, RTL,
emoji, and other uncovered codepoints return `enhancement_required` during contract
validation, before any candidate or output artifact is written. There is no degraded
Unicode artifact and the implementation never emits `.notdef`, replacement glyphs, or
silently reversed RTL text.

## Images, layout, and edit transactions

Creation accepts only local PNG/JPEG assets, verifies their bytes and bounds, and emits
real Image XObjects. Page-specific size/margins, Helvetica weight/style/size/color,
line-height/alignment/wrapping, and vector stroke/fill/opacity/dash are effective PDF
operators. Text overflow fails without publishing the destination.

Image extraction supports page-resource Image XObjects invoked by page content. It
reports page, object, resource, bbox, dimensions, filter/color metadata, byte count, and
SHA-256 for each ZIP entry. Inline images, predictors, non-Gray/RGB lossless samples,
and JPEG soft masks return `enhancement_required`; they are never reported as extracted.

`pdf.edit.primitives` is an ordered bounded transaction. A failure in any primitive
publishes none of the earlier staged edits. Watermark opacity is an effective ExtGState;
text watermarks apply Helvetica size/color/rotation and named or x/y positions; image
watermarks are real Image XObjects with contain/stretch placement, rotation, and named
or x/y positions. Target pages safely clone indirect or inherited resource dictionaries.
Rotated `cover` clipping remains `enhancement_required`. AcroForm fill supports text, checkbox, radio,
and choice values, validates appearance/option states, updates `/V`, `/AS`, and `/AP`,
and sets `NeedAppearances` false. Text/choice flatten merges visible text into page
content and removes only the selected top-level field/widget; nested field graphs and
button flattening remain `enhancement_required`.

Flat destination-based outlines support add, 1-based-index update, and delete. Update
and delete accept an `expected_title` precondition. Nested outline trees and action-based
bookmarks remain inert on read and return `enhancement_required` on edit.

Annotation editing is limited to indirect, action-free `/Text` annotations in direct
page `/Annots` arrays. It supports add plus page-local 1-based-index update/delete with
an `expected_contents` precondition. Widget, Link, attachment, inline, action-bearing,
and indirect-array annotation graphs remain inventory-only or `enhancement_required`.

Page sequence editing accepts a unique ordered list of existing source pages, covering
bounded extract/reorder/delete while preserving the selected page objects. Documents with
AcroForm, outlines, or page labels are rejected until those graphs can be reconciled; page
insertion is not implemented. Page-label set supports decimal, Roman, alphabetic, and
prefix-only flat `/Nums` ranges; clear removes a flat label tree. Nested `/Kids` trees
remain `enhancement_required`.

`redact_text` is deliberately narrow true removal: it only accepts a unique Latin-1 literal
`Tj` operand in an unfiltered, non-shared content stream, replaces the operand with `()`, and
reopens the candidate to prove both extracted text and literal source bytes are absent.
Ambiguous, encoded, filtered, shared-stream, image, and non-`Tj` redaction requests are
rejected rather than covered with a black rectangle.

## Encryption, decryption, and compression

The accepted pypdf provider is pinned to `6.16.2` with the locked cryptography runtime.
`pdf.encrypt` accepts only `AES-256-R5`; RC4, AES-128, AES-256-R6, and unencrypted-metadata
requests remain `enhancement_required`. Passwords are bounded UTF-8 secret fields and never
appear in argv, provider results, diagnostics, or error messages. Keep request JSON files
private because they contain the caller-supplied secret fields.

`pdf.decrypt` accepts either the user or owner password and produces an unencrypted distinct
PDF only after page/text semantics round-trip. A wrong password preserves both source and any
existing destination. `pdf.compress` currently accepts only `lossless`; `balanced` and
`aggressive` are honest `enhancement_required` outcomes because image recompression,
downsampling, and visual quality measurement are not implemented.

## Render, OCR, and table confidence

Never invoke Poppler or Tesseract directly. `pdf.render` and `pdf.ocr` are registered only
through callable provider implementations and capability detection runs real bounded version
probes. On a Core-only machine they remain present but `available: false`; a request returns
`unavailable` without an output. Development-only PyMuPDF/Pillow installations are not
production provider evidence.

`pdf.table.extract` does not claim semantic table recognition. Its confidence is capped at
`0.4`, the source is always `core-stream-heuristic`, bboxes are approximate, and ruling lines,
merged cells, OCR tables, and cross-page continuity are not inferred.

## Page-level preservation (edit)

Each edit primitive preserves every untargeted page, object, stream, font, image,
annotation, form field, outline item, XMP metadata, and embedded file byte-for-byte
at the object payload level.

## Validation

The `validate --input` command reopens the PDF, checks header/xref/object/stream integrity,
and reports a canonical validation report. Visual/render/OCR gates honestly report
`unavailable` unless the corresponding accepted executable provider is callable and used.

## Result status

| Status | Meaning |
| --- | --- |
| `success` | Operation completed and all required gates passed |
| `degraded` | Operation completed with an explicitly authorized fidelity reduction |
| `failed` | Operation failed; no output promoted |
| `invalid_request` | Request was rejected before execution |
| `unavailable` | Required provider is not available |
