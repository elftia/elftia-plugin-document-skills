# Provider Architecture

## Purpose

This module registers Core and optional execution providers, proves their availability, and adapts accepted provider results back into the shared Document Skills transaction and validation lifecycle.

## Ownership and boundaries

Provider detection, callable acceptance, execution, and result validation are separate stages. A source directory, executable on `PATH`, runtime version string, or successful process start is not enough to advertise a capability. Each provider must satisfy its exact identity, dependency, isolation, byte/time, and result-envelope contract.

Providers never own the public CLI, final stdout, destination promotion, or permission to weaken a format contract. Python remains the public façade and revalidates staged provider evidence.

## Entry points

[`defaults.py`](defaults.py) composes the registry and Core format services. Provider-specific code is isolated under:

| Provider | Directory | Availability boundary |
| --- | --- | --- |
| `core-python` | Core format modules | Required and versioned with the bundle |
| `core-node` | [`../../../runtime/node/`](../../../runtime/node/README.md) plus Node detector | Required for its bounded internal operations; exact locked production graph |
| `libreoffice` | [`libreoffice/`](libreoffice/) | Accepted executable identity, private profile/storage, aggregate hard-quota backend, bounded conversion/reopen evidence |
| `dotnet-openxml` | [`dotnet/`](dotnet/) | .NET 8, project-local locked helper, and exact `DocumentFormat.OpenXml` assembly |
| `html-browser` | [`html_browser/`](html_browser/) | Locked `playwright-core`, supported system Chrome/Chromium/Edge, sandboxed launch/resource probe; no browser download |
| `ocr-vision` | [`ocr_vision/`](ocr_vision/) | Typed audited adapter; shipped production detector is unavailable by default |

The public `capabilities --json` report is the runtime authority for whether a provider-owned operation is callable.

## Safety and failure semantics

Native executable selection is identity-bound and rechecked around launch. Providers receive screened local snapshots and private storage; output, logs, environment details, and error evidence are bounded and sanitized. Timeouts, crashes, malformed/oversized envelopes, quota uncertainty, identity drift, or missing dependencies return stable unavailable/failed results and do not publish output.

LibreOffice output is never promoted directly when the contract requires Core reconstruction or reopen. Browser capture uses a tokenized loopback origin, blocks scripts/service workers and undeclared resources, and keeps the browser sandbox. OCR observations cannot control paths, relationships, OOXML, or aggregate coverage claims.

## Verification

Provider contracts have focused detector, isolation, crash, timeout, identity, hard-quota, and real-provider tests in the [plugin test suite](../../../tests/README.md). The [producer verification guide](../../../../scripts/README.md) owns the exact commands. Environment-gated real-provider skips remain skips; they do not prove availability.

## Related documentation

- [Shared Core](../README.md)
- [Runtime overview](../../../README.md)
- [Private Node runtime](../../../runtime/node/README.md)
- [DOCX](../formats/docx/README.md)
- [XLSX](../formats/xlsx/README.md)
- [PPTX](../formats/pptx/README.md)
- [Provenance](../../../provenance/README.md)
