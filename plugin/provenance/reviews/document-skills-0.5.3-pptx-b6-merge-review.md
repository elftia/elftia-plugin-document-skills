# FINAL REPAIRED EXACT-MAPPING REVIEW APPROVED — PPTX B6 editable equations

Date: 2026-08-27

## Verdict

Status: `clean`

Approval claimed: `true`

The repaired exact unbound release mapping identified below is approved for
provenance attestation binding. This non-author re-review found **0 Blocker, 0
Major, 1 accepted-known Minor, and 0 Trivial** findings. B6-005 is independently
closed on the repaired bytes. B6-001, B6-002, and B6-003 remain closed. B6-004
remains the accepted-known formal artifact traceability Minor.

This report completely supersedes the earlier review bound to
`bbf92d8b848a4b68e1062d6551c20cdf423e10e67625ed4b8cb4d57e300661ee`.
That digest and its prior reviewer identity are not approved for, and must not
be reused by, the repaired candidate.

The `clean` value is the review-attestation status required for approval. It
does not claim that the pre-binding audit currently passes: the repaired
checked-in manifest intentionally has zero review attestations, and its sole
audit failure is `Independent review attestation is missing`.

## Attestation fields

```yaml
approval_claimed: true
id: document-skills-0.5.3-pptx-b6-repaired-exact-mapping-review
identity: codex-reviewer/document-skills-0.5.3-pptx-b6/repaired-release-review-2026-08-27
identity_assurance: self-asserted
identity_limitations: >-
  This session-local/process identity is self-asserted and is not
  cryptographically verified. It does not prove the backing model, service
  principal, human operator, maintainer approval, remote CI, PowerPoint,
  LibreOffice, push, pull request, or merge.
reviewer: /root/b6_release_review
reviewer_task_id: /root/b6_release_review
role: reviewer
runtime: codex
runtime_description: Codex / GPT-5 session-local reviewer
scope: all-release-artifacts
status: clean
report_evidence: provenance/reviews/document-skills-0.5.3-pptx-b6-merge-review.md
report_name: document-skills-0.5.3-pptx-b6-merge-review.md
reviewed_mapping_sha256: 45011341001a17f376dfb65f61d0aea701c36978a17a84e5a8040652b422f371
```

`report_sha256` is intentionally omitted. The provenance generator must
calculate it from the final canonical checked-in review bytes; embedding a
report's own final hash in the report is self-referential.

## Exact reviewed target

- Worktree:
  `E:\\AI\\ChatAI\\Agents\\VibeCodingProjects\\elftia\\elftia\\elftia-plugin-document-skills-wt-pptx-b6`
- Branch: `feat/pptx-ecosystem-phase-bc-b6`
- Base and HEAD:
  `origin/main@b7c033630e99fed929ac0601852231e2a437d84b`
- Candidate form: complete repaired live uncommitted worktree delta, including
  every tracked and untracked release file
- PR at review time: none
- Reviewed mapping SHA-256:
  `45011341001a17f376dfb65f61d0aea701c36978a17a84e5a8040652b422f371`
- Regenerated inventory: 613 modules, 201 data classifications, 3 metadata
  exclusions, 0 pre-binding review attestations

The mapping was regenerated independently in memory immediately before this
report. The regenerated manifest exactly equals the checked-in repaired,
unbound `provenance/modules.json`.

## Scope and review-cycle disposition

This reviewer did not author the B6-005 fix. The repaired delta was inspected
against the complete release diff under the `rasen-review` report-only rules,
with the `rasen-review-cycle` author-not-verifier invariant preserved.

Review-cycle disposition:

| Finding | Prior state | Repaired state | Non-author disposition |
|---|---|---|---|
| B6-001 | closed | unchanged and regression-green | closed |
| B6-002 | closed | unchanged and regression-green | closed |
| B6-003 | closed | unchanged and regression-green | closed |
| B6-004 | accepted-known Minor | unchanged | accepted-known |
| B6-005 | open before repair | explicit group hierarchy plus verified package correspondence | closed |

The complete release review covered equation AST/LaTeX/OMML behavior,
transactional equation upsert, typed create/template/slide-add integration,
mapping and selector safety, branch-aware AlternateContent drawing-ID
validation, agent-facing guidance, fixtures, public contracts, provenance
profiles, release inventory, and the repaired HTML scene hierarchy.

## B6-005 — CLOSED — explicit pseudo-layer group hierarchy

### Normalized structure

`scene_normalizer.py` now turns an HTML item with simple pseudo content into
one transparent explicit group retaining the original source identity. A
visible element box becomes a `:box` child; `::before`, editable text
`:content`, and `::after` become sibling children of that group. The group
has no visible fill, border, text, or asset, so it contributes hierarchy
without duplicating the rendered box.

The repaired regression proves the exact normalized structure:

```text
card                group       parent=None
├─ card:box         rectangle   parent=card
├─ card:before      text        parent=card
├─ card:content     text        parent=card
└─ card:after       text        parent=card
```

The box retains the original geometry, fill, border, opacity, and rotation but
has no text. The content layer retains editable paragraphs/runs while removing
box fill/border. Pseudo layers retain their captured absolute geometry and
text styles.

### Deterministic identities and z-order

The capture pipeline normalizes each item to a four-slot paint interval:
parent `4n+1`, `::before` `4n+2`, content `4n+3`, and
`::after` `4n+4`. The repaired group and box share the parent slot; the
normalizer's stable `(paint_order, dom_index, source_id)` ordering places the
original group identity before its `:box` identity. The next source item
starts at `4(n+1)+1`, so the group subtree remains contiguous.

`emit_scene_objects()` walks roots and their ordered children
deterministically, allocates shape IDs sequentially from 2, and records
`z_order` from manifest insertion order. Duplicate identities, cycles, and
unreachable hierarchy are rejected rather than silently reordered.

### Geometry and package correspondence

The emitted `p:grpSp` uses the group's global geometry for `a:off`,
`a:ext`, `a:chOff`, and `a:chExt`. Because child coordinates stay in the
same captured global coordinate space, equal parent/child coordinate origins
preserve each box, pseudo, and content layer's geometry.

The required scene-to-package correspondence gate independently reconstructs
the expected manifest and verifies:

- exact object and media counts;
- sequential deterministic OOXML shape IDs and source names;
- leaf z-order;
- group versus leaf XML kinds;
- text run correspondence;
- emitted and in-bounds geometry;
- parent source identities;
- media hashes and one-to-one manifest correspondence.

The exact public reproduction passed with 10 objects, 3 media parts,
`one_to_one_manifest=true`, `finite_in_bounds_geometry=true`, and
`deterministic_ids=true`.

### Non-group parent rejection remains enforced

Before any object emission, `scene_group_emitter.py` resolves every
`parent_source_id` and requires the referenced item to exist with
`kind == "group"`. A child of a missing or non-group parent raises
`DS_VALIDATION_FAILED`; the dedicated regression confirms that the output
PPTX is not created.

## Previously closed findings

### B6-001 — equation classification remains envelope-specific

Dedicated bare shapes and generated AlternateContent wrappers are classified
as equations only when their exact supported structure matches the equation
envelope. Mixed text/math shapes, groups, multiple-math containers, and
malformed wrappers retain ordinary behavior; forged equation selectors are
rejected before staging.

### B6-002 — typed text normalization remains symmetric

Typed request normalization and native OMML readback share NFKC and
Unicode-minus canonicalization. Ambiguous typed underscore, whitespace, and
Greek input is rejected in favor of structural script and named symbol nodes.

### B6-003 — AlternateContent drawing IDs remain branch-aware

Every Choice and Fallback branch is validated independently against common and
external identifiers. Invalid or colliding branch identifiers fail deep
validation, while valid same-identity reuse across mutually exclusive branches
remains accepted.

## Accepted-known Minor

### B6-004 — formal Rasen artifact traceability

The original Core PPTX `proposal.md`, `design.md`, `tasks.md`, and delta
spec do not formally specify this later B6 editable-equation slice. The release
implementation, agent-facing contract, direct tests, fixtures, and provenance
profiles are present, so this remains accepted documentation/process debt
rather than a functional release defect.

Task 11.3 remains incomplete until actual remote Windows, macOS, and Linux
results are observed. A local skip or unavailable consumer is not consumer
success.

## Final verification evidence

Environment for Python commands:

```text
DOCUMENT_SKILLS_PROVIDER_PROFILE=core-only
DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=0
```

1. Exact B6-005 public reproduction:
   `uv run --project . --frozen python -m pytest
   tests/test_html_pptx_public.py::test_public_nested_wrappers_shape_fallback_and_pseudo_layers_are_truthful
   -q` — **1 passed**.
2. HTML scene/emitter/public focused suite:
   `uv run --project . --frozen python -m pytest
   tests/test_html_scene.py tests/test_html_scene_emitter.py
   tests/test_html_pptx_public.py -q` — **31 passed**.
3. B6 equation/group/deep-validation suite:
   `uv run --project . --frozen python -m pytest
   tests/test_pptx_equation.py tests/test_pptx_equation_contracts.py
   tests/test_pptx_deep_validation.py -q` — **52 passed**.
4. Targeted Ruff over the repaired normalizer and its HTML regressions —
   **All checks passed**.
5. `git diff --check` and `git diff --cached --check` — passed.
6. Changed-file scan: 52 text files strictly decoded as UTF-8; 0 BOM,
   0 U+FFFD, and 0 typical mojibake matches.
7. JSON scan: all 8 changed JSON files parsed successfully.
8. Final in-memory provenance regeneration:
   `45011341001a17f376dfb65f61d0aea701c36978a17a84e5a8040652b422f371`;
   generated manifest exactly equals the checked-in repaired unbound manifest.
9. Current audit metadata reports all inventory, execution-boundary, command,
   fixture, manifest, public-skill, clean-room, and SBOM checks passing. Its
   only error is the expected missing independent review attestation.

## Coverage conclusion

```text
HTML ITEM WITH SIMPLE PSEUDO CONTENT
  -> explicit transparent group with original source identity
  -> optional :box + before/content/after sibling children
  -> stable four-slot paint order and sequential shape IDs
  -> exact group/leaf geometry and manifest correspondence      [CLOSED]

CHILD WITH MISSING OR NON-GROUP PARENT
  -> rejected before object emission
  -> DS_VALIDATION_FAILED
  -> no output package                                          [CLOSED]

EQUATION ENVELOPE / TYPED TEXT / ALTERNATECONTENT IDS
  -> prior B6-001..003 regressions remain green                 [CLOSED]
```

## Evidence boundary and required next action

- No remote CI, PowerPoint, LibreOffice, push, PR, or merge result is claimed.
- The in-repository B6 review file remains the repaired unbound PENDING
  placeholder at this review point; this reviewer did not alter it.
- The LEAD must place these final report bytes at
  `provenance/reviews/document-skills-0.5.3-pptx-b6-merge-review.md`, bind the
  new attestation through the canonical provenance flow, regenerate derived
  audit bytes, and rerun release verification.
- The old `bbf92...` digest, report hash, and reviewer identity must not be
  reused.

No implementation, test, fixture, release index, provenance file, PENDING
placeholder, run-state, Git index, commit, remote, or PR state was changed by
this reviewer. The only persistent write made by this reviewer is this
canonical external `review-report.md`.
