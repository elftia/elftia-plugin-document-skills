# PDF Format Module

## Purpose

The PDF module owns bounded PDF read, inert inspection, typed creation, page-preserving edits, block rewrite/apply, byte preflight, and structural validation.

## Ownership and boundaries

Core Python owns all five registered PDF operations. It preserves page/object/resource identity where the operation contract requires it and reports glyph limitations explicitly. Visual rendering and OCR are validation dimensions, not silently substituted public operations.

The module does not invoke Poppler, Tesseract, LibreOffice, Node, or an MCP tool directly from the public Skill. Agent workflow detail remains in the [PDF Skill](../../../../skills/document-pdf/SKILL.md).

## Entry points

Use the shared Skill façade. Contract parsing starts in [`contracts.py`](contracts.py), service routing in [`service.py`](service.py), and structural validation in the module's validation helpers.

## Operations and availability

| Operation | Availability | Contract summary |
| --- | --- | --- |
| `pdf.read` | Core Python | Page boxes, metadata, fonts, images, text, forms, annotations, and embedded-file projection |
| `pdf.inspect.structure` | Core Python | Inert object/xref/stream/font/image/action inventory; actions are never executed |
| `pdf.create` | Core Python | Typed multi-page styled PDF with text, table, image, and vector content |
| `pdf.edit` | Core Python | Merge, split, rotate, watermark, and form-fill with page-level preservation |
| `pdf.rewrite.apply` | Core Python | Block extract/rewrite/apply with page-layout preservation and explicit CJK/RTL glyph degradation |

## Safety and failure semantics

Mutations require explicit distinct outputs and verify the source SHA-256 afterward. Required header/xref/object/stream checks and output reopen complete before promotion. Untargeted pages and object payloads remain preserved according to each edit/rewrite contract.

When an embedded font subset cannot represent requested CJK/RTL code points, rewrite reports each uncovered code point and returns `degraded`; it never silently emits incorrect glyphs. Visual/render/OCR gates remain `unavailable` unless an accepted provider actually runs.

## Verification

The [plugin test suite](../../../../tests/README.md) owns the PDF contract, public façade, and operation coverage. Exact focused and aggregate commands belong to the [producer verification guide](../../../../../scripts/README.md).

## Related documentation

- [PDF Skill](../../../../skills/document-pdf/SKILL.md)
- [Shared Core](../../README.md)
- [Providers](../../providers/README.md)
- [Schemas](../../../../schemas/README.md)
- [Consumer validation](../../../../consumer_validation/README.md)
- [Tests](../../../../tests/README.md)
