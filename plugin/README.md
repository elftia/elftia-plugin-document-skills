# Document Skills Runtime

## Purpose

`document-skills` is the runtime-managed artifact produced by this repository. It contributes four public Agent Skills—[`document-docx`](skills/document-docx/SKILL.md), [`document-xlsx`](skills/document-xlsx/SKILL.md), [`document-pptx`](skills/document-pptx/SKILL.md), and [`document-pdf`](skills/document-pdf/SKILL.md)—behind one schema-versioned Python command surface.

Python dispatches direct Core implementations and private project-local Node or optional external providers. The public surface never asks an Agent to invoke Node, LibreOffice, dotnet, a browser, OCR, or provider scripts directly.

## Ownership and boundaries

- [`skills/`](skills/README.md) owns agent-facing routing and safe workflow guidance.
- [`src/document_skills_core/`](src/document_skills_core/README.md) owns contracts, dispatch, transactions, format implementations, provider selection, supervision, and result validation.
- [`schemas/`](schemas/README.md) owns public request/report envelopes; format references own detailed operation arguments.
- The [private Node runtime](runtime/node/README.md) is a bounded backend for template and HTML work.
- [`consumer_validation/`](consumer_validation/README.md), [`tests/`](tests/README.md), [`tools/`](tools/README.md), and [`provenance/`](provenance/README.md) own assurance rather than document operations.

The runtime does not silently install dependencies or optional providers during a document request. It does not treat provider detection as successful execution, and it does not expose provider stdout as protocol data.

## Entry points

Replace `<project-root>` and `<skill-dir>` with absolute paths supplied by the Agent Skills host:

```text
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" doctor --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" capabilities --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" run --request request.json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" validate --input artifact.docx --json
```

Dependency preparation is an installation/build concern:

```text
uv sync --project "<project-root>" --frozen
```

Document operations never mutate `uv.lock` or `package-lock.json`. The [Skill catalog](skills/README.md) routes by format; the [format READMEs](src/document_skills_core/README.md#format-modules) list every registered operation and availability boundary.

### Public protocol

Requests and results use `schema_version: "1.0"` and the checked-in [JSON Schemas](schemas/README.md). Unknown operations return `DS_OPERATION_UNKNOWN`. Final status is one of `success`, `degraded`, `enhancement_required`, `invalid_request`, `unavailable`, or `failed`.

Semantic degradation requires caller authorization where the operation contract offers it. An optional validator that did not run is `unavailable` or `not_run`, never `pass`.

Provider-gated operations remain visible but truthfully unavailable until their exact provider contract is satisfied. For example, `pptx.reconstruct.from-image` requires the explicitly configured `ocr-vision` adapter described by the [PPTX format module](src/document_skills_core/formats/pptx/README.md); no production OCR/vision adapter is configured in the shipped default.

### Managed Elftia lifecycle

Official and Steam builds ship the same release inventory under `resources/plugins/agent-surface/document-skills`. A fresh profile installs it through the normal managed local-plugin installer. The native `elftia-plugin.json` and Claude-compatible `.claude-plugin/plugin.json` identify the same bundle and `skills/` directory; they do not create two installed copies.

The bundle contributes Skills only when the managed installation is enabled and the session's `pluginsEnabled` gate is true. Trusted host preparation installs the frozen Python and Node graphs with lifecycle scripts disabled, records success atomically, and retries after repair when preparation failed. It does not download a browser. Third-party plugins cannot opt into this trusted preparation policy.

When active, the managed replacement suppresses only read-only legacy Skills named exactly `document` or `elftia-document`. Workspace, project, and personal Skills are not removed or rewritten.

## Safety and failure semantics

- Writes use private staging, required validation, atomic promotion, source-hash verification, and cleanup. In-place mutation is rejected unless an operation explicitly implements a tested recovery protocol; none currently do.
- OOXML preflight inventories macros, XLM, ActiveX, OLE/embedded objects, templates, DDE, external relationships, and executable parts. Unsafe content returns `DS_ARCHIVE_UNSAFE` unless a narrowly documented inert copy-through policy applies.
- Each command runs a one-shot supervised worker. Cancellation, exceptions, output overflow, provider exits, hangs, and crashes become bounded schema-valid results. The supervisor accepts only the terminal nonce-bound frame on worker stdout; private workspace state is never a result channel.
- This is protocol and transaction containment, not an OS privilege sandbox. Workers retain the invoking user's filesystem permissions.
- Optional provider absence returns `unavailable` and publishes nothing for provider-required operations. See the [provider matrix](src/document_skills_core/providers/README.md).

## Verification

Producer-side verification is intentionally not an Agent command surface. The [producer verification guide](../scripts/README.md) owns the exact documentation, aggregate, artifact, distribution, and reproducibility commands. Those gates validate this documentation against registered capabilities, exercise the frozen Python and private Node graphs, audit provenance, and compare clean builds by path, length, and SHA-256.

## Related documentation

- [Repository producer guide](../README.md)
- [Public Skill catalog](skills/README.md)
- [Shared Core architecture](src/document_skills_core/README.md)
- [Optional providers](src/document_skills_core/providers/README.md)
- [Private Node runtime](runtime/node/README.md)
- [Schemas](schemas/README.md)
- [Consumer validation](consumer_validation/README.md)
- [Tests](tests/README.md)
- [Provenance](provenance/README.md)
- [Producer E2E](../e2e/README.md)
