---
name: document-pptx
description: Plan, read, inspect, create, edit, render, convert, and validate PPTX presentations through the bundled document core.
---

# PPTX presentations

Use this Skill for `.pptx` presentations, `.potx` template bases, and explicit
`.pptm` keep-VBA edits. The Core implementation reads, inspects,
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
| `pptx.validate.schema` | no | Provider-gated OpenXML SDK schema report for an existing `.pptx` |
| `pptx.outline.create` | yes (distinct `.json` output) | Versioned planning JSON that explicitly does not claim to be a presentation |
| `pptx.create` | yes (distinct output) | Styled deck with native text/shapes/tables, real local raster images, editable native charts, notes, typed themes, seven layout recipes, and `.pptx`/`.potx` template reuse |
| `pptx.create.from-markdown` | yes (distinct output) | Bounded semantic reconstruction of local UTF-8 Markdown through the typed deck emitter |
| `pptx.create.from-html` | yes (distinct output) | Fixed 1920x1080 `.slide` HTML deck to editable native text/shapes/images with explicit element fallback |
| `pptx.edit` | yes (distinct output) | Transactional slide/object edits plus explicit inert `.pptm` keep-VBA copy-through |

## HTML deck conversion

Probe `capabilities --json` and require the `pptx.create.from-html` operation's
`available` field to be `true` before promising a PPTX. The operation uses
exactly `playwright-core@1.62.1` with a supported system Chrome/Chromium/Edge;
it never downloads or bundles a browser. If unavailable, preserve the HTML and
state that no PPTX was created.

The fixed-canvas/local-asset contract, exact request, safe fallback policy, and
diagnostic interpretation are in
`references/html-to-editable-pptx.md`.

## LibreOffice rendering and PDF conversion

Probe capabilities before promising `pptx.render` or `pptx.convert.pdf`; both
are exposed only when the `libreoffice` provider is callable. Read
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
graph. Object selectors use slide number plus stable shape id and/or exact name,
optionally narrowed by native type. `pptx.read` returns a reusable selector and
`precondition_sha256` for every projected top-level object.

Every edit array is one transaction. All supplied preconditions are checked
against the original inputs before mutation, and any failure prevents output
publication. Hyperlinks are internal slide jumps only; actions are the closed
first/last/next/previous set and never execute external content.

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
- **Copy-through preservation:** Every untargeted package part retains an
  identical payload SHA-256. Unknown safe parts, custom XML, media, charts,
  tables, slide masters, slide layouts, themes, notes masters, and notes slides
  are preserved.
- **Fail closed:** Malicious ZIP/XML, DDE, remote templates, executable
  relationships, and external targets are rejected. VBA is rejected by default;
  the sole mutation exception is the explicit `.pptm` keep-VBA policy in
  `references/typed-edit.md`. Use `pptx.inspect.structure` for inert inventory
  of suspicious `.pptx` or `.pptm` packages.
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
| `degraded` | Core succeeded; optional capability unavailable |
| `invalid_request` | Operation arguments invalid; no file mutated |
| `failed` | A required gate failed; no output promoted |
| `unavailable` | Required provider/capability unavailable; no output created |

Slide-structure evidence, edit counts, preservation manifests, lifecycle copy
manifests, reorder evidence, and per-object before/after hashes appear under
`diagnostics.operation_result`.
