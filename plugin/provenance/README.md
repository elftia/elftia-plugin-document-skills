# Provenance and Release Audit

## Purpose

This module records the exact origin, review, license, classification, hashes, and test evidence for every file emitted in the `document-skills` release inventory.

## Ownership and boundaries

The release inventory is fail closed: every non-generated file under `plugin/` is a release candidate unless the shared policy names an exact worktree-only class. Executable/risky locations and bytes require explicit reviewed module records; ordinary data and fixtures require exact classification. Unknown files do not inherit a broad directory exclusion.

Provenance metadata is evidence, not a dependency installer or legal conclusion. Self-referential audit metadata has a narrow reviewed classification because raw self-hashing would be circular.

## Entry points

- [`modules.json`](modules.json) maps release files to hashes, requirement sources, review, licenses, and tests.
- [`runtime-source-allowlist.json`](runtime-source-allowlist.json) records the exact executable Python/Node source set for value-flow audit.
- [`audit-report.json`](audit-report.json) records the current aggregate audit result.
- [`dependency-allowlist.json`](dependency-allowlist.json), [`dependency-licenses.json`](dependency-licenses.json), [`../sbom.cdx.json`](../sbom.cdx.json), and [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) cover dependency evidence.
- [`reviews/`](reviews/) contains independent implementation/release reviews; [`parity/`](parity/) contains bounded parity evidence.

Generation and validation tools live in [`../tools/`](../tools/README.md).

## Safety and failure semantics

Regeneration computes a new mapping but does not constitute independent review. New or changed release bytes must not reuse an old attestation as if the reviewer saw them. Pending review remains explicit; it does not block the official automated release when inventory, hashes, and other audits pass.

Hash drift, missing classification, unexpected executable bytes, portable path collisions, opaque unclassified data, dependency drift, or mismatched SBOM/audit metadata blocks release verification.

## Verification

The [producer verification guide](../../scripts/README.md) owns the exact audit and prospective-mapping commands. Prospective mapping generation does not write or review metadata, and the aggregate producer gate runs the audit without treating regeneration as independent attestation.

## Related documentation

- [Plugin runtime](../README.md)
- [Plugin tools](../tools/README.md)
- [Tests](../tests/README.md)
- [Producer scripts](../../scripts/README.md)
- [Clean-room policy](clean-room-policy.md)
- [Top-level provenance statement](../PROVENANCE.md)
