# DOCX result guide

The stable top-level result remains the shared Document Skills contract. DOCX-specific data is
always under `diagnostics.operation_result`.

## Operation payloads

- Read: `document.stories`, `document.sections`, `document.images`, selected limits, and explicit
  truncations.
- Inspect: inert policy, `mutation_authorized: false`, sorted parts/content types/relationships,
  media, unknown parts, Word feature counts, sections, and dangerous-content sources.
- Create: creation part/image/section evidence.
- Replace: per-rule/per-story counts, `first-affected-run` formatting policy, protected spans,
  and the preservation manifest.
- Template: sorted used/missing/unused/protected variables, exact backend/version evidence, and
  the preservation manifest.

Artifact records include the normalized path, SHA-256, and byte count. Mutation results include
both input and output records. The input digest is rechecked after success and handled failure.

## Validation

Required gates cover artifact existence/size, ZIP magic/CRC, bounded XML, content types,
relationships, required Word parts, active-content policy, provider reopen, operation semantics,
part preservation, and source preservation where applicable.

`visual.render` and `schema.full` can be `unavailable` while Core succeeds because they are
optional. `unavailable` is never equivalent to `pass` and never raises achieved fidelity.

Provider chains are evidence, not configuration. Read/create/replace/inspect use `core-python`;
the admitted scalar template backend uses `core-node` privately behind Python.
