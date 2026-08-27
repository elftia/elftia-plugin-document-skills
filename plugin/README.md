# Document Skills

`document-skills` is a standalone Agent Skills project with four public surfaces:
`document-docx`, `document-xlsx`, `document-pptx`, and `document-pdf`.

The only agent-visible execution surface is a bundled Python entrypoint run in this project's
frozen uv environment. Python dispatches Core Python and project-local Node providers internally;
optional LibreOffice and .NET/OpenXML providers are detected but never installed silently.

## Commands

Replace `<project-root>` and `<skill-dir>` with absolute paths resolved by the Agent Skills host:

```text
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" doctor --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" capabilities --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" run --request request.json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" validate --input output.docx --json
```

No command falls back to system Python or invokes Node, npm, LibreOffice, dotnet, or another
provider directly. Dependency preparation is an installation/build concern:

```text
uv sync --project "<project-root>" --frozen
```

Document operations never mutate either lock and never install dependencies.

## Elftia managed built-in lifecycle

Official and Steam builds ship the same release inventory under
`resources/plugins/agent-surface/document-skills`. On a fresh profile, Elftia installs it as the
managed `document-skills` built-in through the normal local-plugin installer. The native
`elftia-plugin.json` and Claude-compatible `.claude-plugin/plugin.json` both identify the same
bundle and the same `skills/` directory; they do not create two installed copies.

Installation state and session state are separate:

| Managed install | Session `pluginsEnabled` | Agent contribution |
| --- | --- | --- |
| enabled | `true` | the effective `document-skills` bundle contributes the four narrow Skills |
| enabled | absent or `false` | no document Skill is injected |
| explicitly disabled | any value | no contribution and no runtime preparation |
| re-enabled | `true` | preparation is retried if the recorded runtime state is absent or stale |

After a first install or version update, trusted Elftia host policy prepares the installed user
copy with the exact Elftia-managed uv and Node tool records. It performs frozen Python and Node
lock installation with lifecycle scripts disabled, including exact `playwright-core@1.62.1`,
then checks Python, Node, and the private protocol before atomically recording success. It does
not download or provision a browser. A matching marker makes later boots reads-only.
Preparation failure is contained to this plugin, does not crash application boot, and never
writes a success marker; repairing the managed tools and retrying is sufficient. Third-party
plugins and manifest-declared commands cannot opt into this policy.

When the managed replacement is active for a session, TinyElf suppresses only read-only legacy
Skills named exactly `document` or `elftia-document`. Workspace, project, and personal Skills are
never removed or rewritten, and disabling the plugin or the session gate restores the legacy
projection.

## Contract

Requests and results use `schema_version: "1.0"` and the checked-in schemas in `schemas/`.
Unknown operations return `DS_OPERATION_UNKNOWN`. The shared provider registry exposes bounded
DOCX, XLSX, PPTX, and PDF operations. The Core DOCX slice registers nine callable operations:

- `docx.read`
- `docx.inspect.accessibility`
- `docx.inspect.structure`
- `docx.compare.semantic`
- `docx.create`
- `docx.edit`
- `docx.edit.replace-text`
- `docx.merge`
- `docx.template.apply`

The DOCX implementation lives in `src/document_skills_core/formats/docx/`. Read and inspection
return bounded structured data. Create accepts either the compatible report contract or a
source-neutral versioned document spec with stable semantic ids, reusable style profiles, and
optional domain profiles. Template Engine/physical `.docx|.dotx` bases, Document Spec, Style
Profile, and Domain Profile are separate layers: `academic-paper` is the first domain application,
while `technical-report` proves the generic emitter is reusable. Replacement is run-aware across
the document and referenced header/footer stories. Scalar template substitution accepts only
bounded ASCII/dot identifiers and uses the project-local Node backend privately through Python.
`skills/document-docx/references/` contains the complete request/result and safety guidance.
Mammoth 1.12.1 was evaluated as a lossy HTML adapter and not adopted; no Markdown/HTML placeholder
operation or runtime dependency was added, and native OOXML remains the comparison/security source
of truth.

### XLSX

The public Skill is `skills/document-xlsx/SKILL.md`; its entrypoint and detailed guidance live in
`skills/document-xlsx/scripts/` and `skills/document-xlsx/references/`. The implementation is
owned by `src/document_skills_core/formats/xlsx/`, with optional LibreOffice and .NET/OpenXML
adapters isolated in `src/document_skills_core/providers/libreoffice/` and
`src/document_skills_core/providers/dotnet/`.

| Surface | Operations | Availability boundary |
| --- | --- | --- |
| Foundation Core | `xlsx.read`, `xlsx.inspect.structure`, `xlsx.create`, `xlsx.edit` | Callable through `core-python`; create/edit may honestly degrade when optional recalculation is unavailable. |
| Additional Core | `xlsx.recalculate`, `xlsx.convert`, `xlsx.template.instantiate`, `xlsx.summary.aggregate`, `xlsx.pivot.create` | Registered through `core-python`; formula recalculation and the legacy `.xls` conversion branch still require callable LibreOffice. |
| Provider-only | `xlsx.validate.schema`, `xlsx.render` | Schema validation requires callable .NET/OpenXML; rendering requires callable LibreOffice. Missing providers report `unavailable` and do not promote output. |

Formula cells expose only `recalculated`, `stale`, `never_calculated`, or
`recalculation_required`. A stored cache is never treated as proof of correctness, and
`recalculated` requires an accepted recalculation-provider result. Without that result,
read/create/edit preserve the honest outstanding state and report degradation where applicable;
explicit recalculation of a formula workbook is unavailable and promotes no output. A workbook
with no formulas completes that operation as `not_applicable` without calling LibreOffice.

Optional-provider source belongs to separately scoped enhancement Changes and is not established
by this Core XLSX delivery. Source presence alone does not make LibreOffice callable: executable
identity and a validated aggregate hard-quota backend must both pass. The shipped default quota
backend is fail-closed and reports unavailable; size polling or free-disk checks never substitute
for that capability. `xlsx.convert` otherwise remains Core for XLSX/CSV/TSV/canonical-JSON
conversion. `xlsx.validate.schema` is callable only with .NET 8, the locked project helper, and
its exact OpenXML dependency; a Core reopen is not reported as full schema validation. This
documentation records producer behavior only and makes no claim that a host seeded the artifact,
that either optional provider ran live, or that remote CI was observed.

The PPTX surface adds browser-gated `pptx.create.from-html` to its read, inspect, typed-create,
provider-gated `pptx.reconstruct.from-image`, and edit operations. Typed create embeds bounded local PNG/JPEG/static GIF bytes and emits
editable bar/column, line, pie, and scatter DrawingML charts with literal caches; missing or
invalid assets fail closed instead of becoming placeholders. Python owns the public request,
path policy, transaction, validation, and promotion. A private Node adapter uses exact
`playwright-core@1.62.1` with a
closed detector for a supported system Chrome/Chromium/Edge executable. It serves only the
fixed 1920x1080 `.slide` deck and canonical descendant assets from a tokenized loopback origin,
retains the browser sandbox, disables scripts/service workers, and blocks other resources.
Scene and raster payloads return through nonce-bound private files. Supported text, geometry,
and images remain native/editable; unsupported effects use bounded element-level fallback or
fail, never silent whole-slide rasterization. See
`skills/document-pptx/references/html-to-editable-pptx.md`.

Layered reconstruction accepts only bounded local PNG/JPEG input plus the exact
fail-closed `ocr-vision` policy and an explicit `retain`/`discard` audit policy.
The production provider is unavailable by default until an audited adapter is
configured. When callable, confident text/shapes remain native, low-confidence
elements use only their smallest source-region crops, and overlap-safe area and
object-count coverage remain separate receipt fields. It never reports a hidden
or uncropped whole-slide image as editable reconstruction. See
`skills/document-pptx/references/layered-reconstruction.md`.

Result status is one of `success`, `degraded`, `enhancement_required`, `invalid_request`,
`unavailable`, or `failed`. Semantic degradation requires `options.allow_degraded: true`; an optional validator
that is unavailable is never reported as passing.

## Output safety

Writes require an explicit output path. The normal lifecycle hashes the immutable input, writes
to a private operation directory, validates the staged artifact, stages within the destination
filesystem, atomically promotes it, verifies source preservation, and cleans temporary data.
Input/output identity is rejected unless a future operation explicitly implements and tests
recoverable in-place replacement.

## Optional providers

LibreOffice and `.NET 8 + DocumentFormat.OpenXml` are optional enhancements. `doctor --json`
reports executable/runtime detection separately from accepted callable capability. An accepted
LibreOffice provider adds DOCX PDF conversion, PDF/PNG page evidence with deterministic layout
findings, a bounded semantic-node layout repair loop, fixed-profile reference visual comparison,
and legacy `.doc` conversion. A normal render does not imply reference visual comparison. The
OpenXML enhancement is available only when .NET 8 and the
project-local `OpenXmlProbe.dll` successfully load and identify the project-local
`DocumentFormat.OpenXml` assembly; another .NET major or a bare dotnet executable is not enough.
Their absence does not make Core unhealthy.
Installing or updating them is always an explicit user/system administration action outside a
document operation.

`html-browser` is an optional execution provider rather than an enhancement validator. The
capability report always lists `pptx.create.from-html`, but marks it `available: true` only when
the locked Node library, a supported system browser, and the bounded sandboxed launch probe all
pass. Its absence returns `unavailable` and creates no output.

`ocr-vision` is also an optional execution provider. The capability report
always lists `pptx.reconstruct.from-image`, but the shipped detector reports it
unavailable because no production OCR/vision adapter is configured. Its absence
creates no output and never degrades to a single-image PPTX.

The DOCX slice exposes `docx.compare.visual` only through the accepted LibreOffice provider and
`docx.validate.schema` only through the accepted .NET/OpenXML provider. Ordinary Core mutations do
not claim either result: their visual and full-schema gates remain `unavailable` unless the
corresponding public operation actually runs. Detection alone never turns a gate into `pass`,
changes achieved fidelity, or advertises a callable operation.

## Active-content policy

OOXML preflight inventories VBA, Excel 4.0 macro sheets (including international, binary, and
add-in forms), ActiveX, OLE/embedded objects, attached templates, DDE field codes, external
relationship targets, and executable package parts. The default policy rejects any such content
with `DS_ARCHIVE_UNSAFE` and a structured security inventory.
`preserve-disabled` is an internal negotiation state for a future format provider: it exposes the
inventory and marks mutation unauthorized until that provider proves it can preserve the
original bytes while keeping the content disabled. It never means the foundation executed,
removed, or safely rewrote active content.

## Troubleshooting

- `DS_RUNTIME_UNAVAILABLE`: repair the Elftia-managed uv/Node installation or frozen dependencies.
- `DS_REQUEST_INVALID`: validate the request against `schemas/operation-request.schema.json`.
- `DS_ENHANCEMENT_REQUIRED`: install an identified optional provider or explicitly choose an
  advertised safe degraded path.
- `DS_ARCHIVE_UNSAFE`: inspect the package origin; the archive failed a hard safety ceiling.
- `DS_VALIDATION_FAILED`: no staged artifact was promoted; review the reported gate evidence.

Supply-chain and clean-room boundaries are documented in `PROVENANCE.md`,
`THIRD_PARTY_NOTICES.md`, and `provenance/`.
The release audit hashes and classifies every release file through one shared inventory. Risky
scripts, executable locations/modes, extensionless artifacts, binary magics, and opaque bytes
require exact provenance or a reviewed hash-pinned data exclusion; ordinary and fixture data
require their own exact reviewed classification. Only the exact self-referential audit metadata
allowlist may use a reviewed hashless classification.

## Public protocol containment

Each documented command starts a private, one-shot Python worker. The supervisor owns argument
classification, cancellation, final schema validation, and the only stdout write. Provider
stdout/stderr are bounded and discarded as protocol data; a nonce-bound atomic result file is
the only worker channel. HTML capture additionally binds its private scene/assets to the command
nonce and hard byte/time ceilings. Provider exceptions, `SystemExit`, provider-created interrupts, hangs,
output overflow, `os._exit`, and worker crashes become schema-valid failures or unavailable
reports. This is reliability and protocol containment, not OS privilege isolation; the worker
still runs with the invoking user's filesystem permissions.
