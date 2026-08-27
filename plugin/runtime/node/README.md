# Private Node Runtime

## Purpose

This directory contains internal Node adapters used behind the supervised Python façade: DOCX template work and bounded HTML-to-PPTX scene capture/evidence.

## Ownership and boundaries

Node is not an Agent-visible command surface. Python selects the adapter, validates the request, owns nonce-bound private files, applies time/byte ceilings, validates the returned scene/result, and performs final artifact promotion. The runtime uses the exact production dependencies in [`../../package-lock.json`](../../package-lock.json).

The HTML adapter does not download a browser, accept arbitrary navigation, enable page scripts, or serve undeclared filesystem paths. The DOCX adapter does not accept caller JavaScript, expressions, raw XML, or custom parser code.

## Entry points

- [`health.mjs`](health.mjs) reports bounded Node/runtime dependency health.
- [`docx_template.mjs`](docx_template.mjs) owns private template expansion.
- [`html_capture.mjs`](html_capture.mjs) orchestrates the fixed-canvas capture contract.
- `html_*policy.mjs`, `html_*evidence.mjs`, `html_*assets.mjs`, and `html_*server.mjs` separate resource policy, evidence, assets, and the tokenized loopback server.

Call these only through the public Python Skill façade. Provider registration and detection live in [`../../src/document_skills_core/providers/`](../../src/document_skills_core/providers/README.md).

## Safety and failure semantics

Private request/result data uses nonce-bound files rather than provider stdout. HTML capture keeps the browser sandbox, disables scripts and service workers, blocks external/undeclared resources, binds a canonical 1920x1080 `.slide` surface, and enforces resource ceilings. Unsupported semantics use only an explicitly allowed element fallback or fail; whole-slide raster fallback is not accepted.

Adapter crashes, exits, hangs, oversized output, missing dependencies, or browser launch failure become bounded unavailable/failed Python results with no destination promotion.

## Verification

Private Node policy/health coverage and HTML provider integration coverage are owned by the [plugin test suite](../../tests/README.md). The [producer verification guide](../../../scripts/README.md) owns the exact focused and aggregate commands.

## Related documentation

- [Runtime overview](../../README.md)
- [Provider architecture](../../src/document_skills_core/providers/README.md)
- [PPTX module](../../src/document_skills_core/formats/pptx/README.md)
- [PPTX HTML contract](../../skills/document-pptx/references/html-to-editable-pptx.md)
- [DOCX Skill](../../skills/document-docx/SKILL.md)
