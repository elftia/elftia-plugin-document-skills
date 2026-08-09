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

Development-only dependencies are not distributed as production runtime components. Adopted
source is not present in this release; later additions must update this file and
`provenance/modules.json`.
