# Plugin Test Suite

## Purpose

This directory owns deterministic contracts, public façade tests, transaction/security regressions, provider simulations, environment-gated real-provider tests, fixture validation, supply-chain audits, and private Node tests for the bundled runtime.

## Ownership and boundaries

Tests must distinguish deterministic pass, environment-gated skip, unavailable provider, expected fail-closed result, consumer crash, and remote CI status. A skipped real-provider test is not a passing provider test. Fixtures are inert reviewed data with exact manifest hashes and redistribution policy.

The suite tests public behavior through the frozen façade where the contract requires it; private unit tests may target a bounded implementation seam but do not create a second public API.

## Entry points

- [`fixtures/`](fixtures/) contains generated and reviewed document fixtures plus [`fixtures/manifest.json`](fixtures/manifest.json).
- [`support/`](support/) contains shared request/fixture/evidence helpers.
- [`node/`](node/) contains private Node runtime tests.
- `test_*_public.py` exercises public Skill/provider reporting and result truth.
- Provider/consumer real tests are explicitly gated by executable availability and policy.

The producer harness owns invocation of the complete Python and private Node suites; the release artifact does not expose those developer commands as Agent entry points.

## Safety and failure semantics

Tests use temporary directories and explicit artifacts; they must not overwrite user files, depend on global Python/Node packages, install optional providers, or leave owned Office/LibreOffice processes running. Failure evidence is bounded and sanitized.

Environment-dependent tests must state their gate and preserve skip/failure semantics. Remote CI results are separate from local execution and must not be inferred from a committed test file.

## Verification

The normal producer path prepares the frozen graphs, runs the complete Python and private Node suites, compiles Python into a private temporary bytecode root, and runs the audit. Focused documentation and distribution XLSX E2E remain separate gates. The [producer verification guide](../../scripts/README.md) owns all exact commands.

## Related documentation

- [Runtime overview](../README.md)
- [Shared Core](../src/document_skills_core/README.md)
- [Consumer validation](../consumer_validation/README.md)
- [Provider architecture](../src/document_skills_core/providers/README.md)
- [Provenance](../provenance/README.md)
- [Distribution E2E](../../e2e/README.md)
