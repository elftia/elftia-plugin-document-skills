# Document Skills 0.5.6 exact-byte independent review

- Date: 2026-08-31
- Repository: `elftia-plugin-document-skills`
- Branch: `main`
- Base: `18b6ec1d93978e5fad488283ac8a2da78cd0a9fb` (`origin/main`)
- HEAD: `061d92fed0b1dc60f94fccea8877eef399972c29`
- Reviewer: Codex exact-byte independent reviewer
- Reviewer identity: `codex-reviewer/elftia-plugin-document-skills/0.5.6-exact-bytes`
- Runtime / role: `codex` / `reviewer`
- Identity assurance: `self-asserted`
- Scope: `all-release-artifacts`
- Status: `clean`
- Approval claimed: `true`
- Reviewed mapping SHA-256: `ce9870259843e8cc59cedb53ca78aa907a6b5d01ee345362cce6cb1240bbce26`

## Verdict

The final 0.5.6 candidate has **0 Blockers and 0 Majors**. The earlier version
identity and invalid-attestation Blockers are closed. The follow-up Strategy-2
Blocker is also closed: both stale `core-pdf-review-cycle-round-1.md` test
expectations now use `CURRENT_REVIEW_ARTIFACT`, the stale PDF-specific test
names were corrected, and the complete `tests/test_strategy2.py` file passes.

This clean decision covers the full `origin/main...HEAD` change and the final
uncommitted blocker-fix delta. I inspected the repository files and exact
candidate bytes directly; this report does not reuse the previous invalid
approval or treat provenance generation as independent review.

## Exact mapping and provenance evidence

- Prospective regeneration and an independent structured recomputation both
  produced mapping digest
  `ce9870259843e8cc59cedb53ca78aa907a6b5d01ee345362cce6cb1240bbce26`.
- The stored manifest equals the regenerated PENDING manifest exactly.
- The inventory contains 1,067 files classified exactly once: 813 executable
  or risky module records, 251 data classifications, no executable exclusions,
  and the exact three permitted self-referential metadata exclusions.
- All 1,064 non-circular records have SHA-256 values matching the current source
  bytes. All 1,067 records remain `PENDING independent review`, and there are no
  pre-bound review attestations.
- All 813 modules are original Elftia, `clean_room: true`, GPL-3.0 records with
  non-empty requirement, implementation, and artifact-test evidence. There are
  51 requirement-source groupings and no adopted-source records.
- Relative to `origin/main`, no existing requirement, implementation-source,
  license, clean-room, or adoption field drifted. The historical parallel-test
  report is hash-pinned `reviewed-data`; only the new current report occupies
  the exact current-review metadata seam.
- The aggregate audit passes inventory, clean-room, execution-boundary,
  command, fixture, manifest, skill, and SBOM checks. Before this report is
  bound, it fails only with the intended `Independent review attestation is
  missing` safety error.

## Runtime, fixtures, and test evidence

- All eleven release identity surfaces in source and in the candidate package
  resolve to `0.5.6`; the focused one-source version test passes.
- Required `node-lock` detection is available and healthy. Doctor reports for
  DOCX, XLSX, PPTX, and PDF are healthy, publish project version `0.5.6`, and
  have no unavailable required runtime or provider.
- The complete Strategy-2 test file passes, including the current-review
  metadata allowlist and report-byte mapping-stability cases.
- All 109 registered fixtures have exact manifest hashes, redistribution and
  license evidence, and existing recipes/dependencies. The foundation, DOCX,
  HTML-to-PPTX, and PDF deterministic recipe checks pass.
- README verification passes 39 tests and validates 18 README files, 246 local
  links, 60 operations, and four package commands.
- Reproducibility unit verification passes four tests, including checkout
  policy and byte-preserving artifact construction.
- `validate:artifact` passes for 1,067 files with inventory SHA-256
  `812e622729690a82a87fc24c400aa0a7a3cce3fb0232121a5859354bfb220459`;
  `elftia-plugin verify` independently accepts the dist tree as document-skills
  0.5.6.

## Package evidence

- The reviewed pre-binding package is a standard ZIP (`50 4b 03 04`) with
  1,067 regular entries, no duplicate or portable-path collision, valid CRCs,
  and exactly one root `elftia-plugin.json`.
- EPKG SHA-256:
  `b25a39c88f30636279c59c23831259e5db61d0e360cdd4923209cb5c49128a1c`
  (2,702,612 bytes).
- Sidecar SHA-256:
  `0dc79bf7f03927e47b234d19511941e888ba100d40f750bc976f890f679863c7`;
  its package digest, byte size, version, kind, id, and 1,067-file count all
  match the EPKG.
- Every package entry matches both `dist/document-skills` and the current source
  inventory byte-for-byte. The package contains no `@elftia/plugin-kit` path or
  content; the producer resolves exactly `@elftia/plugin-kit@0.2.0`.

The release owner must bind this report's final SHA-256 and the reviewed mapping
digest, then regenerate audit, dist, and release outputs. Those binding-only
self-referential bytes are intentionally excluded from the mapping digest, so
the final package will have a new container hash even though the reviewed
mapping digest remains stable.

## Limitations

This reviewer identity is self-asserted by the Codex runtime; the repository
cannot cryptographically prove which service or human principal operated this
review session. The review verifies repository bytes, declared provenance,
policy gates, deterministic fixtures, and the generated package, but it does
not prove the behavior of compromised runtimes, operating systems, native code,
or future code outside the reviewed inventory.

I did not rerun commands that overwrite `dist`, `release`, `modules.json`, or
`audit-report.json`, because the review contract forbids those mutations.
Instead I read and hashed those exact existing outputs, established full
source/dist/EPKG parity, ran the read-only validators, and exercised the
reproducibility tests in their isolated temporary workspaces.

## Durable findings

- A canonical review-path change is a tested release contract; production and
  Strategy-2 metadata tests must move together through the shared SSOT.
- PENDING provenance plus the missing-attestation audit failure is the correct
  pre-review state. Structural generation must never be treated as approval.
- Report binding and final package generation are release-owner operations;
  the independent reviewer supplies the exact report bytes, hash, identity,
  mapping digest, and clean decision without editing provenance manifests.
