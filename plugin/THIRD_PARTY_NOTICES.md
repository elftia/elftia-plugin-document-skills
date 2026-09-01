# Third-party notices

The foundation runtime uses the following locked Python packages:

- `attrs` — MIT.
- `defusedxml` 0.7.1 — Python Software Foundation License.
- `jsonschema` 4.25.1 — MIT.
- `jsonschema-specifications` — MIT.
- `referencing` — MIT.
- `rpds-py` — MIT.
- `typing-extensions` (when selected by the Python environment marker) — PSF-2.0.

The PDF image, encryption, decryption, compression, and visual-evidence paths use this
exact locked production graph:

- `pypdf` 6.16.2 — BSD-3-Clause.
- `cryptography` 50.0.0 — Apache-2.0 OR BSD-3-Clause.
- `cffi` 2.1.1 — MIT-0.
- `pycparser` 3.0 — BSD-3-Clause.
- `Pillow` 12.3.0 — HPND.

These packages run only behind the public supervisor and isolated worker. Passwords remain
in the caller-protected request file and process memory; they are never copied to result files,
command-line arguments, or provider diagnostics. Core PNG creation and orientation-1 JPEG
creation do not invoke Pillow pixel-decoding or transform APIs for their supported bounded
image subsets. For JPEG EXIF orientation values 2 through 8, Elftia owns local-file and magic
validation, APP1/APP14 marker parsing, source hashing and TOCTOU checks, and the 16 MiB source,
40 million pixel, and 160 MiB decoded-byte ceilings. Elftia also owns the closed orientation
1-through-8 policy, decoder/frame-size agreement, Gray/RGB output policy, Flate PDF
serialization, creation evidence, candidate reopen checks,
and atomic promotion. Pillow receives only an already-local, marker-inspected, budget-preflighted
orientation-2-through-8 JPEG; it performs the bounded pixel decode, `ImageOps.exif_transpose`,
Gray/RGB conversion, and pixel extraction. Pillow does not discover inputs, access remote or
system resources, write PDF objects, set budgets, publish evidence, or control promotion.

Separately, Pillow is used with bounded decode budgets for compatible soft-mask image
extraction, balanced/aggressive Image XObject recompression, decoded-image quality evidence,
and full-page render comparison. Elftia retains the PDF preflight, limits, alpha fail-closed
policy, object replacement, quality and byte-gain gates, semantic reopen checks, evidence, and
atomic promotion. Alpha-bearing images are never rewritten by the compression path.

The Unicode PDF font and shaping path uses this exact locked production graph:

- `fonttools` 4.63.0 — MIT. Its wheel also carries upstream test-font notices under
  SIL Open Font License 1.1; those test fonts are not imported into this project.
- `uharfbuzz` 0.56.0 — Apache-2.0 Python bindings around the bundled HarfBuzz engine.
- `python-bidi` 0.6.11 — LGPL-3.0-only. Its wheel-provided third-party notice records
  the bundled Rust UAX #9 implementation and MIT/Apache-2.0/Unicode-DFS-2016 components.

The font path accepts only caller-selected, hash-bound local TrueType fonts, enforces
embedding permissions and byte/glyph bounds, and subsets each font before PDF embedding.
No system font discovery, remote font fetch, or font command is exposed to the agent.

The release audit uses the locked Node package `acorn` 8.15.0 (MIT) to parse provider runtime
ECMAScript. It is not an agent-visible command or a document provider.

Optional PDF render/OCR profiles may use host-supplied executables that are neither
downloaded nor redistributed by this package:

- Poppler `pdftoppm` — GPL-2.0-or-later; the callable detector accepts versions from
  23.1.0 (inclusive) through 27.0.0 (exclusive).
- Tesseract OCR — Apache-2.0; the callable detector accepts versions from 5.3.0
  (inclusive) through 6.0.0 (exclusive) and inventories installed language packs.

These host tools and Tesseract language data are intentionally outside the Python/Node
lock graph and package SBOM because Elftia does not install or ship them. The operator of
an optional provider profile remains responsible for the executable distribution source,
language-data license, security updates, and platform sandbox. A successful runtime probe
is capability evidence, not release approval; supported platform/version smoke evidence
and an independently reviewed host-runtime inventory are still required before such a
profile is declared release-ready.

The private Core DOCX scalar-template backend uses this exact locked production graph:

- `docxtemplater` 3.69.3 — MIT option selected.
- `@xmldom/xmldom` 0.9.10 — MIT.
- `pizzip` 3.2.0 — MIT option selected.
- `pako` 2.2.0 — MIT AND Zlib; both published license identities are retained.

These packages run only behind the frozen uv/Python façade and the centralized process policy.
No upstream wrapper, MCP handler, schema, prompt, template, fixture, or transport source is
included.

The optional HTML-deck capture provider uses `playwright-core` 1.62.1 (Apache-2.0). The exact
package has no production transitive dependencies and no install lifecycle scripts. No browser
binary is downloaded or redistributed; the provider can launch only a supported local
Chrome/Chromium/Edge executable selected from the host-authored platform list.

The optional .NET OpenXML helper uses this exact locked NuGet graph, restored in locked mode
from its package source into project-private temporary cache and configuration roots. It never
reads or depends on the user's NuGet cache or configuration, and the packages are never bundled
into this repository:

- `DocumentFormat.OpenXml` 3.0.0 — MIT.
- `DocumentFormat.OpenXml.Framework` 3.0.0 — MIT.
- `System.IO.Packaging` 8.0.0 — MIT.

The helper project requires locked restore, and document operations disable implicit restore.

The independent consumer verification suite uses the following development-only locked graph;
none of these packages is distributed or imported by production runtime sources:

- `openpyxl` 3.1.5 and `et-xmlfile` 2.0.0 — MIT.
- `PyMuPDF` 1.27.2.2 — GNU AGPL-3.0-only or Artifex commercial license.
- `python-docx` 1.2.0 — MIT; `lxml` 6.1.1 — BSD-3-Clause.
- `python-pptx` 1.0.2 — MIT; `XlsxWriter` 3.2.9 — BSD-2-Clause.
- `pytest` 8.4.1 — MIT; `colorama` 0.4.6 — BSD-3-Clause; `iniconfig` 2.3.0 — MIT;
  `packaging` 26.2 — Apache-2.0 or BSD-2-Clause; `pluggy` 1.6.0 — MIT;
  `Pygments` 2.20.0 — BSD-2-Clause; `pytest-xdist` 3.7.0 — MIT; and
  `execnet` 2.1.2 — MIT.

Development-only dependencies are not distributed as production runtime components. Adopted
Adopted source is not present in this release; later additions must update this file and
`provenance/modules.json`.
