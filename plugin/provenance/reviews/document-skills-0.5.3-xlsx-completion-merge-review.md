# CLEAN — Document Skills 0.5.3 XLSX Dist E2E Post-main Merge Review

Date: 2026-08-26

## Verdict

Status: `clean`

Approval claimed: `true`.

Canonical findings: **0 Blocker, 0 Major, 0 Minor**.

This is a fresh, post-main-merge independent review. It does not reuse the
earlier reviewer worktree or its approval. The exact candidate and unbound
provenance mapping identified below are independently approved within the
stated evidence boundary.

## Reviewer identity

- Reviewer: `Codex collaboration subagent /root/review_xlsx_dist_e2e`
- Identity: `codex-reviewer/document-skills-0.5.3-xlsx-dist-e2e/post-main53f-fresh-non-author-2026-08-26`
- Runtime: `codex`
- Role: `reviewer`
- Fresh review worktree branch: `review/xlsx-dist-e2e-main53f-final`
- Fresh review worktree:
  `elftia-plugin-document-skills-wt-xlsx-e2e-review-main53f`
- Scope: complete eight-commit actual diff from the new main base, including
  XLSX dist E2E, temporal conversion, feature evidence, formula-operation
  evidence, Strategy-2/3 provenance, and the DOCX/PPTX B4 merge integration
- Identity assurance: `self-asserted`
- Identity limitations: This reviewer cannot cryptographically prove the
  backing model, service principal, or human operator. This local review does
  not establish remote CI, a pull-request state, a merge, live LibreOffice,
  live .NET/OpenXML, Microsoft Excel, or behavior outside the commands
  explicitly recorded below.
- Report id: `document-skills-0.5.3-xlsx-completion-merge-review`

The reviewer did not author the candidate, merge resolutions, tests, feature
mapping, provenance generator, or audit metadata. No previous verdict or
supplied digest was accepted as approval evidence.

## Reviewed target

- Base: `origin/main@53f40c676dc4e59489afa532eaa50bf43f49140b`
- Candidate commit: `eb5d798116327cbd12d83a884c2835e47bd05fa9`
- Candidate tree: `e99215f043338d6d4dda8d587fac902e3f6c9d0a`
- Candidate first parent: `3eafd08d3a5b12df14630d1faf24d57d86969201`
- Candidate second parent: `53f40c676dc4e59489afa532eaa50bf43f49140b`
- Commits above base: 8
- Actual diff: 20 paths, 3,986 insertions and 1,697 deletions
- Independently regenerated unbound provenance mapping SHA-256:
  `95850acd7a9bbae117ef9cd54310513fd019f9ebc0ffbd046bc9a2622d07d9c4`
- Feature-evidence file SHA-256:
  `764f198b91049855e6fdb1053212c6921cfe9243e69c849dc6c50ce410865fdb`

The new reviewer worktree started clean at the exact candidate. During the
review, the only tracked path changed was this required report.

## Scope check

Scope Check: **PASS**

Intent: rebase the previously completed XLSX dist-E2E work onto the new main
containing DOCX completion, PPTX image integrity, PPTX B4 template-content
work, and their shared provenance/runtime updates without weakening either
side.

Delivered:

- the XLSX temporal reopen fix and full feature-evidence system remain intact;
- the fresh 739-file merged release builds and all five core-only XLSX dist
  E2Es execute through the built public artifact;
- all 152 advertised XLSX features retain exact evidence records and pytest
  collection;
- create/edit formula classification, invalid-edit fail-closed behavior, and
  the dist inspect classification assertion remain operation-level evidence;
- the new main's PPTX B4 review becomes ordinary hash-pinned historical data;
- the XLSX review is the exact current self-referential report, with exactly
  three metadata exclusions; and
- Strategy-3 composes both PPTX B2 and B4 provenance into the shared runtime
  record while preserving the complete XLSX requirements rather than relaxing
  an expectation.

No requirement gap remains in the reviewed scope.

## Post-main integration review

### XLSX implementation and evidence remained intact

A direct tree comparison against the last fixed XLSX candidate found no
content difference in the task's non-provenance XLSX production code, tests,
E2E files, launcher, or package script. The main merge changes the shared
provenance surface and adds `test_strategy3.py` to the actual diff; it does not
silently rewrite the temporal fix, the formula operation tests, or the feature
mapping.

Fresh metrics from `e2e/xlsx_dist/feature-nodeids.json` are:

- 152 features;
- 200 evidence records;
- 92 unique non-real-provider evidence nodeids;
- one real-provider nodeid; and
- maximum behavior reuse of 10 features per nodeid.

The gate validates the exact truth-table set, tier/role/provider structure,
assertion anchors, high-risk dist operations, bounded reuse, and real pytest
collection. The final inspect evidence remains bound to
`inspection["formula_analysis"]["categories"]["normal"] == 4`, not to an
unrelated worksheet-count assertion.

### Shared provenance merge is exact

Independent regeneration was byte-semantically equal to the checked
`provenance/modules.json` and produced:

- 569 executable module records;
- 167 data classifications;
- 3 metadata exclusions;
- 0 executable exclusions;
- 0 review attestations before final binding; and
- mapping
  `95850acd7a9bbae117ef9cd54310513fd019f9ebc0ffbd046bc9a2622d07d9c4`.

`CURRENT_REVIEW_ARTIFACT` is exactly
`provenance/reviews/document-skills-0.5.3-xlsx-completion-merge-review.md`.
The three and only three metadata exclusions are:

1. `provenance/audit-report.json`
2. `provenance/modules.json`
3. this current XLSX review report

`document-skills-0.5.3-pptx-b4-merge-review.md` is ordinary
`reviewed-data`. Its recorded SHA-256 exactly matches its bytes:
`6e18c057db4ef07cba94982dcf3da8c2fc817d531d4cf846736554790221f5fc`.

The checked audit report is correctly unbound and reports only the missing
independent attestation. In a temporary copied release, binding a test review
made the complete audit pass. Changing copied XLSX report bytes left the
mapping unchanged.

### Strategy-3 preserves the B2+B4 composition

The shared `provenance/runtime-source-allowlist.json` expectation uses exact
requirement composition in this order:

`pptx-ecosystem-phase-bc-b2 + pptx-ecosystem-phase-bc-b4 + document-skills-core-xlsx + document-skills-xlsx-completion + document-skills-xlsx-advanced-authoring`.

Its expected description likewise concatenates the exact B2 description, B4
description, and XLSX runtime description. The test continues to require all
five profiled shared-data paths and the full XLSX evidence set; it does not
replace an equality with a subset or otherwise weaken the gate.

## Findings

No canonical finding remains.

Standards count: 0 Blocker, 0 Major, 0 Minor.

Spec and coverage count: 0 Blocker, 0 Major, 0 Minor.

## Coverage summary

```text
POST-MAIN INTEGRATION
=====================
[+] exact 8-commit / 20-path actual diff reviewed
    +-- [*** VERIFIED] XLSX non-provenance content retained
    +-- [*** VERIFIED] DOCX/PPTX B4 shared provenance composed
    +-- [*** VERIFIED] PPTX B4 report hash-pinned as historical data
    `-- [*** VERIFIED] XLSX report is sole current review metadata

XLSX EXECUTION
==============
[+] fresh 739-file dist
    +-- [*** TESTED] capabilities contract in core-only mode
    +-- [*** TESTED] 152/152 feature-evidence collection gate
    +-- [*** TESTED] rich create/read/inspect/edit/validate workflow
    +-- [*** TESTED] template/summary/pivot/follow-up edit workflow
    `-- [*** TESTED] typed JSON/XLSX/read/JSON/CSV workflow

[+] mapped evidence
    +-- [*** TESTED] 89 release nodeids -> 99 cases
    +-- [*** TESTED] formula and conversion focused files
    +-- [*** TESTED] rebound audit and mapping stability
    `-- [*** COLLECTED] one real .NET/OpenXML provider nodeid
```

## Independent verification evidence

- HEAD, tree, both parents, base, eight-commit count, and 20-path actual diff
  matched the dispatched target exactly.
- `npm run test:xlsx:dist-e2e` built a fresh 739-file merged artifact and ran
  the complete core-only suite: **5 passed in 50.90s**. Reviewer artifact
  inventory SHA-256:
  `3115cdd30d6da3c253eb70d677d809659770049f446ed3ae3fce56297ce59c8b`.
- All **89** non-real-provider mapped release nodeids executed, expanding to
  **99 passed in 56.82s**.
- The complete XLSX conversion and formula-analysis files plus focused
  Strategy-2/3 provenance checks produced 50 immediate passes. The rebound
  audit initially lacked the locked Acorn dependency and therefore could not
  start its Node parser. After exact `npm ci --ignore-scripts` preparation from
  the release lockfile, the same audit passed; the final focused set therefore
  had **51 passing cases** with no candidate failure.
- The rebound audit's final checks passed inventory, clean-room, commands,
  execution boundary, fixtures, manifests, public skills, SBOM, and bound
  provenance.
- Fresh provenance regeneration exactly equaled the checked manifest and
  independently returned mapping
  `95850acd7a9bbae117ef9cd54310513fd019f9ebc0ffbd046bc9a2622d07d9c4`.
- Ruff and Python AST parsing passed for all 14 changed Python files. All four
  changed JSON files parsed. All 20 changed text files decoded as strict UTF-8
  with no BOM or mojibake markers. The launcher passed `node --check`, and the
  complete candidate diff passed `git diff --check`.
- Every local test process was explicitly given
  `DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=0` and
  `DOCUMENT_SKILLS_XLSX_CORE_ONLY=1`.
- The user-level PATH started at 697 characters, 18 entries, zero private
  dotnet entries, and SHA-256
  `7e8f32ba3d944443bb9b3681810e355e11c99c40abd920e04012679051d6c2d3`.

## Evidence boundary

No remote CI status was queried, awaited, investigated, or used. No real
dotnet/OpenXML provider, LibreOffice, or Microsoft Excel process was run. The
capabilities test ran only with `DOCUMENT_SKILLS_XLSX_CORE_ONLY=1`. The single
real-provider nodeid was collected by the mapping gate but not executed. Root
will run the real-provider post-review check separately; its future outcome is
not claimed by this report. No repository-wide provider or full test suite was
run.

## Attestation

I independently approve the exact post-main candidate commit/tree and unbound
provenance mapping identified above. Based on the complete actual-diff review,
fresh worktree, independent regeneration, and local evidence recorded here,
this candidate is **CLEAN with 0 Blocker / 0 Major / 0 Minor** within the stated
evidence boundary.
