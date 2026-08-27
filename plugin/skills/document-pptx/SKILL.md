---
name: document-pptx
description: Plan, read, inspect, create, edit, export scenes, render, convert, and validate PPTX presentations through the bundled document core.
---

# PPTX presentations

Use this Skill for `.pptx` presentations, `.potx` template bases, explicit
`.pptm` keep-VBA edits, and explicit LibreOffice conversion of legacy `.ppt`.
The Core implementation reads, inspects,
creates, edits, and performs mandatory package validation through direct OOXML.
It does not depend on python-pptx or PptxGenJS. LibreOffice rendering and
.NET/OpenXML schema validation are optional, capability-gated enhancements.

## Commands

```text
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" doctor --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" capabilities --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" run --request request.json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" validate --input artifact.pptx --json
```

## Operations

| Operation | Mutation | Summary |
|---|---|---|
| `pptx.read` | no | Structured slide/shape/text-frame/table/chart/media/notes/layout projection |
| `pptx.inspect.structure` | no | Inert package inventory — parts, relationships, masters, layouts, themes, charts, media |
| `pptx.render` | yes (distinct `.zip` output) | LibreOffice-gated full-deck PDF plus one PNG per slide and a hash manifest |
| `pptx.convert.pdf` | yes (distinct `.pdf` output) | LibreOffice-gated PDF conversion with source-slide/output-page correspondence |
| `pptx.convert.legacy` | yes (distinct `.pptx` output) | LibreOffice-gated semantic conversion from bounded legacy `.ppt`; no exact source-visual claim |
| `pptx.validate.schema` | no | Provider-gated OpenXML SDK schema report for an existing `.pptx` |
| `pptx.outline.create` | yes (distinct `.json` output) | Versioned planning JSON that explicitly does not claim to be a presentation |
| `pptx.create` | yes (distinct output) | Styled deck with native text/shapes/tables, editable Office Math, real local raster images, editable native charts, notes, typed themes, seven layout recipes, and `.pptx`/`.potx` template reuse |
| `pptx.create.from-markdown` | yes (distinct output) | Bounded semantic reconstruction of local UTF-8 Markdown through the typed deck emitter |
| `pptx.create.from-html` | yes (distinct output) | Fixed 1920x1080 `.slide` HTML deck to editable native text/shapes/images with explicit element fallback |
| `pptx.create.from-svg` | yes (distinct `.pptx` output) | Closed-profile local SVG to editable DrawingML primitives/groups/text/table/chart/image objects; whole-slide raster is forbidden |
| `pptx.scene.export` | yes (new distinct directory) | Inert PPTX to pinned A-Contract Deck IR, constrained per-slide SVG, hash-bound assets, and source mapping |
| `pptx.template.sanitize` | yes (distinct `.pptx` output) | Inert fail-closed removal of external/OLE relationships plus unreachable-part purge and `.potx` identity downgrade |
| `pptx.template.inspect` | optional (distinct `.png` evidence) | Inert structural inventory, bounded content lint, descriptor-bound semantic slots, and optional provider-rendered contact sheet |
| `pptx.create.from-template` | yes (distinct `.pptx` output) | Descriptor-bound semantic fill, page selection/repetition/reorder, and physical purge of unselected private content |
| `pptx.edit` | yes (distinct output) | Transactional slide/object/equation/deck-size/design-graph edits plus explicit inert `.pptm` keep-VBA copy-through |

## HTML deck conversion

Probe `capabilities --json` and require the `pptx.create.from-html` operation's
`available` field to be `true` before promising a PPTX. The operation uses
exactly `playwright-core@1.62.1` with a supported system Chrome/Chromium/Edge;
it never downloads or bundles a browser. If unavailable, preserve the HTML and
state that no PPTX was created.

The fixed-canvas/local-asset contract, exact request, safe fallback policy, and
diagnostic interpretation are in
`references/html-to-editable-pptx.md`.

## Constrained SVG and scene bundles

Use `pptx.create.from-svg` only for an explicit 16:9 SVG viewport and the
closed editable profile. Native primitives, bounded paths/transforms, groups,
text/tspan, approved gradients, local bounded PNG/JPEG images, and typed
Elftia table/chart semantic groups enter the shared scene emitter. Script,
foreign namespaces, event handlers, external references, animation, and
resource bombs fail closed. Optional `element-rasterize` fallback requires an
explicit local fallback asset and can never cover the whole slide.

Use `pptx.scene.export` for an inert `.pptx` source only when the caller has the
pinned `@elftia/presentation-contracts@1.0.0` owner artifact. The output is a
new absent directory containing `manifest.json`, `deck-ir.json`, one constrained
SVG per slide, and content-addressed assets. `strict` rejects unsupported
objects; `tolerant` keeps stable source identity and opaque inventory without
claiming editability. Read `references/svg-and-scene.md` for exact requests,
supported semantics, directory publication rules, and result interpretation.

## LibreOffice rendering and conversion

Probe capabilities before promising `pptx.render`, `pptx.convert.pdf`, or
`pptx.convert.legacy`; all are exposed only when the LibreOffice provider is
callable. Read
`references/rendering.md` for their exact requests, bounded output formats, and
validation evidence. Provider absence returns `unavailable` and never creates
the requested output.

## Typed deck creation

For a `pptx.create` request containing images or charts, read
`references/typed-create.md`. Use a real bounded local PNG/JPEG/static GIF;
missing, mismatched, animated, or oversized images fail closed and never turn
into placeholders. Charts are native DrawingML chart objects with bounded
literal data caches, not pictures or empty references. The supported chart
types are bar, column, line, pie, and scatter.

For a custom palette/font system, recipe-driven layout, or template-as-base
request, read `references/typed-design.md`. Theme and layout tokens are closed
contracts: unsupported properties fail closed. A local `.pptx` or `.potx` template reuses
its master/layout/theme graph byte-for-byte and cannot be combined with new
`deck.theme` tokens or a different slide size.
For native editable Office Math in `pptx.create`, read
`references/editable-equations.md`. Equations accept only the documented LaTeX
subset or typed math AST; raw OMML/XML is never caller input.
For explicit master/layout/theme graph edits or template inheritance lint,
read `references/design-authoring.md`.

## Inert template sanitization

Use `pptx.template.sanitize` only with the fixed policy documented in
`references/template-sanitize.md`. The operation inventories package content
without dereferencing targets, rejects active content and signatures, removes
external/OLE/embedded relationships, converts cached chart references to
literal data when safe, and physically purges unreachable parts. A `.potx`
input is deliberately downgraded to an ordinary `.pptx` output. Missing chart
caches, ambiguous/dangling relationships, stale input hashes, or resource
limits fail without publishing output.

## Semantic template inspection and fill

Use `pptx.template.inspect` before semantic fill, then pass only returned
`source_slide_id`, `slot_id`, and `expected_hash` selectors to
`pptx.create.from-template`. Both operations consume the pinned A-Contract
template contract, semantic slots, and Deck IR; they never infer writable slots
from visual layout or expose shape/run ordinals. Read
`references/template-inspect-and-fill.md` for exact requests, supported binding
values, physical-purge evidence, license behavior, and contact-sheet provider
truth. Inspection always returns a read-only `content_lint` report for CJK
capacity, placeholder/ellipsis/promotional content, speaker-note leakage, and
type-scale hierarchy. Findings do not invent writable selectors; the same
error classes block template-output promotion.

## Outline and Markdown content entry

For planning JSON or Markdown reconstruction, read
`references/content-entry.md`. `pptx.outline.create` never emits a deck or
claims presentation success. `pptx.create.from-markdown` maps a closed Markdown
subset to the same typed emitter and mandatory validators as `pptx.create`; it
preserves content semantics, not source visual styling.

## Transactional editing

For slide or object edits, read `references/typed-edit.md`. Slide lifecycle
primitives add, delete, duplicate, copy, and move/reorder slides; cross-deck
copy carries the contained layout/master/theme/media/chart/notes dependency
graph. The separate deck-level `slide_size` primitive never scales content and
fails closed unless every final object boundary fits. Object selectors use
slide number plus stable shape id and/or exact name,
optionally narrowed by native type. `pptx.read` returns a reusable selector and
`precondition_sha256` for every projected top-level object.
Use `equation_upsert` to add an equation or replace one selected by the exact
`type: "equation"` selector returned by `pptx.read`; the request remains part of
the existing `pptx.edit` transaction. See `references/editable-equations.md`.

Every edit array is one transaction. All supplied preconditions are checked
against the original inputs before mutation, and any failure prevents output
publication. Hyperlinks are internal slide jumps only; actions are the closed
first/last/next/previous set and never execute external content.

## Advanced-object inventory

Use `pptx.inspect.structure` for inert discovery of SmartArt/diagram parts,
unsupported equation variants, audio/video, OLE, animations, transitions, and
comment metadata. Supported native Office Math is also projected by `pptx.read`.
Read `references/advanced-inventory.md` before interpreting these records. They
do not authorize playback, activation, execution, creation, or editing.

## Validation

Every create/edit route, including HTML conversion, must pass the deep Core
package gate before promotion. The standalone `validate --input ... --json`
command exposes the same check as `operation.pptx-deep-validation`. Its graph,
chart/workbook, inventory, and static-layout evidence is described in
`references/validation.md`.

Use `pptx.validate.schema` only after capabilities reports it available. This
read-only operation requires the `dotnet-openxml` provider. Provider absence is
reported as `unavailable`; schema errors produce `failed` with a required
`schema.full` gate. For create/edit operations, schema is optional while the
provider is absent, but becomes a required promotion gate when it is callable.

## Key policies

- **Distinct output:** All mutations require an explicit output path separate
  from the input. In-place mode is not supported.
- **Source preservation:** The input SHA-256 is recorded and verified after
  every operation. No mutation modifies the source.
- **Slide reorder preservation:** Reorder edits change only
  `ppt/presentation.xml` (sldIdLst order). Shape IDs, relationship IDs, layout
  references, master references, notes slides, themes, media, charts, and tables
  are preserved at the payload level. A structure-equality-on-reorder gate
  reopens the candidate and input and verifies every slide's content matches
  modulo order.
- **Run-aware editing:** Slide text edits preserve existing run formatting
  (font, size, bold/italic/underline, color, language) unless the request
  explicitly supplies a new style. Notes edits follow the same policy and do
  not affect the parent slide payload.
- **Object graph editing:** Image/chart add, replace, update, and delete mutate
  the slide XML, contained relationship, native part, content type, and any
  newly unreachable dependency graph together. Shape ids remain stable across
  updates and replacements.
- **Typed object evidence:** Successful typed creation reports each source
  image hash and embedded media part plus each chart part, chart type, native
  status, and data-storage mode under
  `diagnostics.operation_result.creation`. Read/inspect project chart series,
  literal values, axis ids/titles/number formats, and media parts back from the
  emitted package.
- **Editable equation boundary:** Equation blocks emit native Office Math, not
  OLE or whole-object images. Input is a bounded LaTeX subset or typed AST,
  `fallback` is currently only `reject`, and default PowerPoint/LibreOffice
  consumer states remain `not_run` until that consumer is actually exercised.
- **Copy-through preservation:** Every untargeted package part retains an
  identical payload SHA-256. Unknown safe parts, custom XML, media, charts,
  tables, slide masters, slide layouts, themes, notes masters, and notes slides
  are preserved.
- **Fail closed:** Malicious ZIP/XML, DDE, remote templates, executable
  relationships, and external targets are rejected. VBA is rejected by default;
  the sole mutation exception is the explicit `.pptm` keep-VBA policy in
  `references/typed-edit.md`. Use `pptx.inspect.structure` for inert inventory
  of suspicious `.pptx` or `.pptm` packages.
- **Sanitizer receipts:** Removed relationships expose only redacted type and
  target hashes, while removed parts include their original hashes. Core,
  schema, visual, LibreOffice, and PowerPoint states remain distinct; an
  unrun consumer is never reported as passed.
- **Semantic template selectors:** Public fill selectors are restricted to
  stable semantic slot ids plus exact precondition hashes. Strict descriptor or
  catalog drift fails before staging; tolerant inspection returns diagnostics
  without making inferred slots writable.
- **Physical template purge:** Page selection, repetition, and reorder reuse the
  validated slide graph copier. Unselected slides and their private notes,
  media, charts, embeddings, and comments are removed from the ZIP; shared
  reachable master/layout/theme dependencies remain.
- **Template content lint:** `pptx.template.inspect` reports content findings as
  an optional failed validation gate while preserving read-only inspection
  success. `pptx.create.from-template` treats error findings as required and
  publishes no output. There is no separate `pptx.template.lint` operation.
- **Scene bundle identity:** `pptx.scene.export` consumes the exact pinned
  A-Contract version/hash, assigns stable deck/slide/object ids, hashes every
  non-manifest member, and publishes the directory with atomic no-replace
  semantics. An existing directory, file, or broken symlink is never replaced.
- **SVG fallback boundary:** Whole-slide or near-whole-slide raster fallback is
  forbidden. Native/approximated/rasterized coverage and every SVG-node-to-PPTX
  mapping remain explicit under `diagnostics.operation_result`.
- **Visual validation:** It reports `unavailable` without LibreOffice and never
  becomes `pass` from structural or DOM evidence alone. `pptx.render` passes a
  required visual gate only after every slide PNG and the full-deck PDF reopen
  from the published evidence bundle.
- **Schema validation:** It reports `unavailable` without .NET/OpenXML. A
  callable provider must actually validate the candidate; provider failure or
  schema errors block promotion.

## Result interpretation

| Status | Meaning |
|---|---|
| `success` | All required Core gates passed |
| `degraded` | Required gates passed, but a disclosed semantic difference or optional capability gap remains |
| `invalid_request` | Operation arguments invalid; no file mutated |
| `failed` | A required gate failed; no output promoted |
| `unavailable` | Required provider/capability unavailable; no output created |

Slide-structure evidence, edit counts, preservation manifests, lifecycle copy
manifests, reorder evidence, and per-object before/after hashes appear under
`diagnostics.operation_result`.
