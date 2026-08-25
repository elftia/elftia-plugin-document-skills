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
| `pdf.create` | yes | One-or-more-page PDF with requested Latin/CJK/RTL text, embedded local TrueType subsets, PNG/JPEG images, tables, styled text, and styled vector shapes |
| `pdf.edit` | yes | Atomic bounded primitive lists: form-aware merge/split/page sequencing/hash-bound insertion, rotate, flat outline and safe Text-annotation add/update/delete, styled/positioned opacity-aware text/image watermark, and AcroForm text/checkbox/radio/choice fill with appearances and safe text/choice flatten |
| `pdf.rewrite.apply` | yes | Hash-bound block rewrite with required source/text/bbox/page preconditions and page-layout preservation; CJK/RTL requires an explicit hash-bound font style |
| `pdf.images.extract` | no | Extract Image XObjects invoked directly or through bounded Form XObjects, plus raw/FlateDecode 8-bit Gray/RGB inline images, to an atomic deterministic `.zip`; copies JPEG and rebuilds PNG, including compatible soft-mask alpha |
| `pdf.table.extract` | no | Bounded axis-aligned ruling-line lattice extraction with real page/cell bboxes and rectangular row/column spans, plus an explicit low-confidence text heuristic fallback |
| `pdf.encrypt` | yes | pypdf-backed AES-256-R5 encryption with distinct user/owner passwords, explicit permissions, and encrypted metadata |
| `pdf.decrypt` | yes | Explicit password-gated decryption; ordinary `pdf.read` and Core `pdf.edit` remain fail-closed for encrypted input |
| `pdf.compress` | yes | Evidence-backed lossless or bounded balanced/aggressive image optimization; publishes only when output bytes shrink and required semantics/quality gates pass |
| `pdf.render` | yes | Optional supported-version Poppler page rasterization to a bounded deterministic PNG/JPEG ZIP; unavailable when the Poppler page renderer is not callable or outside policy |
| `pdf.ocr` | yes | Optional supported-version Poppler + Tesseract OCR to bounded text/JSON sidecars with language, confidence, and pixel bboxes; unavailable unless both tools and the requested language packs are callable |

The canonical callable `pdf.create` smoke request is
[create-minimal.json](assets/examples/create-minimal.json). Replace its output
placeholder with a local `.pdf` path before running it.
The hash-bound CJK/RTL font example is
[create-unicode.json](assets/examples/create-unicode.json); replace both font paths,
both complete SHA-256 placeholders, and the output path before running it.
The matching source-bound rewrite template is
[rewrite-unicode.json](assets/examples/rewrite-unicode.json); populate its source
SHA-256 and copy the selected block's current page/text/bbox from `pdf.read`.
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

Core creation accepts an explicit `document.fonts` registry of local `.ttf` files bound
to complete SHA-256 digests. A text style selects an exact face with `font_family`, may
list `fallback_fonts`, and may set `direction: auto|ltr|rtl` plus a bounded language tag.
The runtime rejects URLs, collections/CFF/WOFF, unstable or oversized files, excessive
glyph counts, and embedding-restricted or no-subsetting license flags. It instantiates
variable fonts at their declared defaults, creates deterministic subsets, shapes complex
scripts with HarfBuzz, resolves bidi levels, and emits Type0/CIDFontType2 resources with
CIDToGIDMap, ToUnicode, and logical-order ActualText. There is no system-font discovery.

Every visible codepoint must be covered by the selected face or its ordered fallback
chain. Missing glyphs return `enhancement_required` with exact `character` and `U+...`
records before publication; the implementation never emits `.notdef`, replacement
glyphs, or handwritten RTL reversal.

Unicode `pdf.rewrite.apply` uses the same `fonts` registry. Each Unicode rewrite must
include an embedded-font `style`; every rewrite request must bind the current input with a
complete 64-hex `source_sha256`. The digest is checked before any candidate is written, and
the source is checked again while it is parsed and before promotion. The selected
source block's page, logical text, and bbox are checked against the current document,
then bound to an exact content-object and text-showing-operator index. Literal and hex
`Tj` operands and bounded `TJ` arrays are rewritten without selecting an earlier duplicate;
the candidate is reopened to verify the requested replacement plus every non-target
text-showing operator, page box, and resource dictionary. Plain and single `FlateDecode`
content streams are supported;
other filter chains remain `enhancement_required`. Replacement text wraps into the
caller-selected bbox and fails if its complete multiline height cannot fit. Mixed
Latin/Unicode transactions use the embedded-font path atomically when every rewrite has
an explicit covered style. A stale/ambiguous selector, missing font, or replacement that
cannot fit fails without publication. Legacy Latin-1-only rewrites remain available
without a font registry.

## Images, layout, and edit transactions

Creation and image watermarking accept only local PNG/JPEG assets with a required complete
`sha256`, verify the caller-bound bytes and bounds, and emit real Image XObjects.
Creation images with a non-empty `alt` are emitted as tagged `Figure` marked content:
per-page MCIDs and `StructParents` are bound through the catalog `StructTreeRoot` and
`ParentTree` to a Unicode `/Alt`, the exact page, Image XObject, and visible bbox. Images
without alt text do not acquire fabricated structure entries. The promotion gate reopens
and verifies every association before publication.
Page-specific size/margins, Helvetica weight/style/size/color,
line-height/alignment/wrapping, and vector stroke/fill/opacity/dash are effective PDF
operators. Overflow fails without publishing the destination by default. A page may
explicitly set `overflow_policy: paginate` plus bounded `widow_lines` and `orphan_lines`.
Core then paginates headings and paragraphs while enforcing both line minima, moves a
fixed-height image or non-splittable table to the next page when needed, and splits a
repeat-header table across bounded continuation pages. A fixed block taller than the
whole content box fails atomically. Absolute vector shapes stay on the page reached in
block order and do not consume vertical flow height.

`document.design_tokens` is the typed default layer for page size, four-sided margins,
bounded named RGB palette colors, heading/paragraph/table typography, and per-block-type
spacing. Explicit block styles override typography defaults, while color-bearing styles,
tables, and vector shapes may reference a declared palette token. Tokens are normalized
into the same validated document model and creation evidence; there is no template-only
emission path.

Created tables support explicit/equal column widths, wrapped Latin/Unicode cell text,
minimum row heights, padding, border width/color, table/row/cell/header fills, and
table/cell text alignment. Unicode cells use the table block's explicit embedded-font
style and the same glyph coverage checks as paragraphs. A table with
`repeat_header: true` and one or more `header_rows` is split across bounded continuation
pages and repeats its header, including when mixed with other flow blocks under the
explicit pagination policy. A table without repeat headers moves intact when it fits a
fresh page and otherwise fails instead of splitting rows or overlapping content.
Vector shapes support line, rectangle, rounded rectangle (with corner radius), and
ellipse paths plus stroke/fill/opacity/dash.

Image extraction supports Image XObjects invoked by page content or bounded nested Form
XObjects. Form resource scopes and matrices are composed into each page bbox; recursive or
over-depth Form graphs fail closed. It reports page, object, resource path, bbox, dimensions,
filter/color metadata, byte count, and SHA-256 for each ZIP entry. Count, decoded-pixel,
sample-byte, and output-byte budgets are shared across pages, nested Forms, XObjects, and
inline images and are reserved before the next decode. ZIP promotion reopens each payload;
PNG/JPEG format, dimensions, completeness, hashes, and aggregate budgets are independently
rechecked with bounded Pillow decoding. Matching 8-bit TIFF horizontal and PNG row predictors are
reversed within the pixel bounds. A DeviceGray/RGB JPEG with a compatible 8-bit soft mask
is decoded through locked Pillow and emitted as RGBA PNG; JPEG without alpha remains an
unchanged codestream. Raw or single-FlateDecode 8-bit DeviceGray/DeviceRGB inline images are
bounded by exact decoded sample length and emitted as PNG with `source: inline` and their
effective draw bbox. Predictor-encoded, other-filter, masked, non-8-bit, or other-color-space inline images, plus
non-Gray/RGB lossless XObjects, mismatched predictor parameters, and other mask/filter
chains return `enhancement_required`; they are never reported as extracted.

`pdf.edit.primitives` is an ordered bounded transaction. A failure in any primitive
publishes none of the earlier staged edits. Each primitive is preflighted against the current
staged page/object model and declares its permitted changed/added/removed objects before it
writes. Observed differences cannot expand that permission set. Before promotion, a required
composite semantic gate reopens the final candidate and checks page sequencing/rotation,
watermark resources/operators, form values/appearances/widget graph, safe Text annotations,
and redaction evidence. Watermark opacity is an effective ExtGState;
text watermarks apply one of the closed PDF Base-14 Helvetica, Times, or Courier
normal/bold/italic variants plus size/color/rotation and named or x/y positions. Each
target page receives a collision-free dedicated font resource that is reopened and
verified against the requested `/BaseFont`; image
watermarks are real Image XObjects with contain/stretch placement, rotation, and named
or x/y positions. Target pages safely clone indirect or inherited resource dictionaries.
Rotated `cover` clipping remains `enhancement_required`. AcroForm fill supports text, checkbox, radio,
and choice values, validates appearance/option states, updates `/V`, `/AS`, and `/AP`,
and sets `NeedAppearances` false. Indirect nested field trees are traversed with inherited
`/FT` and `/Ff`, qualified dotted names, and separate terminal widgets; read and fill use
the same resolved graph. Form fill rejects requested ReadOnly fields as `invalid_request`;
any AcroForm containing `/XFA` returns `enhancement_required` before candidate output is
written. Text/choice flatten merges visible text into every selected widget's
page content, removes its annotations, and prunes empty nested field ancestors while preserving
unrequested siblings. Checkbox/radio flatten paints each effective resource-free normal `/AP`
state through its BBox-to-Rect transform before removing the widget/field graph. Button
appearances with resources or non-identity matrices remain `enhancement_required`.

Flat destination-based outlines support add, 1-based-index update, and delete. Update
and delete accept an `expected_title` precondition. Nested outline trees and action-based
bookmarks remain inert on read and return `enhancement_required` on edit.

Annotation editing is limited to indirect, action-free `/Text` annotations in direct
page `/Annots` arrays. It supports add plus page-local 1-based-index update/delete with
an `expected_contents` precondition. Delete scans the parsed object graph before writing
and requires exactly one inbound reference: the selected page's current `/Annots` entry.
Replies (`/IRT`), Popup parent links, duplicate `/Annots` entries, and references from any
other owner return `enhancement_required` without publication. Update preserves the
annotation object number. Widget, Link, attachment, inline, action-bearing, and
indirect-array annotation graphs remain inventory-only or `enhancement_required`.

Page sequence editing accepts a unique ordered list of existing source pages, covering
bounded extract/reorder/delete while preserving the selected page objects. Hash-bound page
insertion accepts a local PDF, required `source_sha256`, a destination `at` position, and an
optional unique ordered source-page list. It preserves each inserted page's box, rotation,
resources, content, and page annotations while rebuilding a bounded flat page tree. Either
operation reconciles flat page labels to the exact visible labels of the selected pages;
unlabeled pages receive their original default numeric labels when combined with a labeled
document. Page sequence also drops flat `/Fit` outlines targeting removed pages and
retargets retained outline destinations to the new order. Page insertion merges destination
and inserted flat outline lists at the insertion boundary and retargets both sets. Both
operations retain indirect widgets on selected pages, prune their field ancestors and `/Kids`,
and rebuild one compatible `/AcroForm`; merge and split use the same reconciliation. Duplicate
qualified names, XFA/signatures/calculation graphs, direct fields, mixed widget/field Kids, and
conflicting defaults/resources remain `enhancement_required`. Nested or action-based outlines
remain unsupported. Page-label set supports decimal, Roman, alphabetic, and
prefix-only flat `/Nums` ranges; clear removes a flat label tree. Nested `/Kids` trees
remain `enhancement_required`. Page-tree reconstruction preserves safe ordinary Catalog
entries and their bounded object closure, but tagged structure trees, Names/Dests trees,
collections, permissions, document requirements, and attachment/thread graphs currently
return `enhancement_required` with capability `pdf.page-tree-catalog-reconciliation` rather
than being dropped or mislabeled as unsafe. This includes page operations on PDFs created
with image-alt tagging until structure-tree reconciliation is implemented.

Merge accepts 2-10 entries shaped as `{input, source_sha256}`. The first entry must resolve to
the top-level `pdf.edit.input`; every entry is byte-preflighted, caller-hash checked, and checked
again for source preservation before and after candidate promotion. Relative merge paths are
resolved from the public command invocation directory before the isolated worker starts.

`redact_text` is deliberately narrow true removal: it only accepts a unique Latin-1 literal
`Tj` operand in an unfiltered, non-shared content stream, replaces the operand with `()`, and
reopens the candidate to prove both extracted text and literal source bytes are absent.
Ambiguous, encoded, filtered, shared-stream, image, and non-`Tj` redaction requests are
rejected rather than covered with a black rectangle.

## Encryption, decryption, and compression

The accepted pypdf provider is pinned to `6.16.2` with the locked cryptography runtime.
`pdf.encrypt` accepts only `AES-256-R5`; RC4, AES-128, AES-256-R6, and unencrypted-metadata
requests remain `enhancement_required`. Passwords are bounded UTF-8 values accepted only in
the request's top-level `secrets` object, never in ordinary `arguments`, and never appear in
argv, provider results, diagnostics, or error messages. Keep request JSON files private because
they contain caller-supplied secrets. Successful encrypt/decrypt results declare
`output_version: "1.7"`, matching the emitted `%PDF-1.7` header.

`pdf.decrypt` accepts either the user or owner password and produces an unencrypted distinct
PDF only after page/text semantics round-trip. A wrong password preserves both source and any
existing destination. `pdf.compress` accepts `lossless`, `balanced`, and `aggressive`.
Lossless recompresses content streams and removes duplicate/unreferenced objects. Balanced and
aggressive additionally recompress compatible indirect, non-alpha Image XObjects with locked
Pillow policies (quality 82/max 1920/PSNR 24 dB or quality 60/max 1280/PSNR 18 dB). Results
record independently reopened before/after object, stream, duplicate, metadata, image,
object-stream, and xref-stream counts/bytes plus changed object identifiers. Object-stream and
xref-stream conversion are truthfully reported as unsupported/not-attempted. Lossless gates
also bind MediaBox/CropBox/rotation, Info/XMP metadata, resources, decoded content, and image
identity. Lossy results record per-image dimensions, decoded-pixel error, PSNR, skipped images,
and byte savings recomputed from the final artifact.
This is image-level visual evidence, not full-page rendering. Inline/alpha images, absent
compatible images, quality failure, or non-positive byte savings preserve the destination.

## Render, OCR, and table confidence

Never invoke Poppler or Tesseract directly. `pdf.render` and `pdf.ocr` are registered only
through callable provider implementations and capability detection runs real bounded version
probes. On a Core-only machine they remain present but `available: false`; a request returns
`unavailable` without an output. Development-only PyMuPDF/Pillow installations are not
production provider evidence.

Each successful `pdf.render` page result and manifest entry binds the parsed MediaBox,
effective CropBox, normalized right-angle rotation, DPI, actual raster width/height, and a
zero-origin raster bbox to the expected extent. The raster must exactly match the extent
independently calculated from the effective PDF page box, rotation, and DPI; otherwise the
provider fails closed. Before promotion, `render.page-semantics` reopens the ZIP, reparses the
source using the originally accepted page selection, decodes every generated image, and
recomputes the geometry, hashes, bbox bounds, and `overflow: false` evidence instead of
trusting a self-consistent manifest.

`pdf.render` can optionally compare every selected full-page raster with a local reference
PDF. The reference must be bound by its complete SHA-256 before either document is rendered.
The caller supplies a per-channel tolerance, expected PDF-coordinate regions, and aggregate
minimum-expected/maximum-unexpected changed-pixel ratios. Both PDFs are safety-preflighted
and preserved, the deterministic manifest records page and aggregate evidence, and
`visual.page-render-diff` is a required validation gate. Expected regions are mapped from
MediaBox/CropBox PDF coordinates through 0/90/180/270-degree page rotation into raster
coordinates; malformed non-right-angle rotation remains `enhancement_required`. A policy
miss publishes no ZIP. Poppler performs both page
renders, while locked Pillow only measures the decoded raster difference and does not make
an unavailable Poppler capability appear available.

The optional-tool detector accepts Poppler 23.1.x through 26.x and Tesseract 5.3.x
through 5.x, records both executable paths/versions, and requires Tesseract's `eng`
language pack before advertising OCR. Every OCR request is checked against the probed
language inventory. Render selects at most 256 pages and OCR at most 64; they use fixed
120/300-second whole-operation deadlines in addition to per-process timeouts. Tool output
is size-checked before a bounded read, and selected pages with non-default `/UserUnit`
return `enhancement_required` because the pixel estimate has not been validated for that
coordinate scaling.

The render contract defaults to 144 DPI and accepts 36 through 300 DPI; OCR defaults to
300 DPI and accepts 72 through 300 DPI. For either operation, `max_pixels` is the cumulative
selected-page raster budget: it defaults to 40,000,000 pixels and may be caller-lowered or
raised no higher than 100,000,000 pixels. `max_total_bytes` defaults to 64 MiB and may be
caller-lowered or raised no higher than 128 MiB. Render applies the byte budget to produced
image payloads (and separately to the reference side of a comparison); OCR applies it across
its cumulative raster, TSV, and sidecar working bytes. OCR accepts one through eight distinct
installed Tesseract language IDs, each matching `[A-Za-z0-9_]{2,16}`, and accepts at most
100,000 parsed word records per OCR-processed page.

Every OCR raster is bound to the selected source page's MediaBox/effective CropBox,
right-angle rotation, DPI, and independently calculated pixel extent before Tesseract runs.
Every word bbox must have positive area and remain inside that raster. Before promotion,
`ocr.page-semantics` reparses the original page selection and reopens JSON/text sidecars to
recheck page ordering, geometry, languages, word evidence, and derived text; a self-consistent
but source-unbound archive is rejected.

Poppler and Tesseract remain host-supplied optional tools. They are not downloaded or
included in the package SBOM. The runtime bounds above do not provide an operating-system
CPU, memory, or disk quota while the native process is running, so a provider profile is
not release-ready until the deployment supplies sandbox/resource controls, exact
platform/version smoke evidence, and an independently reviewed host-runtime inventory.
The executable-free provider tests use a fake runner and therefore are not real Poppler or
platform smoke evidence.

### Executable provider profiles

Repository CI and deployment verification use an operator-only provider-profile harness
through the frozen environment. It is not an agent-facing command; document agents continue
to use only this Skill's public façade. The harness profiles are `core-only`, `render`,
`ocr`, and `full`.

`core-only` runs real public create, edit, rewrite, and form-fill smokes while giving the
isolated workers an explicit empty external-tool PATH; its receipt must show both render and
OCR unavailable. The other profiles first consume the real public capability report and run
their public smoke only when the required accepted provider and binding are callable. A
missing binary, unsupported version, or missing `eng` language pack produces a machine-readable
`unavailable` receipt, never `pass`. The `full` profile does not short-circuit at the first
missing optional executable: it still runs every available public pypdf
encrypt/decrypt/compress smoke and records those passes, while the overall receipt remains
`unavailable` when render or OCR is unavailable. Provider crashes, timeouts, or malformed
outputs remain `failed`, not partial availability. Add `--strict` on a runner where that profile is required
to make unavailable non-zero. A successful local receipt records evidence for that execution
only; it is not a substitute for CI receipts, host sandbox/quota evidence, or independent
release review.

`pdf.table.extract` reports `core-lattice` at confidence `0.9` only for bounded connected grids
formed by axis-aligned stroked `m/l/h` paths under translation/scaling transforms. It returns
real table/row/cell PDF bboxes and rectangular `row_span`/`column_span` values when internal
rulings are absent. Rectangle operators, curves, fill-only rules, rotated/skewed paths,
non-rectangular merges, and text outside detected grids fall back to the approximate
`core-stream-heuristic` capped at `0.4`; mixed results say `mixed`. OCR tables are not inferred.
Adjacent page tables merge only when source, repeated header text, and column anchors match;
the result records explicit continuation-page evidence.

`pdf.read` keeps raw object/resource inventory separate from semantic text selection. Callers
may select an ordered page list and an intersecting bbox, then choose content-stream,
top-to-bottom geometric, or explicit bounded multi-column reading order. Every projected text
block carries its resulting order index and the result records the selection policy.

## Page-level preservation (edit)

Copy-through edit primitives compare untargeted object hashes and report their changed object
sets. Page-list operations rebuild and renumber bounded graphs, so object numbers and payload
bytes can change; their preservation evidence is a normalized old-to-new mapping rather than a
claim of byte-identical output objects.

Every successful single-primitive result, every item in a multi-primitive result's
`primitives` array, and the aggregate multi-primitive result expose sorted unique
`changed_objects`, `added_objects`, and `removed_objects` copied from the exact preservation
manifest used by validation. Each also exposes `page_impact` with its mode, source/output page
counts, and separately numbered source/output page lists. Content mutations derive those lists
from the changed object graph; page-tree operations report the complete before/after page sets.
Document metadata and outline navigation use explicit non-content modes with empty page lists,
while page-label edits explicitly report every labeled page.

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
