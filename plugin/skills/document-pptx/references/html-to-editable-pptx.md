# HTML deck to editable PPTX

## Probe before export

Run the PPTX capability command documented in the parent Skill. Find the
`operations` entry whose `operation` is `pptx.create.from-html`; the name is
always discoverable, so only `available: true` permits invocation. The entry's
`providers` should contain `html-browser`. Provider evidence identifies the
locked `playwright-core` version and selected system browser.

An unavailable entry means Node, `playwright-core@1.62.1`, a supported local
Chrome/Chromium/Edge executable, or the sandboxed launch probe did not pass.
Do not install or download a browser during a document operation.

## Input contract

- The input is a local `.html` or `.htm` file with one or more `.slide`
  elements, each resolving to exactly 1920x1080 CSS pixels.
- The output is a distinct `.pptx` path. In-place conversion is unsupported.
- Relative assets must remain canonical descendants of the HTML file's parent
  directory. Bounded PNG/JPEG `data:` images are accepted.
- Remote, `file:`, custom-scheme, parent-traversal, and symlink-escape resources
  are blocked. JavaScript and service workers are disabled.
- `fallback_policy` is `element-rasterize` (default) or `fail`. Element fallback
  targets the smallest eligible subtree; the slide root and semantic whole-slide
  flattening are rejected.
- Safe optional hints are `data-pptx-id`, `data-pptx-ignore`,
  `data-pptx-raster`, and `data-pptx-role`. Other `data-pptx-*` attributes do
  not inject paths, relationships, OOXML, or executable content.

## Request

Write a request file such as:

```json
{
  "schema_version": "1.0",
  "operation": "pptx.create.from-html",
  "input": "C:/absolute/deck/deck.html",
  "output": "C:/absolute/deck/deck.pptx",
  "arguments": {
    "metadata": {
      "title": "Deck title",
      "creator": "Deck producer",
      "subject": "Optional subject"
    },
    "fallback_policy": "element-rasterize"
  },
  "options": {
    "fidelity": "core"
  }
}
```

Invoke it with the parent Skill's frozen `run --request` command. A promoted
output has a required scene/package validation pass. Coordinates map at exactly
6,350 EMU per CSS pixel; font sizes map at 0.5 PowerPoint points per CSS pixel.

## Interpret the result

Read `diagnostics.operation_result`:

- `conversion.outcomes`, `conversion.kinds`, and `conversion.fidelity` separate
  native, editable approximations, and rasterized elements.
- `conversion.unsupported_css`, `blocked_resources`, and `font_evidence` are
  bounded aggregates with samples and truncation counts.
- `emission` and `manifest` report native object/run/media correspondence.
- `validation.gates` reports required semantic/package gates and optional visual
  evidence. Without LibreOffice, visual parity is `unavailable`, never `pass`.
- `degraded` can mean declared approximation/raster fallback or optional visual
  parity was not established. It does not mean the whole slide was rasterized.
- `invalid_request`, `failed`, or `unavailable` means no new PPTX was promoted.
  Preserve the HTML and report that no PPTX was created.

Target-machine PowerPoint may substitute fonts again; capture-time font
evidence is diagnostic, not a promise of font embedding or visual identity.
