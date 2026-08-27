# CLEAN — Document Skills 0.5.3 PPTX/OpenXML Schema-Order Provenance Review

Date: 2026-08-26

## Verdict

- Status: `clean`
- Approval claimed: `true`
- Canonical findings after final warm re-review: **0 Blocker, 0 Major, 0 Minor, 0 Trivial**
- Scope: the exact all-release-artifact mapping, source/data classifications, provenance
  metadata, release inventory, changed release source, fixture bytes, direct regressions, and the
  explicitly bounded prerequisite changes described below.

This approval binds only the following mapping SHA-256:

`1f5c737a7fbe9a49a3fef34351687cb30450fa8292b0aeb6d3b0259b3e1abcee`

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

No prior report identity, historical clean verdict, pre-generated candidate, prerequisite PR
description, or earlier mapping was treated as current approval evidence. The canonical path is
reused solely because it is one of the three explicitly allowed self-referential metadata paths.

## Reviewed target and final composition

The final warm review covers branch `fix/pptx-openxml-schema-order` at
`6d0eac6ad059a082ffcc33488836368f6e805af6`, based on
`origin/main@ec917a0242f8f2dd9fc39e012e7943df05712e90`, plus the final pending provenance and
review-report bytes.

The branch combines:

- `8a6c3c0` — the PPTX/OpenXML repair and its provenance/test/fixture evidence;
- `fe1fb95bb52130bf013132dcd945e0fa80e3a98d` — producer-side compileall bytecode-cache
  isolation (PR #5); and
- `54b4c6040332e821e0f42b7cac298988250ec8d2` — Windows consumer cold-start timeout-test
  stability (PR #6), followed by one behavior-neutral unused-import cleanup raised during this
  warm review.

The repository diff contains 18 paths. Seventeen are under the plugin producer root, including
the three circular provenance metadata paths; the eighteenth is
`scripts/run-plugin-checks.mjs`, a repository-level producer verification script that is not a
plugin release artifact. No prerequisite overlaps or changes the reviewed PPTX runtime, fixture,
or profile bytes from `8a6c3c0`.

## Independent review method

The review independently:

1. enumerated the plugin release through the shared inventory and checked portable uniqueness
   and symlink absence;
2. regenerated the pending manifest in memory and compared it structurally with the checked-in
   candidate;
3. recomputed every non-circular release SHA-256 and recomputed the canonical mapping with
   ordinal sorting independently of the generator;
4. reviewed the complete PPTX runtime/test/profile diff and the two prerequisite changes in
   surrounding code context;
5. checked source, license, dependency, dynamic-execution, network, fixture, and metadata
   boundaries; and
6. ran focused regressions, a real OpenXML SDK validator, Ruff, Node syntax checking, strict text
   checks, and the pre-binding machine audit.

The generator result, checked manifest, and independent ordinal digest all equal the mapping
above.

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

## Findings raised and closed before final approval

The first candidate was rejected because Core-PPTX changes in typed creation, the shared public
supervisor, and their tests inherited generic foundation or HTML-only provenance descriptions and
indirect artifact-test links. The final profile/generator changes add explicit Core-PPTX and
combined HTML+Core requirements, truthful descriptions, and direct regression evidence. The
regenerated records match those profiles exactly.

The warm prerequisite candidate was then rejected because its newly changed
`tests/test_consumer_validation.py` still contained an unrelated unused local `fitz` import and
failed targeted Ruff. A non-reviewer removed that import. The final file passes Ruff and its two
adjacent parameterized independent/corruption fixture tests pass all eight cases. The cleanup does
not alter `_write_pdf`, which retains the actual local `fitz` import it uses.

No finding remains open.

## Prerequisite-byte review and boundary

### Producer compileall isolation

`scripts/run-plugin-checks.mjs` has SHA-256
`e386e7f364aef09a891ad94899aa8f592f7c302c5bb78d497ed16da686e71096`. It is outside the plugin
release inventory and therefore correctly has no release provenance record. It is still reviewed
as producer-side verification code:

- `mkdtempSync(join(tmpdir(), "elftia-document-skills-bytecode-"))` creates a new exact system
  temporary directory;
- Python receives that exact directory through `-X pycache_prefix=...`, so compileall does not
  populate release-source trees; and
- `rmSync` targets only the exact newly returned directory in `finally`, including failure paths.

The script adds no shell interpolation or user-selected cleanup target. `node --check` passes.
The complete post-binding `npm run verify` remains mandatory to exercise this orchestration in the
final integrated workflow.

### Windows consumer timeout stability

`tests/test_consumer_validation.py` has exact release-record SHA-256
`d798b92ff372b521df0f17dc5113e22f7684e4e1a64fefe42174c98a64077fb7`. Its record is correctly
classified as original GPL-3.0 clean-room consumer-gate evidence with empty third-party files,
requirement `Rasen document-skills-consumer-gates-and-truthful-contracts`, and direct
consumer/cross-format test links.

The behavioral test body is unchanged except that the real Office process timeout increases from
0.25 to 4.0 seconds so Windows cold start can publish its child PID before cleanup. It still
requires a typed timeout failure, positive descendant cleanup, source-hash preservation, process
absence, and total operation time below 10 seconds. The real Windows test passes in 9.01 seconds.

## Source, license, dependency, and execution-surface review

- All **327** risky release records are `source_class: original`, `clean_room: true`, `GPL-3.0`,
  with empty `third_party_files`; there are no adopted records.
- The plugin runtime delta remains bounded to OpenXML element construction/order and
  operation-scoped public worker budgets. Neither prerequisite adds plugin runtime code,
  dependencies, lockfile changes, package adoption, native payloads, network clients, dynamic
  imports, `eval`, or `exec`.
- Targeted changed-source searches found no copied-source copyright/SPDX header, upstream source
  attribution, Anthropic, MiniMax, claude-office, or MCP implementation reference.
- The static execution-boundary audit passes with **323** Python/Node source files, **327** risky
  artifacts, four dependency manifests, and two registration manifests.
- The deterministic CycloneDX SBOM remains unchanged and passes with SHA-256
  `a8d871e521169509b6a109bf4ee342e961b985d282589e4d3d3964a58757fa2d`.

These are provenance and source-review conclusions, not a legal opinion or proof against every
possible expression-level derivation.

## PPTX/OpenXML repair review

The plugin runtime changes correct five schema/operation boundaries without changing the public
data model:

- theme gradient fills contain the two required `a:gs` stops;
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

The prerequisite merges do not modify any of those validated runtime or fixture bytes.

## Fixture and verification evidence

- The fixture registry contains **35** records and the machine fixture audit passes.
- `html-native.expected.pptx` is a valid 16-entry ZIP with no CRC failure; its actual and manifest
  SHA-256 are both
  `0e6aa02162c4005c9cc72de0d0ffa4367098f9ba3c47110987585ebdbefbd41f`.
- The fixture manifest SHA-256 is
  `339156ef0871867f2fde6a7c206d8fa9d4fbb29704231306a6f39e8238a24868`.
- The fixture recipe regenerated twice to the checked-in bytes during the focused PPTX test group.
- Affected PPTX/HTML tests: **46 passed, 6 skipped** out of 52 collected. The six skips are
  capability-probed browser/provider cases; schema-order, typed-create, deterministic fixture, and
  worker-budget regressions executed and passed.
- Final provenance profile tests: **2 passed**.
- Real Windows descendant-timeout regression: **1 passed**.
- Independent/corrupted consumer fixture regression functions: **8 parameterized cases passed**.
- Ruff across all **12** changed release Python files: pass.
- `node --check scripts/run-plugin-checks.mjs`: pass.
- Strict UTF-8, no-BOM, LF-only checks across all **17** changed text paths: pass.
- `git diff --check`: pass.

The pre-binding machine audit passes public Skills, manifests, commands, inventory, execution
boundary, fixtures, clean-room declarations, and SBOM. Its sole expected failure is
`Independent review attestation is missing`; this report exists to supply that attestation. The
checked audit report is circular metadata and must be regenerated after this exact report hash is
bound. A clean post-binding machine audit, supply-chain test, and full `npm run verify` remain
mandatory before merge.

## Evidence boundary

The checks prove exact current release bytes, release coverage, declared classifications,
reviewed metadata, static execution policy, fixture registration/determinism, and OpenXML SDK
schema validity for the two representative repaired output paths. Producer-side CI orchestration
is reviewed but is outside the plugin release mapping. The checks cannot prove the self-asserted
reviewer identity, a compromised runtime or host dependency, all possible Office-version or
LibreOffice behavior, remote CI availability, or complete security/legal correctness. No claim
beyond the stated mapping and evidence is made.
