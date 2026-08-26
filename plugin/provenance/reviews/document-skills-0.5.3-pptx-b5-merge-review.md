# CLEAN — Document Skills 0.5.3 PPTX B5 Round 3 Delta Re-review

Date: 2026-08-27

## Verdict

Status: `clean`

Approval claimed: `true`.

Canonical unresolved findings: **0 Blocker, 0 Major, 0 Minor**.

This delta-only non-author re-review confirms that B5-R3-MAJ-001 and
B5-R3-MIN-001 are closed. Approval is limited to the exact base, reviewed
HEAD, current uncommitted repair delta, and unbound semantic mapping recorded
below.

## Reviewer identity

- Reviewer: `Codex collaboration agent /root/b5_review_round2`
- Identity:
  `codex-reviewer/document-skills-0.5.3-pptx-b5/review-cycle-round-3-delta-re-review-2026-08-27`
- Runtime: `codex`
- Role: `independent non-author delta reviewer`
- Scope: `B5 Round 3 repair delta and exact all-release-artifacts mapping`
- Identity assurance: `self-asserted`
- Identity limitations: This reviewer cannot cryptographically prove the
  backing model, service principal, human operator, or maintainer approval,
  and this local re-review does not establish current-branch remote CI, a pull
  request, a commit, a push, a merge, POSIX runtime behavior, or behavior
  beyond the commands and observations recorded here.

The reviewer did not author the depth preflight, regression tests, Ruff
cleanup, provenance profile update, or regenerated manifests.

## Reviewed target

- Worktree:
  `elftia-plugin-document-skills-wt-pptx-b5`
- Branch: `feat/pptx-ecosystem-phase-bc-b5`
- Base:
  `origin/main@861e86c4cbede6c6b69a0f13509e6f8813476235`
- Previously reviewed HEAD:
  `5343cc16f6723e899e2489876d7c5d6486ed9a3b`
- Current HEAD:
  `5343cc16f6723e899e2489876d7c5d6486ed9a3b`
- Candidate form: six tracked modified files and one untracked regression-test
  file above the reviewed HEAD; no functional commit was created
- Independently regenerated unbound provenance mapping SHA-256:
  `2ee7b4c7290a6de4e5715c3909f5ba97f6dd5ec55d69352b07830eda601a9ce6`
- Unbound inventory: 601 module records, 195 data classifications,
  0 executable exclusions, 3 metadata exclusions, 0 review attestations

The repair delta contains only:

1. iterative PresentationML group-depth preflight;
2. direct/public strict/tolerant resource-limit regression coverage;
3. removal of the two prior unused bindings;
4. B5 provenance-profile registration for the new test; and
5. regenerated unbound provenance and audit manifests.

No functional code, tests, provenance files, attestation, run-state, commit,
push, pull request, or merge was changed by this reviewer. The only review
write is this external canonical report.

## Scope check

Scope Check: **CLEAN**

Intent: close B5-R3-MAJ-001 and B5-R3-MIN-001 without expanding B5 behavior.

Delivered: a bounded pre-projection depth gate, four public/direct negative
paths, mechanical lint cleanup, and exact provenance rebinding. No unrelated
feature or delivery change is present.

## Code-path and user-flow coverage

```text
CODE PATH COVERAGE
==================
[+] scene_export_objects._slide()
    |
    +-- collect top-level drawable elements
    +-- _require_group_depth(elements)
    |     |
    |     +-- non-grpSp element
    |     |     -> preserve parent depth
    |     |     -> do not descend into non-drawable XML
    |     |
    |     +-- grpSp element
    |           -> depth = parent depth + 1
    |           +-- depth <= 64 -> push drawable children only
    |           +-- depth > 64  -> DS_RESOURCE_LIMIT {"limit": 64}
    |
    +-- accepted tree -> existing recursive object projection
                       -> Deck IR / SVG / staged bundle / atomic publish

USER FLOW COVERAGE
==================
[+] 65 nested groups
    +-- [★★★ TESTED] direct service, strict
    +-- [★★★ TESTED] direct service, tolerant
    +-- [★★★ TESTED] public isolated worker, strict
    +-- [★★★ TESTED] public isolated worker, tolerant
         all -> failed + DS_RESOURCE_LIMIT + source unchanged + no destination

[+] Boundary and filter behavior
    +-- [★★★ VERIFIED] 64 nested groups -> strict service success + bundle
    +-- [★★★ VERIFIED] 65 nested groups -> typed DS_RESOURCE_LIMIT
    +-- [★★★ VERIFIED] 200 nested fake grpSp nodes below non-drawable extLst
                       -> ignored by the drawable-depth policy

[+] Existing supported scene/chart flow
    +-- [★★★ TESTED] scene export and strict ChartML suites, 25 passing tests

------------------------------------------------------------
COVERAGE: every changed behavioral branch is exercised
GAPS: none identified in the repair delta
------------------------------------------------------------
```

## Closed prior findings

### B5-R3-MAJ-001 — CLOSED

`scene_export_objects._require_group_depth()` uses an explicit iterative
stack before recursive object projection. It counts only actual drawable
`grpSp` ancestry, rejects depth 65 before Python recursion, and emits
`DocumentSkillsError(ErrorCode.RESOURCE_LIMIT)` with the stable
`{"limit": 64}` detail.

The new parameterized tests cover strict and tolerant modes through both
`PptxService.execute()` and the public isolated worker. Every path asserts
the typed code, source hash preservation, and absence of output publication.

Independent boundary replay additionally established:

- exactly 64 groups are accepted and produce a successful bundle;
- 65 groups return `DS_RESOURCE_LIMIT`; and
- non-drawable XML descendants do not inflate the group depth.

### B5-R3-MIN-001 — CLOSED

The unused `chart` assignment and unused `Path` import were removed.
Focused Ruff over every changed source, test, and provenance-profile Python
file reports `All checks passed!`.

## Findings

No canonical finding remains.

- Standards axis: 0 Blocker, 0 Major, 0 Minor
- Spec/coverage axis: 0 Blocker, 0 Major, 0 Minor

## Independent verification evidence

- `uv run --frozen pytest -q tests/test_pptx_scene_export_depth.py`:
  **4 passed**.
- `uv run --frozen pytest -q tests/test_pptx_scene_export.py
  tests/test_pptx_scene_export_chart_strict.py`: **25 passed**.
- Focused Strategy 2/3 provenance selection: **4 passed**.
- `uv run --frozen pytest -q tests/test_html_provenance.py`:
  **7 passed**.
- `node --test scripts/__tests__/reproducibility.test.mjs`:
  **3 passed**.
- Total independently observed: **40 Python tests and 3 Node tests passed**.
- Independent in-memory boundary replay printed:
  `depth64=pass depth65=DS_RESOURCE_LIMIT nondrawable_ignored=pass
  service64=success`.
- Focused Ruff over the five changed Python source/test/profile files passed.
- `uv lock --check --offline` passed.
- `git diff --check` and `git diff --cached --check` passed.
- Strict UTF-8 decoding, no BOM/replacement/mojibake markers, and JSON parsing
  passed for all seven delta files.
- Mapping-only regeneration returned exactly
  `2ee7b4c7290a6de4e5715c3909f5ba97f6dd5ec55d69352b07830eda601a9ce6`.
- Independent in-memory regeneration was semantically identical to checked
  `provenance/modules.json`; regenerated
  `runtime-source-allowlist.json` was also identical to the checked file.
- Manifest comparison against the reviewed HEAD found one expected added
  module (`tests/test_pptx_scene_export_depth.py`), 78
  `artifact_tests`-only updates, and four
  `artifact_tests + sha256` updates for the changed implementation/profile
  files; no removal or other semantic drift.
- The checked and live unbound provenance audits fail only with
  `Independent review attestation is missing`, the expected pre-binding
  fixed point; all other audit checks pass.

## Remote and delivery evidence boundary

No pull request exists for
`feat/pptx-ecosystem-phase-bc-b5`, so Greptile triage is not applicable and
no current-branch remote result was observed. The previously established
GitHub Billing no-start condition remains missing remote evidence rather than
a code failure. Task 11.3 remains honestly incomplete and is not a repair-delta
finding.

PowerPoint COM and LibreOffice were not re-executed because the repair changes
only pre-projection resource containment and dead bindings; approval does not
extend beyond the local evidence above.

## Attestation

I independently re-reviewed the exact uncommitted B5 Round 3 repair delta and
semantic mapping
`2ee7b4c7290a6de4e5715c3909f5ba97f6dd5ec55d69352b07830eda601a9ce6`.
Within the stated scope and limitations, the result is **CLEAN with 0 Blocker /
0 Major / 0 Minor**.
