# Producer Scripts

## Purpose

These Node scripts own standalone dependency preparation, test/audit orchestration, deterministic artifact construction, artifact validation, reproducibility checks, and focused documentation verification.

## Ownership and boundaries

Producer scripts operate on this repository and the emitted `dist/document-skills/` artifact. They do not search for an Elftia checkout, synchronize host resources, mutate user documents, create remotes, push, publish packages, or install optional Office/browser/OCR providers.

Exact Python and Node dependency installation occurs only in verification/build preparation with lifecycle scripts disabled. Document operations never call these producer scripts.

## Entry points

| Script | Responsibility |
| --- | --- |
| [`verify-readmes.mjs`](verify-readmes.mjs) | README inventory, UTF-8, local links, package commands, and registered-operation coverage |
| [`run-plugin-checks.mjs`](run-plugin-checks.mjs) | Frozen Node/Python preparation, Python suite, compile check, and plugin audit |
| [`verify.mjs`](verify.mjs) | Documentation/repro tests, plugin checks, artifact build, and artifact revalidation |
| [`artifact.mjs`](artifact.mjs) | Selected release tree build/validation orchestration |
| [`build-artifact.mjs`](build-artifact.mjs) | Build CLI for `dist/document-skills/` |
| [`validate-artifact.mjs`](validate-artifact.mjs) | Validate the emitted artifact independently |
| [`verify-reproducible-build.mjs`](verify-reproducible-build.mjs) | Compare repeated clean builds |
| [`run-xlsx-dist-e2e.mjs`](run-xlsx-dist-e2e.mjs) | Build and exercise XLSX through the distribution artifact |

Use package scripts rather than invoking orchestration internals by hand:

```text
npm run verify:docs
npm test
npm run build
npm run validate:artifact
npm run verify
npm run verify:repro
```

## Safety and failure semantics

Inventory paths must be normalized, ordinary, contained files without symlink/reparse escapes or case-fold collisions. Artifact replacement and cleanup are scoped to validated repository-owned build targets. A dependency, test, audit, inventory, hash, build, or verification failure stops the pipeline.

Scripts never force a publish or downgrade failed checks. Release packaging is local unless an explicit later workflow performs external delivery.

## Verification

Script unit tests live in [`__tests__/`](__tests__/) and run from the aggregate gate:

```text
node --test scripts/__tests__/*.test.mjs
npm run verify:docs
npm run verify:repro
```

## Related documentation

- [Repository producer guide](../README.md)
- [Plugin runtime](../plugin/README.md)
- [Plugin tests](../plugin/tests/README.md)
- [Provenance](../plugin/provenance/README.md)
- [Distribution E2E](../e2e/README.md)
