# Distribution End-to-End Tests

## Purpose

This directory owns end-to-end checks that execute the built `dist/document-skills/` artifact instead of importing producer source directly. The current checked-in slice covers the XLSX distribution surface.

## Ownership and boundaries

Distribution E2E proves artifact packaging, frozen entry points, public requests, feature coverage, output promotion, and independent reopen for its declared cases. It does not by itself prove installed-host seeding, every optional provider, every Office consumer, or remote CI.

Real PowerPoint/LibreOffice/browser/OCR runs belong in explicit evidence reports with the executable identity, artifact hash, command, and outcome. A consumer crash, missing adapter, skip, or unexecuted CI remains that exact state.

## Entry points

[`xlsx_dist/`](xlsx_dist/) contains the current feature manifest, support helpers, and public distribution tests. Run it from the producer root:

```text
npm run test:xlsx:dist-e2e
```

The runner builds the artifact first, creates isolated temporary state, calls the artifact's public façade, and checks the declared feature node ids.

## Safety and failure semantics

E2E writes only to explicit temporary/output locations, preserves source fixtures, uses frozen dependencies, and must not provision optional providers or mutate a host checkout. Unsupported or unavailable boundaries are asserted as truthful results rather than bypassed with direct provider calls.

Owned processes and temporary resources must be cleaned after success, failure, timeout, or interruption.

## Verification

Run the distribution slice after deterministic documentation and producer checks:

```text
npm run verify:docs
npm run test:xlsx:dist-e2e
```

The 2026-08-28 PPTX B7 real-consumer evidence is recorded with the [product implementation PR](https://github.com/elftia/elftia-plugin-document-skills/pull/19) and [planning/evidence PR](https://github.com/elftia/eltia-store/pull/11). It records PowerPoint success, non-PPTX LibreOffice success, a local LibreOffice Impress control crash with product fail-closed behavior, no configured production OCR/vision adapter, and no CI execution.

## Related documentation

- [Repository verification](../README.md#verification)
- [Producer scripts](../scripts/README.md)
- [Plugin tests](../plugin/tests/README.md)
- [Consumer validation](../plugin/consumer_validation/README.md)
- [XLSX module](../plugin/src/document_skills_core/formats/xlsx/README.md)
- [PPTX module](../plugin/src/document_skills_core/formats/pptx/README.md)
