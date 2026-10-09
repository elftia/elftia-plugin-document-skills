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
| `pypdf` | [`pypdf/`](pypdf/) | Locked Python dependency, bounded private mutation service, and staged PDF reopen/semantic validation |
| `poppler` | [`pdf_tools/`](pdf_tools/) | Accepted `pdftoppm` identity and bounded private raster archive/result validation |
| `tesseract-ocr` | [`pdf_tools/`](pdf_tools/) | Accepted Tesseract identity and bounded OCR archive/result validation |

The public `capabilities --json` report is the runtime authority for whether a provider-owned operation is callable.

## Safety and failure semantics

Native executable selection is identity-bound and rechecked around launch. Providers receive screened local snapshots and private storage; output, logs, environment details, and error evidence are bounded and sanitized. Timeouts, crashes, malformed/oversized envelopes, quota uncertainty, identity drift, or missing dependencies return stable unavailable/failed results and do not publish output.

LibreOffice output is never promoted directly when the contract requires Core reconstruction or reopen. Browser capture uses a tokenized loopback origin, blocks scripts/service workers and undeclared resources, and keeps the browser sandbox. OCR observations cannot control paths, relationships, OOXML, or aggregate coverage claims.

### LibreOffice hard storage quotas

[`quota_linux.py`](libreoffice/quota_linux.py) provides the production Linux x86-64/glibc backend. Install system `fuse3` and `libfuse3-3` (validated libfuse ABI 3.14–3.16), and permit the invoking account to open `/dev/fuse` and create a FUSE mount. Each conversion uses one private mount, with output, profile, temporary files, home and XDG cache/config in the same quota. File data lives only in bounded broker memory; no writable backing disk tree is exposed.

The broker serializes writes, sparse truncation, directory/file creation and rename replacement. It charges logical file length, directory/file entries, and open files retained after unlink; it releases those charges only when storage is actually discarded. Cached write-through keeps ordinary successful writes synchronous with quota decisions; the initialization callback explicitly disables `FUSE_CAP_WRITEBACK_CACHE`. Shared mappings can modify already charged file contents, but cannot extend file length; growth still requires a quota-checked write or truncate. Links, special files and unimplemented allocation/copy shortcuts are rejected. An activation-time sparse growth and entry-creation probe must return real `ENOSPC` from the broker before LibreOffice can launch. A quota denial invalidates the conversion even if LibreOffice subsequently exits zero; the final identity/tree scan is an additional publication gate.

This is a storage quota for the selected private tree, not OS privilege isolation. The existing executable identity binding, macro/content screening, timeouts, cancellation and process-tree cleanup still apply. macOS/Windows and unsupported Linux architectures fail closed until they have an equivalent reviewed backend; installing LibreOffice alone does not satisfy its managed provider contract. PDF Core on those platforms does not depend on this optional provider.

Before conversion, the fresh profile sets `DisableMacrosExecution=true`, `DisableActiveContent=true` and `MacroSecurityLevel=3`. These fixed values disable all macro runtimes, OLE and DDE; the profile bytes and entries are charged to the same quota. See the [LibreOffice configuration schema](https://github.com/LibreOffice/core/blob/libreoffice-24.2.7.2/officecfg/registry/schema/org/openoffice/Office/Common.xcs).

The headless child also receives the fixed `GSETTINGS_BACKEND=memory` for GLib settings. LibreOffice can still access dconf directly; its shared file mappings therefore use the same quota filesystem. This environment setting does not bypass any storage quota.

ABI references: [libfuse high-level API](https://github.com/libfuse/libfuse/blob/fuse-3.14.0/include/fuse.h), [open-file ABI](https://github.com/libfuse/libfuse/blob/fuse-3.14.0/include/fuse_common.h).

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
