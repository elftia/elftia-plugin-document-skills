# Elftia Document Skills Producer

## Purpose

This repository is the canonical standalone producer for Elftia's `document-skills` bundle. It owns the reviewed source, exact Python and Node locks, schemas, tests, provenance, SBOM, build tooling, and deterministic artifact emitted at `dist/document-skills/` after a build.

The bundled runtime exposes four narrow Agent Skills—DOCX, XLSX, PPTX, and PDF—through one frozen uv/Python façade. Start with the [runtime overview](plugin/README.md) when integrating the bundle and the [Skill catalog](plugin/skills/README.md) when choosing a format.

## Ownership and boundaries

- Authoring source lives under [`plugin/`](plugin/); host consumers read only the verified `dist/document-skills/` artifact.
- Producer commands do not discover or modify an Elftia checkout, synchronize host resources, create remotes, push, publish packages, or mutate user documents.
- Python owns the public protocol, path policy, transactions, validation, and the only stdout result. Node, LibreOffice, .NET/OpenXML, browser, and OCR/vision components are private capability-gated providers.
- Missing optional providers are normal availability outcomes. They are never installed silently and are never reported as passing because a weaker Core check succeeded.

## Entry points

Requires Node 20 or newer and [uv](https://docs.astral.sh/uv/). From the repository root:

```text
npm ci --ignore-scripts
npm run verify:docs
npm run verify
npm run verify:repro
```

`npm run verify:docs` validates the README hierarchy and executable references. `npm run verify` prepares frozen dependencies, runs the producer suite and audits, builds and validates the artifact, verifies the plugin package, and creates the release package. `npm run verify:repro` compares two clean artifact builds byte-for-byte.

Agent-visible document commands are documented in the [plugin entry point](plugin/README.md). Build and release command ownership is documented in [`scripts/README.md`](scripts/README.md).

### Capability map

| Skill | Core ownership | Optional boundaries | Module guide |
| --- | --- | --- | --- |
| `document-docx` | Direct OOXML read, inspect, create, edit, merge, semantic compare | LibreOffice rendering/conversion; .NET/OpenXML revisions, comments, schema | [DOCX](plugin/src/document_skills_core/formats/docx/README.md) |
| `document-xlsx` | Direct OOXML/tabular read, inspect, authoring, conversion, summary, pivot | LibreOffice recalculation/render/legacy conversion; .NET/OpenXML schema | [XLSX](plugin/src/document_skills_core/formats/xlsx/README.md) |
| `document-pptx` | Direct OOXML read, inspect, typed authoring/editing, SVG/template/scene flows | LibreOffice render/conversion; .NET schema; system browser HTML capture; configured OCR/vision reconstruction | [PPTX](plugin/src/document_skills_core/formats/pptx/README.md) |
| `document-pdf` | Direct PDF read, inspect, create, edit, rewrite, structural validation | Visual rendering and OCR remain separate unavailable gates unless a future accepted provider owns them | [PDF](plugin/src/document_skills_core/formats/pdf/README.md) |

## Safety and failure semantics

Mutations require explicit output paths distinct from inputs. The normal lifecycle snapshots and hashes the source, stages output in a private operation root, validates the candidate, atomically promotes it without replacing an unrelated destination, verifies source preservation, and cleans temporary state.

Active content, external relationships, unsafe package graphs, ambiguous selectors, provider crashes, timeouts, and required validation failures fail closed. Result status distinguishes `success`, authorized `degraded`, `enhancement_required`, `unavailable`, `invalid_request`, and `failed`; unavailable or unexecuted validators never become passes.

Native process launches retain the authorized executable identity: Windows holds canonical file/directory handles, Linux executes through a held `/proc/self/fd` descriptor, and macOS uses `posix_spawn` with `POSIX_SPAWN_START_SUSPENDED`. On macOS, the parent checks the kernel-mapped main image's device/inode, size and timestamps against the held executable, rechecks its SHA-256, and resumes only that verified child. Missing inspection support or mismatched identity kills and reaps the suspended child; it never falls back to an unchecked pathname launch. The child starts its own session and inherits only standard pipes and explicitly authorized workspace descriptors. Launches of the current Python interpreter retain its authorized virtualenv alias through a code-selected `PYTHONEXECUTABLE` value on macOS. POSIX LibreOffice discovery selects the installed native `soffice.bin` companion when its entry point is a shell wrapper; executable identity and version-probe checks remain required.

## Verification

The optional DOCX CI profile requires real .NET/OpenXML operations. LibreOffice currently has no production hard-quota backend, so its managed operations must report `hard_quota_backend_unavailable`; CI validates that exact boundary and records no LibreOffice operations as executed. If a complete quota backend becomes available, the same profile requires all LibreOffice operations. The separate DOCX artifact renderer remains mandatory for template pack acceptance, and PDF Core functionality requires actual operations on all three platforms.

The verification layers are deliberately separate:

- `npm run verify:docs` checks documentation structure, UTF-8, links, package commands, and registered-operation coverage.
- `npm run verify` runs deterministic producer tests, supply-chain audit, artifact validation, plugin verification, and release packaging. The pytest layer runs in two phases: everything except `slow` in parallel (`-n 4 --dist loadscope` by default, whole modules per worker), then the `slow` tier (real external providers) serially — the dotnet helper is a shared on-disk build target that deadlocks under parallel workers. Set `DS_PYTEST_WORKERS=N` to override the parallel worker count, or `DS_PYTEST_SERIAL=1` to run the full suite serially. Serial-only execution measured ~2h47m on the packaging machine.
- `npm run test:fast` is the iteration tier: the same suite minus the `slow` mark (tests that drive a real external provider — LibreOffice install, dotnet helper build, PDF rendering). It uses four xdist workers by default; `DS_PYTEST_WORKERS=N` overrides that, and `DS_PYTEST_SERIAL=1` disables xdist for a serial run. The pin gate (`npm run verify`) always runs the full set, including slow.
- `npm run verify:repro` proves repeated builds have identical inventories and hashes.
- [`e2e/README.md`](e2e/README.md) documents distribution-level E2E owned by this repository. Real Office-consumer evidence is recorded separately and must name the consumer and run outcome.

The 2026-08-28 PPTX B7 evidence passed real PowerPoint consumption and non-PPTX LibreOffice paths. On that machine, LibreOffice Impress crashed even for a minimal control PPTX, while the product failed closed; production OCR/vision was not configured; remote CI was not executed. Those run facts are not universal compatibility claims.

## Related documentation

- [Bundled runtime](plugin/README.md)
- [Public Skill catalog](plugin/skills/README.md)
- [Shared Core architecture](plugin/src/document_skills_core/README.md)
- [Optional provider model](plugin/src/document_skills_core/providers/README.md)
- [Schemas](plugin/schemas/README.md)
- [Consumer validation](plugin/consumer_validation/README.md)
- [Provenance and supply chain](plugin/provenance/README.md)
- [Producer scripts](scripts/README.md)
- [Distribution E2E](e2e/README.md)
- [PPTX ecosystem contract ADR](docs/adr/0001-pptx-ecosystem-phase-bc-contract-and-operations.md)
