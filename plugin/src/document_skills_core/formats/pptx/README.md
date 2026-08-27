# PPTX Format Module

## Purpose

The PPTX module owns direct PresentationML read, inspection, typed creation/editing, content entry, templates, editable SVG/scene flows, equations, and provider-gated HTML, reconstruction, render, conversion, and schema operations.

## Ownership and boundaries

Core Python owns the public contract, package graph, typed scene emission, stable selectors, transactions, deep validation, and promotion. Private providers contribute only accepted bounded results: a system browser for HTML scene capture, configured OCR/vision for layered reconstruction, LibreOffice for render/conversion, and .NET/OpenXML for schema validation.

The module does not depend on python-pptx or PptxGenJS, download a browser, infer editable output from a whole-slide screenshot, execute active content, or equate structural validation with PowerPoint/LibreOffice consumer success. Agent workflow detail remains in the [PPTX Skill](../../../../skills/document-pptx/SKILL.md).

## Entry points

Use the shared Skill façade and probe `capabilities --json` before provider-backed work. Specialized request/receipt contracts are split across the Skill's [`references/`](../../../../skills/document-pptx/references/) directory; the [PPTX ecosystem ADR](../../../../../docs/adr/0001-pptx-ecosystem-phase-bc-contract-and-operations.md) records the B2–B7 boundaries.

## Operations and availability

| Operation | Availability | Contract summary |
| --- | --- | --- |
| `pptx.read` | Core Python | Structured slide/object/text/table/chart/media/equation/notes/layout projection with reusable selectors |
| `pptx.inspect.structure` | Core Python | Inert package and advanced-object inventory |
| `pptx.outline.create` | Core Python | Versioned planning JSON; explicitly not a presentation |
| `pptx.create` | Core Python | Typed editable deck authoring with native text/shapes/tables/charts/images/equations, notes, themes, recipes, and template reuse |
| `pptx.create.from-markdown` | Core Python | Closed semantic Markdown subset through the typed emitter |
| `pptx.create.from-svg` | Core Python | Closed-profile local SVG to editable DrawingML with bounded element fallback; whole-slide raster forbidden |
| `pptx.create.from-template` | Core Python | Descriptor-bound semantic fill with page graph copy and private-content purge |
| `pptx.scene.export` | Core Python | Pinned Deck IR, constrained SVG, content-addressed assets, and source mapping in an atomic new directory |
| `pptx.template.inspect` | Core Python; optional provider contact sheet | Inert descriptor/slot/content-lint inspection without inferred writable selectors |
| `pptx.template.sanitize` | Core Python | Fail-closed external/OLE relationship removal and unreachable-part purge |
| `pptx.edit` | Core Python | Transactional slide, object, equation, deck-size, design-graph, and explicit inert `.pptm` keep-VBA edits |
| `pptx.create.from-html` | `html-browser` provider | Fixed-canvas local HTML scene capture using locked Playwright Core and an accepted system browser |
| `pptx.reconstruct.from-image` | `ocr-vision` provider; unavailable by default | Bounded PNG/JPEG to confident editable layers with smallest-region fallback and explicit audit policy |
| `pptx.render` | LibreOffice | Full-deck PDF, per-slide PNGs, and hash manifest in a distinct evidence ZIP |
| `pptx.convert.pdf` | LibreOffice | PDF conversion with source-slide/output-page correspondence |
| `pptx.convert.legacy` | LibreOffice | Bounded `.ppt` to `.pptx` semantic conversion without exact visual claim |
| `pptx.validate.schema` | .NET/OpenXML | Full OpenXML SDK schema report for an existing presentation |

## Safety and failure semantics

Every mutation is a transaction over a distinct destination. Immutable object/source hashes, package-graph validation, copy-through manifests, relationship/content-type checks, static layout gates, deep reopen, and optional callable schema/visual gates run before promotion.

HTML capture keeps the browser sandbox, tokenized loopback origin, script/service-worker disablement, and resource ceilings. Reconstruction requires a configured typed provider, separates area/count editability metrics, and never falls back to a hidden or uncropped whole-slide image. An unrun consumer stays `not_run`; provider crashes or unavailable adapters publish nothing.

## Verification

The [plugin test suite](../../../../tests/README.md) owns the public PPTX contract, operation, and security coverage. Exact focused and aggregate commands belong to the [producer verification guide](../../../../../scripts/README.md). Real PowerPoint, LibreOffice, browser, and OCR/vision evidence remains separate from deterministic Core tests and must report unavailable/crashed/not-run states literally.

## Related documentation

- [PPTX Skill and references](../../../../skills/document-pptx/SKILL.md)
- [PPTX ecosystem ADR](../../../../../docs/adr/0001-pptx-ecosystem-phase-bc-contract-and-operations.md)
- [Shared Core](../../README.md)
- [Providers](../../providers/README.md)
- [Private Node runtime](../../../../runtime/node/README.md)
- [Tests](../../../../tests/README.md)
