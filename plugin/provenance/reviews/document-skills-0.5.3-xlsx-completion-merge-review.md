# CLEAN — Document Skills 0.5.3 XLSX Dist E2E Final Warm Re-review

Date: 2026-08-26

## Verdict

Status: `clean`

Approval claimed: `true`.

Canonical findings: **0 Blocker, 0 Major, 0 Minor**.

The exact candidate and unbound provenance mapping identified below are
independently approved. The previous provenance self-reference blocker, the
operation-wide feature-aliasing Major, and the final create/edit formula
operation-evidence Major are all closed.

## Reviewer identity

- Reviewer: `Codex collaboration subagent /root/review_xlsx_dist_e2e`
- Identity: `codex-reviewer/document-skills-0.5.3-xlsx-dist-e2e/final-warm-non-author-2026-08-26`
- Runtime: `codex`
- Role: `reviewer`
- Scope: exact XLSX dist-E2E candidate, feature evidence, and unbound
  release-artifact provenance mapping
- Identity assurance: `self-asserted`
- Identity limitations: This reviewer cannot cryptographically prove the
  backing model, service principal, or human operator. This local review does
  not establish remote CI, a pull-request state, a merge, live LibreOffice,
  live .NET/OpenXML, Microsoft Excel, or behavior outside the commands
  explicitly recorded below.
- Report id: `document-skills-0.5.3-xlsx-completion-merge-review`

The reviewer did not author the candidate implementation, fixer tests,
feature mapping, provenance generator, or audit metadata. No prior verdict or
supplied digest was accepted as approval evidence.

## Reviewed target

- Review worktree branch: `review/xlsx-dist-e2e-final`
- Full review base: `origin/main@1b9af10f87d835e3d30cfc093578346cb5e8c675`
- Warm-review base: `c19b6f8064415fb1dc659c8fd4e5356dbb1c1891`
- Candidate commit: `e5234b7e545af97b2d47214c4dc123242dae344c`
- Candidate tree: `5dfa7e91621068a80c83a0e9fc441d601b9382dc`
- Candidate parent: `ec39f2ea3c9b2a4f854a32e4f0d77ed2ef4a9668`
- Independently regenerated unbound provenance mapping SHA-256:
  `c343ff6885aa5e9b72c0a3485fb47724189bfe6af1490b03513fbd17afd44d27`
- Feature-evidence file SHA-256:
  `764f198b91049855e6fdb1053212c6921cfe9243e69c849dc6c50ce410865fdb`
- Full diff scope: 18 paths, 3,468 insertions and 1,202 deletions
- Warm fixer delta: 4 paths, 114 insertions and 5 deletions

The working tree contained no changed path other than this required review
report during the review.

## Scope check

Scope Check: **PASS**

Intent: exercise a freshly built XLSX distribution end to end and make every
one of the 152 advertised features auditable through a real execution nodeid
and a feature-specific assertion.

Delivered:

- a fresh 573-file release build and five dist E2Es through the built public
  artifact;
- exact evidence for all 152 truth-table features across 93 non-real-provider
  mapped nodeids plus one real-provider nodeid;
- real pytest collection, behavior/availability roles, provider requirements,
  assertion AST anchors, high-risk dist-operation coverage, and bounded test
  reuse;
- operation-level create/edit formula analysis and fail-closed validation
  evidence; and
- stable self-referential review metadata that does not make the mapping
  circular.

No requirement gap remains in the reviewed scope.

## Closure of prior findings

### Provenance self-reference blocker — closed

`plugin/tools/provenance_records.py` names this XLSX report as the exact
`CURRENT_REVIEW_ARTIFACT`. Fresh metadata contains exactly 435 module records,
135 data classifications, three metadata exclusions, and zero review
attestations. The only exclusions are `provenance/audit-report.json`,
`provenance/modules.json`, and this report; the previous PPTX review is
ordinary hash-pinned data again.

The Strategy-2 regression copies the release, changes this report's bytes, and
proves that the regenerated mapping remains stable.

### Operation-wide feature-aliasing Major — closed

The schema-2.0 mapping explicitly binds every truth-table feature to one or
more evidence records. The gate validates the exact feature set, evidence tier
and role, provider availability evidence, assertion anchors inside the target
test function, high-risk dist coverage, bounded reuse, and real pytest
collection of every exact nodeid.

The mapping contains 152 features, 200 evidence records, and 93 unique
non-real-provider nodeids. No behavior nodeid is reused by more than ten
features. The previously identified false links for sheet rename, advanced
charts, special-formula failure, and bounded schema errors now point to tests
that execute and assert the named behavior.

### Create/edit formula operation-evidence Major — closed

The warm fixer adds three direct service-operation tests and binds the exact
features to them:

- `xlsx.create/formula_type_classification` executes `xlsx.create` and asserts
  the returned normal category, cell reference, and `formula_type`.
- `xlsx.edit/formula_type_classification` executes a `cell_formula` edit and
  asserts the edit result's returned classification.
- `xlsx.edit/static_formula_syntax_and_reference_validation` submits an
  invalid sheet reference through `xlsx.edit`, asserts the specific formula
  issue and failed validation gate, and proves both source and the existing
  destination are preserved.

The final follow-up also replaces the unrelated inspect worksheet-count anchor
with a real dist assertion:
`inspection["formula_analysis"]["categories"]["normal"] == 4`. The separate
focused inspect classification evidence remains in place.

## Findings

No canonical finding remains.

Standards count: 0 Blocker, 0 Major, 0 Minor.

Spec and coverage count: 0 Blocker, 0 Major, 0 Minor.

## Coverage summary

```text
CODE PATH COVERAGE
==================
[+] fresh 573-file dist and public runner
    +-- [*** TESTED] capabilities contract in XLSX core-only mode
    +-- [*** TESTED] feature-evidence collection gate
    +-- [*** TESTED] rich create/read/inspect/edit/validate workflow
    +-- [*** TESTED] template/summary/pivot/follow-up edit workflow
    `-- [*** TESTED] typed JSON/XLSX/read/JSON/CSV workflow

[+] all 152 advertised feature claims
    +-- [*** TESTED] exact truth-table set, roles, tiers, paths, assertions
    +-- [*** TESTED] 89 non-real-provider release nodeids -> 99 cases
    +-- [*** TESTED] 4 mapped root dist nodeids
    `-- [*** COLLECTED] one real .NET/OpenXML provider nodeid

[+] prior formula evidence gap
    +-- [*** TESTED] create operation classification
    +-- [*** TESTED] edit operation classification
    +-- [*** TESTED] invalid edit fails closed and preserves both inputs
    `-- [*** TESTED] dist inspect returns four normal classifications
```

## Independent verification evidence

- Candidate HEAD, tree, parent, bases, and delta matched the dispatched values.
- The complete formula-analysis file passed under core-only isolation:
  **23 passed in 1.25s**.
- `npm run test:xlsx:dist-e2e` built a fresh 573-file reviewer artifact and ran
  the complete core-only dist suite: **5 passed in 74.01s**. The reviewer-local
  artifact inventory SHA-256 was
  `6e05831ce6a76c897be8705dbd0fabc719f87e800ea724c63eebc1d9bb139ae6`.
- All **89** non-real-provider mapped release nodeids were executed, expanding
  to **99 passed in 52.81s**.
- After the final follow-up, the affected feature-mapping gate and rich dist
  workflow passed again: **2 passed in 12.38s**.
- The Strategy-2 report/mapping stability regression passed independently.
- Independent provenance regeneration before this report rewrite returned
  `c343ff6885aa5e9b72c0a3485fb47724189bfe6af1490b03513fbd17afd44d27`.
- Ruff, Python AST parsing, JSON parsing, strict UTF-8/no-BOM checks, recorded
  module-hash verification, and `git diff --check` passed for the warm delta.
- Every local process was explicitly given
  `DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=0` and
  `DOCUMENT_SKILLS_XLSX_CORE_ONLY=1`.
- The user-level PATH started at 697 characters, 18 entries, zero private
  dotnet entries, and SHA-256
  `7e8f32ba3d944443bb9b3681810e355e11c99c40abd920e04012679051d6c2d3`.

## Evidence boundary

No remote CI status was queried, awaited, investigated, or used. No real
dotnet/OpenXML provider, LibreOffice, or Microsoft Excel process was run. The
capabilities test ran only with `DOCUMENT_SKILLS_XLSX_CORE_ONLY=1`. The single
real-provider nodeid was collected by the mapping gate but not executed. No
repository-wide provider suite was run.

## Attestation

I independently approve the exact candidate commit/tree and unbound
provenance mapping identified above. Based on the reviewed delta, the retained
full-candidate baseline, and the local evidence recorded here, this candidate
is **CLEAN with 0 Blocker / 0 Major / 0 Minor** within the stated evidence
boundary.
