# CLEAN — Document Skills 0.5.3 PPTX B2 Final Review

Date: 2026-08-26

## Verdict

Status: `clean`

Approval claimed: `true`, limited to the exact `all-release-artifacts`
mapping identified below.

Canonical findings: **0 Blocker, 0 Major, 0 Minor**.

The independently regenerated all-release-artifacts mapping contains **573
release files**: **435** risky module records, **135** exact-hash data
classifications, **0** executable exclusions, exactly **3** self-referential
metadata exclusions, and **0** pre-existing review attestations. Its SHA-256
is:

`3cbdace427acaaafbd73c789a7e4f306af469ed96668905b0b56dd1ee78b8241`

This approval binds only to that exact semantic mapping. Any release-artifact
change outside the defined self-referential review fields requires a new
mapping digest and independent review.

## Reviewer identity

- Reviewer: `Codex collaboration subagent /root/b2_adversarial_review`
- Identity: `codex-reviewer/document-skills-0.5.3-pptx-b2-final/fresh-non-author-2026-08-26`
- Runtime: `codex`
- Role: `reviewer`
- Scope: `all-release-artifacts`
- Identity assurance: `self-asserted`
- Report id: `document-skills-0.5.3-pptx-b2-merge-review`
- Identity limitations: This self-asserted identity cannot cryptographically
  prove the backing model, service principal, or human operator. It does not
  replace maintainer approval and does not establish remote CI, pull-request,
  merge, live Microsoft PowerPoint, live LibreOffice, live .NET/OpenXML, or
  unobserved operating-system behavior.

This reviewer did not author the implementation, tests, provenance profiles,
runtime allowlist, generator, or delivery changes under review. The main agent
retains responsibility for implementation, manifest binding, commit, push,
pull request, and merge.

## Reviewed target

- Branch: `feat/pptx-ecosystem-phase-bc-b2`
- Base: `origin/main@0a6e66492fbab4ffa4010c2ebd4c0f6fe8cfd5dc`
- Worktree HEAD before delivery:
  `0a6e66492fbab4ffa4010c2ebd4c0f6fe8cfd5dc`
- Reviewed state: the complete current working-tree release inventory relative
  to the base, including untracked release artifacts selected by the shared
  inventory policy.
- Mapping SHA-256:
  `3cbdace427acaaafbd73c789a7e4f306af469ed96668905b0b56dd1ee78b8241`
- Runtime source allowlist SHA-256:
  `6c7fe6cadca8879ab262eb915617d9e867d8e24bdf072de42b78a0b03ff6d768`

The reviewed plugin worktree includes 64 tracked-file deltas relative to the
base (8114 insertions and 1338 deletions) plus the release-inventoried hardening test
and this self-referential review artifact. Both untracked files were explicitly
confirmed present in the 573-file release inventory.

## Review scope and result

The review covered the B2 semantic-template implementation and its final
hardening delta: descriptor-bound structural inspection, tolerant versus
strict semantic projection, catalog and template hash binding, commercial
license fail-closed behavior, optional contact-sheet evidence, stable-slot
materialization, binding receipts, physical purge, content lint, bounded image
handling, repeated-page resource limits, output object identity, public path
resolution, operation-specific worker timeouts, runtime source classification,
fixture data, and exact provenance profiles.

The final supervisor delta places `pptx.template.sanitize` in the same bounded
45-second public mutation budget as the other PPTX mutation operations while
leaving unrelated operations at their existing limits. The public timeout
test verifies the exact operation mapping, including the 150-second template
inspection budget.

The final provenance correction removes the broad `template_*` B2 classifier
that had incorrectly captured four unchanged legacy modules. The B2 profile
now names the eight new semantic-template modules explicitly. Fresh
regeneration proves these legacy modules retain their original requirement:

- `template_create.py`
- `template_lint.py`
- `template_sanitize.py`
- `template_sanitize_inventory.py`

Each remains classified as
`Rasen document-skills-foundation strategy-attempt-3`, has no B2 profile, and
does not bind the B2 hardening test. The regression test checks both the direct
profile functions and the freshly regenerated records.

The current review pointer exactly names this report. The report and
`tests/test_pptx_template_b2_hardening.py` are both included by
`release_artifacts()`. The checked-in runtime source allowlist is JSON-equal to
a fresh `runtime_source_allowlist()` scan and contains 276 Python sources and
10 Node sources.

The final test-fixture correction also verifies overlapping data ownership
instead of assuming HTML ownership is exclusive. `skills/document-pptx/`
records that match both HTML and B2 now combine both modifications and both
test sets and use requirement
`Rasen html-to-editable-pptx + pptx-ecosystem-phase-bc-b2`. The deterministic
review fixture now derives its default report from `CURRENT_REVIEW_ARTIFACT`,
so temporary audit copies bind this B2 report while the historical XLSX review
remains exact-hash reviewed data rather than self-referential metadata.

The final generator correction also preserves cross-workstream ownership when
XLSX data is classified. Pure XLSX data no longer passes an empty base into
requirement composition, so it cannot emit malformed values such as
`Rasen  + ...`. A fresh mapping scan found 15 pure XLSX data records, all with
non-empty canonical requirements and no empty component. The runtime source
allowlist is jointly owned and now records the exact requirement
`Rasen pptx-ecosystem-phase-bc-b2 + document-skills-core-xlsx + document-skills-xlsx-completion + document-skills-xlsx-advanced-authoring`.
Its modifications and direct tests combine the B2 runtime policy with the
Core, completion, and advanced XLSX execution-boundary evidence. Strategy 2
uses `CURRENT_REVIEW_ARTIFACT` for its current-review assertion, while Strategy
3 checks the combined runtime requirement and descriptions.

All earlier implementation findings and the later Major provenance
over-classification finding were re-reviewed after remediation. No finding
remains in the bound mapping.

## Independent verification evidence

- `git diff --check` — passed.
- `python -m tools.regenerate_provenance --project-root . --print-mapping-only`
  — produced
  `3cbdace427acaaafbd73c789a7e4f306af469ed96668905b0b56dd1ee78b8241`.
- A separate in-process call to `tools.regenerate_provenance.regenerate()`
  independently produced the same digest and the 435/135/3 mapping counts.
- A separate `release_artifacts()` scan counted 573 files and confirmed both
  the hardening test and this review report in the release inventory.
- The checked-in runtime source allowlist was parsed with strict UTF-8 JSON and
  compared structurally with `runtime_source_allowlist()`; the values matched
  exactly at 276 Python and 10 Node entries.
- Focused final tests:
  `pytest -q tests/test_html_provenance.py::test_template_b2_profiles_are_exact_and_do_not_capture_unrelated_pptx tests/test_html_pptx_public.py::test_provider_operations_have_private_public_budgets_without_relaxing_existing_commands`
  — **2 passed**.
- Focused final fixture-drift tests were invoked through `pytest.main` after
  pinning the repository-local `tests/` namespace:
  `tests/test_html_provenance.py::test_html_pptx_release_records_use_truthful_requirement_and_tests`,
  `tests/test_supply_chain.py::test_historical_review_reports_are_hash_pinned_reviewed_data`,
  and
  `tests/test_supply_chain.py::test_current_review_metadata_binding_uses_an_exact_allowlist`
  — **4 passed** including parameterized cases.
- Focused final generator tests were invoked through `pytest.main` after
  pinning the repository-local `tests/` namespace:
  `tests/test_strategy2.py::test_current_review_is_the_only_hashless_review_metadata`,
  `tests/test_strategy3.py::test_xlsx_data_provenance_respects_change_boundaries`,
  and
  `tests/test_strategy3.py::test_shared_xlsx_nuget_data_provenance_is_exact_and_composed`
  — **3 passed**.
- Independent fresh-record inspection found 15 pure XLSX data records, zero
  missing requirements, and zero empty or doubled requirement components. It
  confirmed the runtime allowlist's combined B2+XLSX requirement,
  modifications, 43 deduplicated test references, and exact structural match
  to the 276-Python/10-Node runtime scan.
- Strict UTF-8 decoding, BOM rejection, mojibake-marker checks, and `ast.parse`
  passed for the final supervisor, public timeout test, provenance profiles,
  provenance tests, review pointer, and hardening test. The runtime allowlist
  parsed as JSON.
- Earlier in this same independent review, the B2 implementation and hardening
  suites completed **21/21 passed**. The later deltas were confined to the
  supervisor budget and provenance/review binding described above.
- The binding-relevant hardening review checked final-object receipt hashes,
  unused-relationship leakage rejection, relative descriptor and binding-image
  paths, aggregate image and repeated dependency budgets, repeated slot
  cardinality, stable-key collision rejection, and the pre-hash source-size
  gate.

## Evidence boundary

This is a local review of exact repository bytes and their semantic provenance
mapping. No remote CI, GitHub status, pull request, or merge state was queried
or treated as evidence. The repository-wide pytest suite, full provider suite,
Node verification, reproducibility suite, live Microsoft PowerPoint, live
LibreOffice, and real .NET/OpenXML provider were not run in this final narrow
binding pass.

An attempted broader local regression earlier in the review was stopped after
shared provider-process contention was identified; it is not claimed as pass
evidence. Visual/contact-sheet behavior is attested only to the reviewed code
paths and tests, not to an independently observed live renderer. The final
bound `provenance/modules.json` is expected to be generated by the main agent
after this self-referential report is written; this reviewer approves binding
that manifest only if regeneration retains the exact mapping digest above.
The main agent's final combined HTML-provenance and supply-chain run reached
only the expected stale generated audit/manifest assertion before this new
digest was bound; that run is not claimed as an all-green independent result.
The main agent separately reported the complete Strategy 2/3 suites passing
181/181 after the final generator and expectation corrections; the three
binding-critical cases above were also rerun independently by this reviewer.

## Attestation

I attest that the Codex reviewer identified above independently reviewed the
current PPTX B2 implementation, its remediation deltas, release inventory,
runtime allowlist, and exact all-release-artifacts semantic mapping and found
**0 Blocker, 0 Major, and 0 Minor** issues within scope. I approve this report
as the clean independent review attestation for mapping SHA-256
`3cbdace427acaaafbd73c789a7e4f306af469ed96668905b0b56dd1ee78b8241`
and no other mapping.
