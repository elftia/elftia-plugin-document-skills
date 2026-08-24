# Third-party notices

The foundation runtime uses the following locked Python packages:

- `attrs` — MIT.
- `defusedxml` 0.7.1 — Python Software Foundation License.
- `jsonschema` 4.25.1 — MIT.
- `jsonschema-specifications` — MIT.
- `referencing` — MIT.
- `rpds-py` — MIT.
- `typing-extensions` (when selected by the Python environment marker) — PSF-2.0.

The release audit uses the locked Node package `acorn` 8.15.0 (MIT) to parse provider runtime
ECMAScript. It is not an agent-visible command or a document provider.

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

The optional .NET OpenXML helper uses this exact locked NuGet graph, restored from the user's
NuGet cache or configured package source and never bundled into this repository:

- `DocumentFormat.OpenXml` 3.0.0 — MIT.
- `DocumentFormat.OpenXml.Framework` 3.0.0 — MIT.
- `System.IO.Packaging` 8.0.0 — MIT.

The helper project requires locked restore, and document operations disable implicit restore.

The independent consumer verification suite uses the following development-only locked graph;
none of these packages is distributed or imported by production runtime sources:

- `openpyxl` 3.1.5 and `et-xmlfile` 2.0.0 — MIT.
- `PyMuPDF` 1.27.2.2 — GNU AGPL-3.0-only or Artifex commercial license.
- `python-docx` 1.2.0 — MIT; `lxml` 6.1.1 — BSD-3-Clause.
- `python-pptx` 1.0.2 — MIT; `Pillow` 12.3.0 — HPND; `XlsxWriter` 3.2.9 — BSD-2-Clause.
- `pytest` 8.4.1 — MIT; `colorama` 0.4.6 — BSD-3-Clause; `iniconfig` 2.3.0 — MIT;
  `packaging` 26.2 — Apache-2.0 or BSD-2-Clause; `pluggy` 1.6.0 — MIT; and
  `Pygments` 2.20.0 — BSD-2-Clause.

Development-only dependencies are not distributed as production runtime components. Adopted
source is not present in this release; later additions must update this file and
`provenance/modules.json`.
