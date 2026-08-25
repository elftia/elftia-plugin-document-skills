# CLEAN — Document Skills 0.5.3 PPTX/OpenXML Schema-Order Provenance Review

Date: 2026-08-26

## Verdict

- Status: `clean`
- Approval claimed: `true`
- Canonical findings after review: **0 Blocker, 0 Major, 0 Minor, 0 Trivial**
- Scope: the exact all-release-artifact mapping, source/data classifications, provenance
  metadata, release inventory, changed runtime source, fixture bytes, and direct regression
  evidence described below.

This approval binds only the following mapping SHA-256:

`086001a28ffe6e913f019e332281097bab7949e617b38f0547e2ffa0d4a4ea31`

It is not a general maintainer release approval, remote-platform attestation, legal opinion, or
claim that every Office implementation behaves identically.

## Reviewer and attestation identity

- Reviewer: `OpenAI Codex independent provenance reviewer: pptx-openxml-schema-order/2026-08-26`
- Identity: `codex-reviewer/pptx-openxml-schema-order/gpt-5.6-2026-08-26`
- Runtime: `codex`
- Role: `reviewer`
- Scope: `all-release-artifacts`
- Identity assurance: `self-asserted`
- Identity limitations: This reviewer cannot cryptographically prove the backing model, service
  principal, human operator, or execution environment and does not establish professional legal,
  penetration-test, remote-CI, or final maintainer approval.
- Attestation id: `document-skills-0.5.3-pptx-openxml-schema-order-review`
- Report name: `document-skills-0.5.3-unified-pptx-provenance-review.md`

No prior report identity, historical clean verdict, pre-generated candidate, or previous mapping
was treated as current approval evidence. The canonical path is reused solely because it is one
of the three explicitly allowed self-referential metadata paths.

## Reviewed target and method

The review covers branch `fix/pptx-openxml-schema-order` at base
`origin/main@ec917a0242f8f2dd9fc39e012e7943df05712e90` plus the final pending working-tree bytes.
The implementation/provenance candidate before this self-referential report contains 14 changed
paths: four PPTX/public-supervisor runtime modules, five direct test modules, two provenance
generator/profile modules, one regenerated PPTX oracle, its fixture manifest, and the pending
provenance manifest. This report is the fifteenth and final changed path.

The review independently:

1. enumerated the release through the shared inventory and checked portable uniqueness and
   symlink absence;
2. regenerated the pending manifest in memory and compared it structurally with the checked-in
   candidate;
3. recomputed every non-circular file SHA-256 and recomputed the canonical mapping with ordinal
   sorting independently of the generator;
4. reviewed the complete runtime/test/profile diff and the surrounding OpenXML and public-worker
   call paths;
5. checked source, license, dependency, dynamic-execution, network, fixture, and metadata
   boundaries; and
6. ran focused regressions, the real OpenXML SDK validator, static checks, and the pre-binding
   machine audit.

The generator result, the checked manifest, and the independent ordinal digest all equal the
mapping above.

## Release inventory, hashes, and metadata boundary

- **429** unique regular release files, with no symlinks or portable-path collisions.
- **327** risky module records.
- **0** adopted-source records.
- **0** executable exclusions.
- **99** exact-hash data classifications.
- **3** hashless self-referential metadata exclusions.
- **426/426** non-circular module/data SHA-256 values match the final filesystem bytes.
- The pending manifest generated in memory is structurally identical to
  `provenance/modules.json` and contains no duplicate or overlapping classification.

The only hashless paths are exactly:

- `provenance/audit-report.json`
- `provenance/modules.json`
- `provenance/reviews/document-skills-0.5.3-unified-pptx-provenance-review.md`

They are metadata-only circular exclusions: each contains or binds the mapping/report digest.
No executable or ordinary data artifact is admitted through this boundary.

## Finding raised and closed before approval

The first candidate was rejected because Core-PPTX changes in typed creation, the shared public
supervisor, and their tests inherited generic foundation or HTML-only provenance descriptions and
indirect artifact-test links. That metadata would not truthfully describe the reviewed change.

The final candidate adds explicit Core-PPTX and combined HTML+Core profiles, makes the generator
consume the combined profile, and adds exact regression assertions. The final records now bind:

- Core-PPTX requirements and direct design/operation/schema/public tests for typed creation;
- combined HTML-to-PPTX and Core-PPTX requirements for shared scaffolding and the public
  supervisor; and
- the consumer-gates requirement as well for the shared provenance generator.

The regenerated records, descriptions, requirements, and direct `artifact_tests` match these
profiles exactly. No finding remains open.

## Source, license, dependency, and execution-surface review

- All **327** risky records are `source_class: original`, `clean_room: true`, `GPL-3.0`, with
  empty `third_party_files`; there are no adopted records.
- The runtime delta is bounded to OpenXML element construction/order and operation-scoped public
  worker budgets. It adds no dependency, lockfile, package adoption, native payload, network
  client, subprocess API, dynamic import, `eval`, or `exec` surface.
- Targeted changed-source searches found no copied-source copyright/SPDX header, upstream source
  attribution, Anthropic, MiniMax, claude-office, or MCP implementation reference.
- The static execution-boundary audit passes with **323** Python/Node source files, **327** risky
  artifacts, four dependency manifests, and two registration manifests.
- The deterministic CycloneDX SBOM remains unchanged and passes with SHA-256
  `a8d871e521169509b6a109bf4ee342e961b985d282589e4d3d3964a58757fa2d`.

These are provenance and source-review conclusions, not a legal opinion or proof against every
possible expression-level derivation.

## PPTX/OpenXML repair review

The runtime changes correct five schema/operation boundaries without changing the public data
model:

- theme gradient fills now contain the two required `a:gs` stops;
- native body-shape `p:spPr` children follow schema order;
- table and chart `p:graphicFrame` transforms use `p:xfrm` while shape transforms remain
  DrawingML `a:xfrm`;
- scene group transforms use `off`, `ext`, `chOff`, `chExt` order; and
- `pptx.create`, `pptx.create.from-markdown`, and `pptx.edit` receive a private 45-second worker
  budget without relaxing unrelated commands.

The no-placeholder f-string and unused-import removals are behavior-neutral Ruff cleanup in the
same touched files. Direct XML assertions cover each namespace/order change and the worker-budget
test covers all three operations plus unchanged HTML, schema, LibreOffice, and ordinary limits.

A real `DocumentFormat.OpenXml` **3.0.0** validator run returned `valid: true` with zero errors for:

- the regenerated `tests/fixtures/html-native.expected.pptx`; and
- a representative typed-create deck containing two slides, native body shapes, a table, a chart,
  an image, and notes.

## Fixture and verification evidence

- The fixture registry contains **35** records and the machine fixture audit passes.
- `html-native.expected.pptx` is a valid 16-entry ZIP with no CRC failure; its actual and manifest
  SHA-256 are both
  `0e6aa02162c4005c9cc72de0d0ffa4367098f9ba3c47110987585ebdbefbd41f`.
- The fixture manifest SHA-256 is
  `339156ef0871867f2fde6a7c206d8fa9d4fbb29704231306a6f39e8238a24868`.
- The fixture recipe regenerated twice to the checked-in bytes during the focused test group.
- Affected PPTX/HTML tests: **46 passed, 6 skipped** out of 52 collected. The six skips are the
  capability-probed browser/provider cases; the schema-order, typed-create, deterministic fixture,
  and worker-budget regressions executed and passed.
- Final provenance profile tests: **2 passed**.
- Ruff on all 11 changed Python files: pass.
- Strict UTF-8/no-BOM/no-replacement-character checks on all 13 changed text candidates before
  this report: pass.
- `git diff --check`: pass.

The pre-binding machine audit passes public Skills, manifests, commands, inventory, execution
boundary, fixtures, clean-room declarations, and SBOM. Its sole expected failure is
`Independent review attestation is missing`; this report exists to supply that attestation.
After this report is hash-bound into `provenance/modules.json`, a clean post-binding machine audit
and supply-chain test remain mandatory before merge.

## Evidence boundary

The checks prove exact current bytes, release coverage, declared classifications, reviewed
metadata, static execution policy, fixture registration/determinism, and OpenXML SDK schema
validity for the two representative repaired output paths. They cannot prove the self-asserted
reviewer identity, a compromised runtime or host dependency, all possible Office-version or
LibreOffice rendering behavior, remote CI availability, or complete security/legal correctness.
No claim beyond the stated mapping and evidence is made.
