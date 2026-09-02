---
name: document-docx
description: Read, inspect accessibility and structure, create, edit, template, merge, review, validate, render, and explicitly convert Word documents through the bundled frozen uv/Python surface.
---

# DOCX documents

Use this Skill for `.docx` work, inert `.dotx` template input, inert `.docm` inventory/explicit
keep-VBA editing, and provider-backed legacy `.doc` conversion. Core operations include:

- `docx.read` — deterministic headings, paragraphs, lists, tables, hyperlinks, images,
  headers/footers, and section metadata. Content created from a `document_spec` also projects
  its stable `node_id` and semantic `node_type` on the corresponding paragraphs, tables, and
  images.
- `docx.inspect.structure` — inert package, relationship, feature, and dangerous-content
  inventory; it never authorizes mutation.
- `docx.inspect.accessibility` — bounded inert checks for missing image alternative text,
  skipped body-heading levels, unmarked table header rows, and absent document-level language
  metadata. Findings request review but never modify the source.
- `docx.create` — either a versioned, source-neutral `document_spec` or the compatible legacy
  `report` contract. The semantic plan supports reusable style profiles, hash-bound template style
  mappings, academic/technical domain profiles, stable front matter, captions, editable linear
  OMML, structured citations/bibliography, bookmarks, and restricted cross-reference fields.
  Both contracts create exactly the requested content, with opt-in header, footer, sections, and
  metadata.
- `docx.edit` — typed top-level body paragraph insert/delete plus paragraph/complete-run formatting
  across public body, table-cell, header, and footer story paragraphs. Local raster insert/replace
  and bounded table insert/cell/row/merge/split edits are guarded by immutable input text,
  story-part, image-relationship, or table-subtree preconditions. Section paper,
  orientation, margins, break type, and isolated default/first/even header/footer stories use
  section/story hashes from the same public read surface. Bounded paragraph bookmarks and
  bookmark-targeted internal hyperlinks can be inserted or updated without external relationships.
  It also supports safe fields/TOC dirty markers, footnotes/endnotes, simple unlocked content
  controls, custom paragraph styles, and existing multilevel-numbering instances.
- `docx.edit.replace-text` — exact run-aware replacement across body, tables, referenced
  headers, and referenced footers.
- `docx.template.apply` — bounded scalar `{identifier}` substitution over a `.docx` or inert
  `.dotx` base, including placeholders split across formatting runs. Restricted declarative
  top-level body paragraph regions support explicit item repetition and literal-boolean inclusion;
  they do not add loop markers, expressions, raw XML, or caller code. An optional explicit style
  overlay imports only named styles with `keep-base|replace-existing`; output is always `.docx`.
- `docx.template.pack.list` / `docx.template.pack.read` — deterministic built-in catalog and
  exact hash-bound local pack inspection. The runtime never scans user directories or selects a
  different/latest version implicitly.
- `docx.template.import.inspect` / `docx.template.import.create` — read-only safety/style/control
  inspection followed by explicit, canonical, immutable local pack creation. Imports preserve the
  safe `.docx/.dotx` payload byte-for-byte, require explicit semantic mappings, record provenance
  and license status, and publish an absent directory atomically. A degraded `document-spec`
  inspection with material formatting requires a source-matching `authoring_format`; missing,
  invented, conflicting, nonuniform, or lossy mappings fail closed before publication.
- `docx.template.pack.instantiate` — one declared `template` or `document-spec` mode. Template mode
  reuses the existing scalar/region engine; document-spec mode rejects caller `style_profile` and
  injects the pack-owned hash-bound `template-mapped` role mapping.
- `docx.merge` — compatible high-fidelity `.docx` graph merge. It copies body XML, tables,
  sections, referenced headers/footers, and media without text extraction or reconstruction,
  deterministically remaps relationship/drawing/part ids, bookmarks, internal links, styles, and
  numbering, and preserves the closed safe Word field vocabulary plus simple unlocked text content
  controls. Self-contained footnotes/endnotes are copied with deterministic note-id remapping.
  Classic self-contained comments copy their range/reference/definition graph with deterministic
  comment-id remapping. Inline tracked insertions/deletions preserve their complete subtree and
  receive collision-free revision ids, including inside nested tables. Complete paired move graphs
  additionally remap wrapper ids, range ids, and colliding move names as one unit. Theme and
  font-table semantic parts must remain identical across every source.
- `docx.compare.semantic` — read-only stable-ID comparison of a `document_spec` with an output, or
  a hash-bound baseline with an after document. It separates missing, unexpected, changed,
  allowed, and degraded evidence and returns structural/preservation evidence for before/after.

Optional callable providers add these public operations without changing the Skill entry point:

- `.NET/OpenXML`: `docx.revisions.read`, `docx.revisions.apply`, `docx.comments.read`,
  `docx.comments.add`, `docx.comments.resolve`, and `docx.validate.schema`.
- LibreOffice: explicit `.doc` conversion through `docx.convert.legacy`, `docx.convert.pdf`,
  bounded PDF/optional per-page PNG evidence and layout findings through `docx.render`, a bounded
  semantic-node layout repair loop through `docx.layout.repair`, and fixed-profile reference
  comparison through `docx.compare.visual`.

Provider helpers and their private operation names are never Agent-facing. Check
`capabilities --json`; an optional operation is advertised only when its accepted provider is
callable.

`docx.create` never adds content of its own. Prefer `document_spec` for new agent-authored
documents because it separates semantic nodes and reusable resources from any source syntax;
Markdown is only a possible upstream adapter. The older `report` input remains supported for
compatibility. A request listing only paragraphs produces only those paragraphs — no placeholder
image, filler table, or empty running head.

Template Engine, Document Spec, Style Profile, and Domain Profile are separate layers. The built-in
`professional-generic` style profile and hash-bound `template-mapped` role mapping are reusable;
`academic-paper` is the first domain recipe, not the template abstraction. `technical-report`
proves the emitter has no academic branch. Mammoth 1.12.1 was evaluated as a lossy HTML adapter and
not adopted; native OOXML remains the preservation, security, and comparison authority.

Before relying on an operation, check its callable capability. All executable examples use the
same bundled Python façade:

```text
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" doctor --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" capabilities --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" run --request request.json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" validate --input artifact.docx --json
```

Never replace `<project-root>` with another Python environment. Node is an internal template
backend selected by Python; do not invoke it or any provider directly.

## Safe workflow

1. Preserve the input. Every mutation requires an explicit, distinct output path; aliases and
   in-place requests are rejected.
2. Use `docx.inspect.structure` when normal read rejects active/external content. Inspection is
   inert: it does not fetch, execute, enable, rewrite, sanitize, or make the package safe.
   Use `docx.inspect.accessibility` only on a normally readable `.docx`; it reports semantic
   authoring issues and does not claim WCAG certification or visual equivalence.
3. For replacement, matches may span formatting runs within one eligible paragraph. Inserted
   text inherits the first affected run. Matches never cross hyperlinks, paragraphs, cells,
   fields, revisions, comments, content controls, drawings, tabs, or breaks.
4. For paragraph insertion/deletion and image insertion, select a top-level body paragraph by its
   public read index and exact expected text. Paragraph/run formatting may also select a body table
   cell or referenced header/footer paragraph by its exact public story `part`, paragraph index,
   and expected text. Run-style text may span complete eligible runs but cannot split a run.
   Image replacement additionally binds the public relationship id and alt text from
   `docx.read` to the media SHA-256 from inert inspection; it never overwrites the old media part.
   Table mutations use the table's `selector_sha256` from `docx.read`; never invent an OOXML table
   or cell index.
   Section and header/footer mutations likewise use the section `selector_sha256`; updating one
   section allocates a new story part instead of rewriting a header/footer shared by other sections.
   Bookmark and hyperlink edits use the same immutable paragraph selector. Core accepts only
   paragraph-range ASCII Word bookmarks and simple internal bookmark links; external links remain
   unsupported because normal mutation rejects external relationships.
5. For templates, use only scalar ASCII/dot identifiers. Missing variables block output; unused
   variables are warnings. Repeating regions bind a top-level body paragraph by its public index
   and exact text, then require every item to match that paragraph's token set exactly. Conditions
   accept only a literal boolean `include`; no expression is evaluated. A `.dotx` input is admitted
   only for this operation and only when its
   sole template marker is the standard main content type; attached templates, macros, external
   relationships, template marker loops/conditions, raw XML, expressions, and caller-supplied
   parser code are rejected. Style overlays require an exact source hash and named style ids, preserve every
   unselected base style, and reject graph-dependent numbering or relationship-bound style XML.
   The promoted output is a `.docx`.
   For reusable reference formatting, list/read a built-in pack or inspect a hash-bound local
   `.docx/.dotx` before import. Candidate role mappings are advisory until supplied explicitly to
   `docx.template.import.create`. If document-spec inspection reports material direct formatting,
   table geometry/borders, or story fields as degraded, also supply an explicit, uniform,
   representable `manifest.authoring_format` that matches the inspection evidence exactly. Missing
   mappings return `DS_DOCX_TEMPLATE_AUTHORING_FORMAT_REQUIRED`; invented, conflicting,
   nonuniform, or lossy mappings return `DS_DOCX_TEMPLATE_AUTHORING_FORMAT_LOSSY`. Local
   unknown-license imports remain non-redistributable. A
   network-aware caller must download separately and supply the verified local file, original and
   retrieved URLs, retrieval time, downloader identity/version, matching downloaded digest,
   license evidence, and redistribution decision; these operations never open a socket. The
   bundled `general-academic-paper` pack is language-neutral at the layout/style layer, preserves
   English, Simplified Chinese, or other caller text without translation, and supports only
   `document-spec` mode.
6. For merge, bind each local `.docx` source to its exact SHA-256. The base, sources, and output
   must be distinct after portable path normalization. Styles support
   `require-identical|rename-source`; numbering supports `require-identical|remap-source`.
   `AUTHOR|DATE|NUMPAGES|PAGE|TIME|TITLE|TOC` fields are copied and counted after reopen; malformed,
   DDE/external, or unknown field instructions fail closed.
   Simple unlocked single-text-node content controls with only inert id/tag/alias/text properties
   are likewise copied and counted; data bindings, placeholders, locks, nested structures, and
   relationship-bound controls remain unsupported.
   Self-contained footnotes/endnotes preserve their note XML and remap body references; note parts
   with their own relationships or revision/comment/field/control/style/numbering dependencies
   remain unsupported.
   Classic comments require one body range-start/range-end/reference triple and one self-contained
   definition. Thread/reply/resolve extension parts and relationship-bound comment content remain
   unsupported pending real OpenXML and consumer evidence.
   Inline `w:ins|w:del` revisions require bounded numeric ids plus author/canonical UTC date and are
   copied with deterministic id remapping. A move requires exactly paired
   `moveFromRangeStart|moveFrom|moveFromRangeEnd` and
   `moveToRangeStart|moveTo|moveToRangeEnd` ranges bound by the same non-empty name and identical
   author/date metadata. Wrapper/range ids and colliding move names are remapped together and
   counted after reopen. Incomplete, overlapping/nested, custom-XML, property, and table revision
   graphs remain unsupported.
   Unsupported complex Word graphs return `enhancement_required` without changing an existing
   destination.
7. Treat required validation failure as no publication. Optional visual and full OpenXML schema
   gates remain `unavailable` unless that validator actually runs. PDF/PNG rendering, layout-rule
   status, reference visual comparison, and consumer/schema validation are independent states.
   `docx.layout.repair` is limited to three rounds and stops on resolution, no improvement,
   repeated output (oscillation), or the caller's round ceiling.
8. Revisions/comments/schema require `.NET/OpenXML`. Revision reads can filter exact authors,
   canonical UTC date bounds, and insertion/deletion/move types. Revision apply can combine those
   filters with explicit ids and an immutable body paragraph-text or table-hash scope; leaving ids
   empty applies only the bounded filtered/scoped selection. Use the returned revision scope
   metadata and never invent an index or precondition. A root comment add uses one immutable body
   paragraph selector; a reply add uses `parent_comment_id` instead, and the two targets are
   mutually exclusive. Comment reads return `parent_comment_id`, root `thread_id`, and inherited
   thread-level `resolved` state. `docx.comments.resolve` accepts only a root comment id plus a
   literal boolean. Thread mutation is intentionally one level deep, requires single-paragraph
   comment definitions and one supported body anchor, rejects replies to resolved threads, and
   never accepts caller XML. Render/conversion require LibreOffice.
   Provider absence returns a stable unavailable result and never publishes a destination.
9. A `.docm` is accepted by inert inspection only. Typed edit additionally requires literal
   `keep_vba: true` and distinct `.docm` input/output paths. Core copies `vbaProject.bin`
   byte-for-byte and never parses, runs, enables, or modifies it; any non-VBA dangerous category
   still rejects the transaction. Legacy `.doc` is accepted only by `docx.convert.legacy` and is
   never treated as a Core-readable DOCX package.

## Interpret results exactly

- `success`: all required Core gates passed and any output was atomically promoted.
- `degraded`: a caller-authorized semantic fallback ran; read its `degradations`.
- `enhancement_required`: Core intentionally refused semantics outside the closed contract; the
  result recommends a capability but does not claim it ran.
- `unavailable`: the requested optional public operation has no callable accepted provider; no
  output was published.
- `invalid_request`: fix paths, operation-specific arguments, schema version, or template syntax.
- `failed`: no successful result; inspect the stable `DS_*` error and required gate evidence.

LibreOffice and `.NET/OpenXML` are optional enhancements, not Core prerequisites. Detection alone
does not advertise a capability or turn an unavailable/not-run gate into a pass.

## References

- [Typed request examples](references/requests.md)
- [Structured result and status guide](references/results.md)
- [Preservation, security, and validation policy](references/safety-and-validation.md)

Checked example request files live under `assets/examples/`.
