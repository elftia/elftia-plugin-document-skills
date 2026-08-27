# Document Skills Core

## Purpose

`document_skills_core` is the shared Python implementation behind all four public Skills. It parses versioned requests, enforces portable paths and archive policy, selects callable providers, runs one-shot workers, validates results, and owns transactional output publication.

## Ownership and boundaries

- [`core/`](core/) owns shared contracts, capabilities, I/O safety, process supervision, results, and validation primitives.
- [`public_cli/`](public_cli/) owns the only public command/protocol surface.
- [`worker/`](worker/) owns isolated one-shot execution behind the supervisor.
- [`formats/`](formats/) owns DOCX, XLSX, PPTX, and PDF contracts and implementations.
- [`providers/`](providers/README.md) owns Core and optional provider registration, detection, and bounded adapters.

The Core does not install dependencies, elevate privileges, fetch remote document content, trust provider aggregate claims, or expose raw provider stdout/stderr. Format modules may call shared helpers but may not bypass the public transaction and validation lifecycle.

## Entry points

The public Skill launchers call the supervised Python CLI. Internally, a request follows this sequence:

1. classify arguments and validate the public envelope;
2. snapshot and preflight local inputs;
3. resolve an available callable provider for the exact operation;
4. execute Core or a bounded private provider inside a one-shot worker;
5. validate the nonce-bound result envelope and staged artifact;
6. atomically promote output and verify source preservation;
7. emit exactly one bounded JSON result.

### Format modules

- [DOCX](formats/docx/README.md)
- [XLSX](formats/xlsx/README.md)
- [PPTX](formats/pptx/README.md)
- [PDF](formats/pdf/README.md)

## Safety and failure semantics

Portable-path normalization rejects aliases, in-place outputs, traversal, symlink/reparse escapes, and ambiguous destinations. ZIP/XML/PDF bounds, active-content inventories, immutable selectors, source hashes, provider time/byte ceilings, mandatory reopen gates, and atomic no-replace promotion are shared policy.

Provider detection, execution, and validation are separate states. A detected binary is not callable until identity, dependency, policy, and launch probes pass. Provider failure never authorizes a Core approximation that the operation contract forbids.

## Verification

Core behavior is exercised through public-format tests, cross-format transaction/security tests, runtime crash-isolation tests, and the supply-chain audit. The [plugin test suite](../../tests/README.md) describes coverage ownership, while the [producer verification guide](../../../scripts/README.md) owns the exact commands. The aggregate gate also builds and revalidates the emitted artifact.

## Related documentation

- [Runtime overview](../../README.md)
- [Public Skill catalog](../../skills/README.md)
- [Provider model](providers/README.md)
- [Schemas](../../schemas/README.md)
- [Consumer validation](../../consumer_validation/README.md)
- [Tests](../../tests/README.md)
