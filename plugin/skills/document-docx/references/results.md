# DOCX result guide

The stable top-level result remains the shared Document Skills contract. DOCX-specific data is
always under `diagnostics.operation_result`.

## Operation payloads

- Read: `document.stories`, `document.sections`, `document.images`, selected limits, and explicit
  truncations. Paragraph, table, and image projections originating from `document_spec` include
  their stable `node_id` and semantic `node_type`; unmarked external/legacy content keeps the
  existing result shape. `document_spec_version`, `style_profile`, and `domain_profile` are read
  back from standard custom properties. `document.formatting` reports the reusable style profile,
  selected style tokens, and direct-formatting normalization evidence. Editable OMML is projected
  under `document.equations`; stable targets and restricted `REF` bindings are projected under
  `document.references`, including the explicit `update_required` state.
- Inspect: inert policy, `mutation_authorized: false`, sorted parts/content types/relationships,
  media, unknown parts, Word feature counts, sections, and dangerous-content sources.
- Accessibility inspect: `pass|review_required`, total/returned/truncated issue counts, four
  fixed check summaries, and bounded issue records with stable code, severity, message, and
  structural location. It is a semantic authoring report, not visual or WCAG certification.
- Create: creation part/image/section/style evidence. The required semantic gate verifies the exact
  ordered stable-node identity set, profile manifest, formatting tokens, captions, reference graph,
  editable equations, and citation/bibliography integrity before output promotion. A
  `template-mapped` profile also binds the local `.docx|.dotx` source to its SHA-256 and reports
  the selected role-to-style mapping. `academic-paper` is a domain profile composed over the
  general emitter; `technical-report` exercises the same emitter without academic front matter.
- Typed edit: applied count, primitive counts, immutable-input paragraph/story-part/image-
  relationship selector policy, and preservation manifest. Table-cell/header/footer formatting
  verifies every changed story part hash after reopen. Image edits additionally verify the reopened
  relationship target, dimensions, alt text, crop, and media payload hash before publication.
  Table edits expose the immutable table-subtree selector policy and compare the reopened table
  hashes, cell text, grid spans, and vertical-merge states with the complete planned table state.
  Section/header/footer edits report section-hash selector policy and verify requested page/break
  properties plus isolated story references and first/even settings after reopen.
  Bookmark/internal-link edits report the immutable body-paragraph/internal-link selector policy
  and verify bookmark range ids plus exact reopened anchor/text pairs before publication.
  Field/TOC edits report a consumer-refresh warning; note, simple content-control, custom-style,
  and numbering edits are compared with their complete reopened inventories. Explicit `.docm`
  edits add `vba_preservation.mode: keep-vba-inert`, while the preservation manifest proves the
  VBA payload remained byte-identical.
- Replace: per-rule/per-story counts, `first-affected-run` formatting policy, protected spans,
  and the preservation manifest.
- Template: sorted used/missing/unused/protected variables, `.docx|.dotx` base-to-`.docx` evidence,
  exact backend/version evidence, bounded region emitted/removed counts, optional style-overlay
  source/hash/conflict mapping, and the preservation manifest.
- Merge: source records, copied body-block count, semantic compatibility/remap status,
  deterministic part/style/numbering/bookmark mappings, safe-field and simple-content-control
  preservation counts, note/comment/revision id mappings and counts, move wrapper/range/name
  mappings, preservation manifest, and structure diff. Reopen assertions report the exact verified
  field/control/note/comment/revision/move-range counts. Unsupported conflicts never produce an
  artifact.
- Revisions read/apply: bounded author/date/type metadata plus selector-ready paragraph text and
  optional table hashes; mutation results include the exact filters/scope selection, matched ids,
  post-reopen remaining-id assertion, and preservation manifest.
- Comments read/add/resolve: bounded records include nullable `parent_comment_id`, root
  `thread_id`, inherited thread-level `resolved`, author/date/text, and body anchor. Add returns
  the reopened root/reply record; resolve returns the verified root record. Mutations also include
  the preservation manifest.
- Schema validation: OpenXmlValidator validity, bounded errors, and a real `schema.full` gate.
- PDF conversion: format, byte count, reopened page count, and visual comparison explicitly
  `unavailable`.
- Legacy DOC conversion: `input_format: doc`, declared `docx|pdf` target, byte count, reopened
  part/page count, and visual comparison explicitly `unavailable`.
- PDF/PNG render: requested page range/fixed 96 DPI, distinct `render_status`,
  `page_generation_status`, `layout_status`, and `visual_comparison_status`, reopened PDF page
  count, provider id/version, and optional bounded per-page PNG records. Each PNG record contains
  base64, SHA-256, byte count, pixel dimensions, and point dimensions. The public PNG payload uses
  a 512 KiB default and a 1,000,000-byte hard aggregate ceiling so the complete result remains
  below the worker protocol limit. `layout.findings` contains stable code, severity, page,
  nullable semantic node id, evidence, and a suggested repair; unavailable node-to-page mapping is
  recorded as a degradation.
- Layout repair: `rounds`, caller ceiling, deterministic score before/after, `stop_reason`, repaired
  node ids, round history, initial/final layout evidence, unresolved findings, render engine, and
  a preservation manifest. The current closed repair changes only oversized drawing extents and
  permits only `word/document.xml` to change.
- Semantic compare: `mode: spec-output|before-after`, comparison `status`, and separate
  `missing`, `unexpected`, `changed`, `degraded`, and `allowed` records. Before/after mode also
  returns a structural diff and preservation manifest; a comparison mismatch is a successful
  execution whose optional result gate is `fail`, so the caller receives the complete report.
- Reference visual compare: fixed render profile/engine, versioned thresholds, explicit page pairs,
  complete-pairing/page-count state, geometry/color/placement-proxy metrics, and bounded overlay and
  diff PNGs. Typography and spacing remain independently `unavailable` rather than being inferred
  from aggregate raster deltas.

Artifact records include the normalized path, SHA-256, and byte count. Mutation results include
both input and output records. The input digest is rechecked after success and handled failure.
Core edit, replace, template, and merge mutation diagnostics also contain `structure_diff`: constant-size
before/after/delta counts for paragraphs, tables, images, sections, relationships, and parts, plus
sorted changed/added/removed part names. It is structural evidence, not a visual comparison.

## Validation

Required gates cover artifact existence/size, ZIP magic/CRC, bounded XML, content types,
relationships, required Word parts, active-content policy, provider reopen, operation semantics,
part preservation, and source preservation where applicable.

`visual.render` and `schema.full` can be `unavailable` while another required operation succeeds.
`unavailable` is never equivalent to `pass` and never raises achieved fidelity. PDF/PNG render can
prove page generation and layout-rule execution without claiming reference comparison. Only
`docx.compare.visual` with a hash-bound reference and complete explicit pairing marks the visual
render evidence as executed; its comparison result remains a separate optional gate. Schema
validation marks `schema.full` pass only when OpenXmlValidator actually ran.

Provider chains are evidence, not configuration. Read/create/edit/replace/inspect/accessibility/
merge/semantic-compare use `core-python`; the admitted scalar template backend uses `core-node`
privately behind Python; revision/comment/schema operations use `dotnet-openxml`; render,
layout-repair, reference-visual-compare, PDF conversion, and legacy conversion use `libreoffice`.

## Status and artifact semantics

- `success`: every required gate passed; a write artifact was atomically promoted.
- `degraded`: an explicitly authorized non-equivalent fallback completed; inspect
  `degradations` before using its artifact.
- `enhancement_required`: the requested semantics are intentionally outside the callable slice;
  no output artifact was promoted.
- `unavailable`: no accepted callable provider exists for that public operation; no output
  artifact was promoted.
- `failed`: provider execution, validation, preservation, or promotion failed; an existing
  destination remains unchanged unless the result explicitly reports committed residue state.
