# Plugin Audit and Evidence Tools

## Purpose

This module contains producer/runtime audit, provenance generation, command discovery, release inventory, policy-flow analysis, and bounded Office/PPTX evidence utilities shipped with the plugin artifact.

## Ownership and boundaries

Tools support verification and evidence capture; they are not Agent-visible document operations. Public document work must enter through a format Skill. Audit tools may read the plugin tree and explicit local evidence inputs but must not discover or mutate an Elftia checkout, publish packages, install dependencies, or weaken release classification.

Evidence capture utilities do not turn a consumer run into a general support claim. Provenance generation computes records; it does not provide the independent review those records require.

## Entry points

- [`audit.py`](audit.py) orchestrates structural, fixture, provenance, and release audits.
- [`release_inventory.py`](release_inventory.py) enumerates and classifies exact release bytes.
- [`regenerate_provenance.py`](regenerate_provenance.py) regenerates mapping and runtime-source metadata to explicit output paths.
- [`supply_chain.py`](supply_chain.py) validates dependency/SBOM/notice evidence.
- `python_policy_*` and [`node_policy.mjs`](node_policy.mjs) own bounded static execution/value-flow checks.
- `capture_*` and `prepare_*` utilities create explicit local PPTX consumer evidence.

Use `--help` through the frozen plugin environment before any write-capable evidence command.

## Safety and failure semantics

Exact paths, hashes, portable identities, output locations, and review state are validated before writes. Unknown or opaque release artifacts fail closed. Tools must emit bounded, sanitized evidence and must not expose credentials, raw environments, or unrelated user data.

Consumer automation may launch installed applications only for an explicit evidence task and must clean up owned processes. A crash/timeout is evidence of that boundary, not permission to retry indefinitely or report success.

## Verification

Audit and tool behavior is covered by supply-chain, structure, policy, provenance, and evidence tests in the [plugin test suite](../tests/README.md). The [producer verification guide](../../scripts/README.md) owns the exact focused and aggregate commands.

## Related documentation

- [Provenance](../provenance/README.md)
- [Tests](../tests/README.md)
- [Producer scripts](../../scripts/README.md)
- [Consumer validation](../consumer_validation/README.md)
- [Provider architecture](../src/document_skills_core/providers/README.md)
