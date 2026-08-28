# PDF Format Module

## Purpose

The PDF module owns bounded PDF read, inert inspection, typed creation, page-preserving edits, block rewrite/apply, byte preflight, and structural validation.

## Ownership and boundaries

Core Python owns seven registered PDF operations. It preserves page/object/resource identity where the operation contract requires it and reports glyph limitations explicitly. Five additional operations are registered only through accepted, separately bounded PDF providers.

The module does not invoke Poppler, Tesseract, pypdf, LibreOffice, Node, or an MCP tool directly from the public Skill. The shared provider registry owns optional-provider selection and the public supervisor retains the transaction and result boundary. Agent workflow detail remains in the [PDF Skill](../../../../skills/document-pdf/SKILL.md).

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
| `pdf.images.extract` | Core Python | Bounded direct image extraction with explicit unsupported-filter and mask semantics |
| `pdf.table.extract` | Core Python | Conservative text/ruling table candidates with explicit confidence and no OCR substitution |
| `pdf.encrypt` | `pypdf` provider | Password encryption through an identity-bound private provider with staged-output validation |
| `pdf.decrypt` | `pypdf` provider | Explicit-password decryption with encrypted-input and output-reopen checks |
| `pdf.compress` | `pypdf` provider | Lossless stream compression with structural and semantic preservation evidence |
| `pdf.render` | `poppler` provider | Bounded page raster evidence packaged under the PDF provider contract |
| `pdf.ocr` | `tesseract-ocr` provider | Bounded OCR evidence; never silently replaces Core PDF text extraction |

## Safety and failure semantics

Mutations require explicit distinct outputs and verify the source SHA-256 afterward. Required header/xref/object/stream checks and output reopen complete before promotion. Untargeted pages and object payloads remain preserved according to each edit/rewrite contract.

When an embedded font subset cannot represent requested CJK/RTL code points, rewrite reports each uncovered code point and returns `degraded`; it never silently emits incorrect glyphs. Encryption, decryption, compression, render, and OCR remain `unavailable` unless their accepted provider actually runs.

## Verification

The [plugin test suite](../../../../tests/README.md) owns the PDF contract, public façade, and operation coverage. Exact focused and aggregate commands belong to the [producer verification guide](../../../../../scripts/README.md).

## Related documentation

- [PDF Skill](../../../../skills/document-pdf/SKILL.md)
- [Shared Core](../../README.md)
- [Providers](../../providers/README.md)
- [Schemas](../../../../schemas/README.md)
- [Consumer validation](../../../../consumer_validation/README.md)
- [Tests](../../../../tests/README.md)
