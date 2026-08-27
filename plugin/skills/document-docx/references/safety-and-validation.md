# DOCX preservation, security, and validation

## Copy-through preservation

Template and replacement operations index every input package part and its payload SHA-256.
Only explicitly planned Word story parts may change. No original part may be removed. Unknown
safe parts, media, custom XML, relationships, headers/footers, and section definitions remain
byte-identical at the part-payload level unless they are a declared target.

Accessibility inspection uses the same normal safe-package admission as structured read. It never
opens external relationships, renders, rewrites, inserts remediation, or treats a clean report as
formal WCAG certification. Findings are bounded by `max_issues`; the input SHA-256 is rechecked
after inspection. A style-local language tag does not satisfy the document-language check: only
core `dc:language` or the Word `docDefaults` run language is accepted as document-level metadata.

For `docx.template.apply`, a `.dotx` source is a narrowly admitted template identity rather than a
general active-content exception. Its security inventory must contain exactly the standard Word
template main content type and no attached-template relationship, macro, external target, or other
dangerous category. Private staging changes that one declaration to the `.docx` main content type;
the final preservation manifest binds all other source parts by hash.

Style overlay is an explicit two-source transaction. The overlay path is local, its caller-supplied
SHA-256 must match before planning, and both the base and overlay hashes are checked again around
promotion. Only named `<w:style>` elements may be imported or replaced. Same-id conflicts follow
the declared policy; unknown/unselected base styles are not removed. Missing style dependencies,
numbering bindings, relationship attributes, duplicate style ids, active content, and output/source
aliases fail closed. Reopen validation binds the complete final `word/styles.xml` hash.

Document-spec style profiles use the same fail-closed graph discipline. `professional-generic`
ships self-authored style tokens. `template-mapped` accepts only a local `.docx|.dotx`, an exact
caller-supplied SHA-256, and a closed semantic-role map; missing styles, duplicate ids, invalid
style types, and unresolved style/numbering/relationship dependencies reject the request. The
creation oracle captures selected style XML before writing and validation never re-reads a mutable
template source. Standard `docProps/custom.xml` properties record the document-spec version,
public style profile, and domain profile for native readback; the manifest is evidence, not an
executable template language.

Merge is a bounded multi-source transaction. Every source is local, unique, `.docx`, and bound to
an exact caller-supplied SHA-256; all source hashes are rechecked before and after promotion. Core
copies OOXML body blocks and their supported relationship graph directly, remapping ids and part
names deterministically rather than reconstructing content from text. Explicit policies can retain
identical styles/numbering or import them with deterministic source-id remapping; theme and
font-table parts remain byte-identical. Bookmark ids/names and internal anchors are remapped as one
closed graph, while header/footer image relationships are copied recursively. Safe Word fields use
the same closed vocabulary as typed Core field edits and are counted before planning and after
reopen. Malformed markers, DDE/external fields, and unknown instructions fail closed. Simple
unlocked text content controls are counted through the same planning/reopen boundary; relationship
bindings, data bindings, placeholders, locks, nested structures, and non-text controls remain
rejected. Self-contained footnote/endnote XML is copied without text reconstruction and body/note
ids are remapped as one graph; nested note relationships and semantic dependencies remain rejected.
Classic comments likewise remap the body range/reference triple and `comments.xml` definition as
one graph. Thread/reply/resolve extension parts and comment relationships remain rejected. Inline
tracked insertions/deletions preserve their complete XML and remap collision-prone ids. Complete
move revisions require paired move-from/move-to start, wrapper, and end elements with one shared
name and matching author/date metadata; revision ids, range ids, and colliding names are remapped
before publication. Incomplete, overlapping/nested, custom-XML, property, and table revision graphs
remain rejected. Other unsupported complex Word structures are rejected before writing when their
full graph cannot be preserved. Reopen validation binds the final main document and every copied or
changed part to the immutable merge plan. Failure leaves an existing destination byte-identical.

Typed paragraph/run edits use the same copy-through rule and declare only `word/document.xml`
mutable. Image edits additionally declare the body relationship part, a content-type declaration
only when the raster extension is new, and deterministic new media parts. Replacement redirects
only the selected relationship and preserves the previous media payload, so shared or unknown
parts are never overwritten. All selectors are checked against the immutable input before any
package is written. A missing index, text/style/image mismatch, protected structure, partial-run
boundary, unsafe normalized input identity, or conflicting edit aborts the complete transaction.

Table edits bind the complete source table subtree hash before planning. Insert/cell/row/merge and
split operations change only `word/document.xml`; the reopened candidate must reproduce the full
planned top-level table sequence, hashes, texts, spans, and vertical-merge states. Complex cells are
rejected instead of flattened, and no caller-supplied XML, style id, grid width, or relationship is
accepted.

Section edits bind the full immutable `sectPr` hash. Header/footer replacement never mutates an
existing story part: it adds a deterministic part and relationship, redirects only the selected
section variant, and preserves old/shared payloads. First/even behavior is expressed only with the
closed `titlePg` and `evenAndOddHeaders` vocabulary. Linking to previous removes the selected
reference without deleting any package part.

Bookmark insertion accepts only a bounded ASCII Word name and a complete paragraph range. Internal
hyperlinks carry a `w:anchor` only: Core never adds an external hyperlink relationship. Planning
requires the bookmark to exist in the immutable input or earlier in the same transaction, and
updates require an exact single anchor/text match. Reopen validation checks the bookmark start/end
id pair and the final hyperlink anchor/text. Stale matches leave source and destination unchanged.

Document-spec cross-references use deterministic bookmark names derived from stable target ids and
emit only the restricted dirty field instruction `REF <bookmark> \\h`. Targets are limited to the
closed heading/figure/table/equation set. Missing, duplicate, or wrong-type targets fail the entire
creation transaction; native readback verifies the target/binding graph and reports
`update_required` until a Word-compatible consumer refreshes displayed fields.

Equations accept a bounded linear Unicode subset and emit editable OMML. Raw OOXML, LaTeX commands,
and unsupported syntax are rejected instead of executed or silently rasterized. Structured
citations accept only known bibliography keys and the fixed `numeric|author-year` formatters.
Citation keys and bibliography entries are checked in both directions before publication; the
slice does not claim arbitrary CSL or journal-style coverage.

The output ZIP hash normally differs from the input ZIP hash. Preservation claims refer to
untargeted part payloads, not whole-container byte identity.

## Fail-closed package policy

Normal read and every mutation except the explicit keep-VBA `.docm` path reject:

- absolute, traversal, drive-qualified, duplicate, normalized-alias, or symlink ZIP members;
- CRC, entry, uncompressed-size, expansion-ratio, or XML-size violations;
- malformed XML, DTDs, and entities;
- escaping or missing internal relationship targets;
- VBA/macros, DDE, remote templates, external relationships, executable parts, OLE, and ActiveX.

Consequently, the typed hyperlink slice is intentionally internal-only. A URL-shaped caller value
is not part of its closed contract, and the mutation path cannot be used to authorize an external
relationship that normal package policy would reject on reopen.

Structural inspection can inventory bounded active/external content without following or
executing it, but the underlying ZIP/XML container must still be safe.

The keep-VBA path is narrower than structural inspection. It requires literal `keep_vba: true`,
distinct `.docm` input/output paths, the standard macro-enabled main content type, one contained
`word/vbaProject.bin`, and its internal document relationship. The VBA payload is an opaque
copy-through part and must retain its SHA-256. Any other dangerous category—or an unexpected VBA
part, content type, relationship source, target, or mode—fails before publication. Core never
parses, invokes, enables, signs, or rewrites VBA.

## Protected Word structures

Replacement and template matching do not cross hyperlinks or structural barriers. They still
return `enhancement_required` rather than editing field instructions, tracked revisions, deleted
text, or comment bodies. Dedicated `docx.revisions.*` and `docx.comments.*` requests can use an
accepted callable `.NET/OpenXML` provider; presence detection alone does not run or enable it.

Revision/comment mutations accept only typed bounded actions and closed selectors. Revision
author/date/type filters are applied before the result limit, and scoped revision mutation requires
an exact immutable body paragraph text or public table-subtree hash. Explicit ids outside that
selection fail the whole transaction. Mutations stage a distinct output, run provider reopen and
operation assertions, compare package preservation, and promote only after source preservation
succeeds. The helper receives no raw XML or private provider operation from the caller.
Comment roots use an exact body-paragraph text precondition. Replies instead bind one decimal root
comment id and inherit that root's anchor and resolved state. Only a single-paragraph, one-level
thread with one range-start/range-end/reference anchor is mutable; dangling parents, nested replies,
independently resolved replies, reply-to-resolved requests, and conflicting extension graphs fail
inside private staging. Resolution targets roots only and writes the standard `commentsExtended`
`done` state. Reopen projection verifies the entire thread state before atomic promotion.

Declarative template regions never interpret template control markers. They clone or remove only
exact-text-bound top-level body paragraphs; repeat items are closed scalar maps and conditions are
literal booleans. The complete post-region story is included in the template semantic oracle
before the existing contained scalar backend runs.

## PDF/PNG page evidence, layout repair, and visual comparison

`docx.convert.pdf`, `docx.render`, `docx.layout.repair`, and `docx.compare.visual` call LibreOffice
only through the accepted provider boundary. Each invocation uses an isolated profile, a read-only
staged source, an independent output directory, an operation-specific timeout, byte ceilings, and
reopen validation. Mutations use atomic promotion, and every input/reference hash is checked before
and after.

PDF page generation proves conversion, bounded page selection, and reopenability. Optional public
PNG evidence uses fixed 96 DPI, per-page and aggregate limits, exact payload hashes, and a public
aggregate ceiling compatible with the worker result budget. Deterministic layout inspection keeps
render, PNG generation, layout-rule, and visual-comparison states separate. Findings are bounded
and explainable; semantic-node-to-page mapping is marked degraded when the renderer cannot expose
it. A normal render is never called a visual comparison.

`docx.layout.repair` is a bounded render-inspect-mutate loop. The current repair vocabulary contains
only `DOCX_LAYOUT_OBJECT_EXCEEDS_TEXT_WIDTH`; it selects drawings by stable semantic node id and may
change only their extent in `word/document.xml`. It stops after at most three rounds on resolution,
no applicable repair, no score improvement, repeated output/oscillation, or the caller ceiling.
Unresolved findings and the complete round history remain visible; no full-document reconstruction
is used.

`docx.compare.visual` requires a hash-bound local `.docx|.pdf|.png` reference, fixed
`libreoffice-96dpi-v1`/sRGB-RGBA8 rendering, and explicit one-to-one page pairs covering both page
sets before pass. Versioned thresholds are code-owned. Geometry, aggregate color, and raster
placement proxies are measured; typography and spacing stay `unavailable`. Overlay/diff images are
bounded evidence, not permission to bypass package, semantic, or preservation validation.

`docx.convert.legacy` is the only `.doc` admission path. LibreOffice receives a read-only private
copy under an isolated profile and may emit only the explicitly declared `.docx` or `.pdf` target.
The output is byte-bounded and reopened by the corresponding validator before atomic promotion;
ordinary read/edit/template/merge operations continue to reject `.doc`.

## Schema validation

`docx.validate.schema` is read-only. It reports bounded OpenXmlValidator errors and marks
`schema.full` pass only after the accepted `.NET/OpenXML` helper actually executes. Normal Core
operations leave the optional schema gate unavailable/not run rather than claiming a pass.

## Mammoth evaluation boundary

Mammoth 1.12.1 was evaluated as a lossy DOCX-to-HTML adapter and was not adopted. Its compact HTML
projection did not retain stable ids, sections, headers/footers, styles, numbering, layout, package
security, or preservation evidence. No runtime dependency, public Markdown/HTML operation, lock,
or SBOM entry was added. Native OOXML remains the security, preservation, semantic comparison, and
structural-validation source of truth.

## Transaction

Each write validates explicit/distinct paths, hashes the source, writes under a private operation
root, executes required gates on the staged DOCX, validates the canonical candidate result,
stages in the destination filesystem, atomically promotes, rechecks final bytes, and verifies the
source digest. Failure before promotion leaves the destination unpublished.
