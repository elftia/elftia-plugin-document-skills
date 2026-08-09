# CLEAN - document-skills-core-xlsx review cycle round 1 (fresh non-author)

Date: 2026-07-27

## Verdict

Status: `clean`

Approval claimed: `true`

Canonical findings: **0 Blocker, 0 Major, 1 Minor, 0 Trivial**.

The single Minor (M1: generic provenance text for XLSX modules in `_module_record`) does not affect the mapping digest, module hashes, clean_room flag, license, security, formula integrity, or any acceptance criterion. It is a non-blocking cleanup item.

This approval covers exactly the release mapping identified below. It does not approve a future
mapping whose product or test bytes, inventory, or classifications differ.

## Reviewer

- Reviewer: `claude-reviewer/document-skills-core-xlsx/review-cycle-round-1/fresh-non-author`
- Identity: `claude-reviewer/document-skills-core-xlsx/review-cycle-round-1/fresh-non-author`
- Runtime: `claude`
- Role: `reviewer`
- Scope: `all-release-artifacts`
- Identity assurance: `self-asserted`
- Identity limitations: This self-asserted reviewer cannot cryptographically prove its backing identity and does not independently establish remote CI execution or external review-service attribution.
- Attestation id: `document-skills-core-xlsx-review-cycle-round-1`

## Mapping and report evidence

- Canonical 187-entry mapping SHA-256 (before this report): `e93fdbf5b5400550f5feffc0ee2305f8af378d3935bb773b3fe1fb30b503dd0d`
- Reviewed prospective mapping SHA-256 (188 entries, this report included as self-referential
  audit-metadata): `3c24bd5a04e71eda731db02cd0eb16f7528727b92e24ef15c48e917226edfb6e`
- External WorkDir report: `work/review-report.md`
- External report verdict and counts: `CLEAN`; 0 Blocker, 0 Major, 1 Minor, 0 Trivial.

## Attestation

I attest that I independently reviewed the complete `document-skills-core-xlsx` delta against the
active Slice `core-xlsx-formula-integrity` acceptance criteria, the change proposal/design/specs,
and the DOCX sibling reuse contract. I ran the frozen test suite, regenerated provenance, ran the
doctor, and exercised a real frozen-uv `xlsx.edit` that confirmed dependent formula invalidation
and result downgrade to `degraded`. The formula-state invariant (the Slice differentiator) holds
at three independent layers — derivation impossibility, summary detection, and assertion
enforcement — and an adversarial test proves `ValueError` is raised when a cell falsely claims
`recalculated` without an accepted provider. No code path can produce `recalculated` without a
provider. I approve binding this attestation to the exact prospective 188-entry mapping digest
`3c24bd5a04e71eda731db02cd0eb16f7528727b92e24ef15c48e917226edfb6e`.

## Findings

### Minor (non-blocking)

**M1: `_module_record` provenance text is generic for XLSX modules.**
`tools/regenerate_provenance.py:_module_record` distinguishes DOCX modules but has no `is_xlsx`
branch. XLSX modules receive the generic foundation strategy-attempt-3 `requirement_source`,
`modifications`, and `artifact_tests`. This does not affect the mapping digest (module path +
sha256 only), module hashes, clean_room flag, or license — all correct. Non-blocking cleanup for
a future provenance refresh.

## What the review independently confirmed

- Formula-state invariant: `derive_read_state` with `recalculation_provider=None` NEVER returns
  `recalculated`; `derive_create_state` returns `stale`/`recalculation_required`;
  `derive_edit_state` returns `recalculation_required`. `assert_invariant` raises `ValueError`
  for unverified `recalculated`. Adversarial test
  `test_invariant_fails_with_unverified_recalculated` confirms.
- Real frozen-uv `xlsx.edit`: editing precedent A1 invalidates dependent B1 to
  `recalculation_required`; result status `degraded`; `outstanding_recalculation_required: 1`;
  `recalculation_provider: unavailable`. Zero cells report `recalculated`.
- Copy-through preservation: `OpcPackage.write_copy` verifies preserved-part payload hashes and
  raises on mismatch; `validate_mutation` → `_assert_preservation` fails on any removed part.
- Security: `inspect_ooxml` with REJECT/PRESERVE_DISABLED policies; `defusedxml` parsing;
  duplicate/traversal member detection; bounded archive limits; `_exact_keys` rejects unknown
  arguments before file access.
- Containment: no MCP/adapter/daemon/hook/`.codex-plugin`; all SKILL.md commands use
  `uv run --project ... --frozen`; no openpyxl/SheetJS/Node imports; XLSX uses `core-python`
  provider only.
- Provenance tooling edit: both `_is_metadata` and `validate_metadata_exclusion` add
  `core-xlsx-review-cycle-round-1.md` mirroring the existing docx/foundation entries exactly.
- Reuse: XLSX composes foundation `OperationTempRoot`, `inspect_ooxml`, `SchemaCatalog`,
  `validate_artifact`, `atomic_promote`, etc. No second schema forked.
- Focused regression: 111 XLSX + safety + supply-chain tests passed, exit 0.
- Canonical 187-entry mapping reproduced from final bytes matches
  `e93fdbf5b5400550f5feffc0ee2305f8af378d3935bb773b3fe1fb30b503dd0d`.

## External evidence boundary

Actual remote Windows/macOS/Linux workflow results are absent and are not claimed. The authored
CI matrix is not treated as execution evidence. All probes were exercised on Windows 11 only;
POSIX path behavior was reasoned from source.
