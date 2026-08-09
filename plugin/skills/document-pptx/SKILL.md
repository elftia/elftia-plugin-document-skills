---
name: document-pptx
description: Read, inspect, create, edit, and validate PPTX presentations through the bundled document core.
---

# PPTX presentations

Use this Skill for `.pptx` requests. The Core implementation reads, inspects,
creates, edits, and validates PPTX packages through direct OOXML — no
python-pptx, PptxGenJS, LibreOffice, or .NET round-trip.

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
| `pptx.create` | yes (distinct output) | Styled deck from typed data — slides, shapes, table, chart reference, image reference, notes, ≥2 layouts |
| `pptx.create.from-html` | yes (distinct output) | Fixed 1920x1080 `.slide` HTML deck to editable native text/shapes/images with explicit element fallback |
| `pptx.edit` | yes (distinct output) | Slide text, slide reorder/move, notes edits with run-aware preservation |

## HTML deck conversion

Probe `capabilities --json` and require the `pptx.create.from-html` operation's
`available` field to be `true` before promising a PPTX. The operation uses
exactly `playwright-core@1.62.1` with a supported system Chrome/Chromium/Edge;
it never downloads or bundles a browser. If unavailable, preserve the HTML and
state that no PPTX was created.

The fixed-canvas/local-asset contract, exact request, safe fallback policy, and
diagnostic interpretation are in
`references/html-to-editable-pptx.md`.

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
- **Copy-through preservation:** Every untargeted package part retains an
  identical payload SHA-256. Unknown safe parts, custom XML, media, charts,
  tables, slide masters, slide layouts, themes, notes masters, and notes slides
  are preserved.
- **Fail closed:** Malicious ZIP/XML, active content (VBA, DDE, remote
  templates, executable relationships), and external targets are rejected under
  the normal policy. Use `pptx.inspect.structure` for inert inventory of
  suspicious packages.
- **Visual/render/schema validation:** These gates report `unavailable` without
  LibreOffice/.NET. They never become `pass` or increase fidelity.

## Result interpretation

| Status | Meaning |
|---|---|
| `success` | All required Core gates passed |
| `degraded` | Core succeeded; optional capability unavailable |
| `invalid_request` | Operation arguments invalid; no file mutated |
| `failed` | A required gate failed; no output promoted |
| `unavailable` | Required provider/capability unavailable; no output created |

Slide-structure evidence, edit counts, preservation manifests, and reorder
evidence appear under `diagnostics.operation_result`.
