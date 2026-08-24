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
  directory. Local PNG/JPEG images are native; local SVG images use an
  evidenced element-level PNG fallback.
- Remote, `data:`, `file:`, custom-scheme, parent-traversal, and symlink-escape
  resources are blocked. JavaScript and service workers are disabled.
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

## CSS, layout, and media policy

Capture uses a fixed 1920x1080 viewport. Absolute positioning is native.
Bounded flex and grid layouts are emitted from their computed fixed-viewport
geometry and reported as `computed_flex_layout` or `computed_grid_layout`
approximations; this is not a claim that PowerPoint retains responsive layout
semantics. Computed margin and gap affect that geometry.

Solid backgrounds, uniform borders and radii, opacity, supported transforms,
text alignment, line height, and native images remain editable where the scene
contract permits them. Text padding maps to DrawingML body insets. Pixel
`letter-spacing` maps to bounded DrawingML character spacing.

The smallest affected element is rasterized, with a stable reason, for CSS or
HTML that cannot be represented faithfully. Reasons include box shadow,
gradient/background image, filter, clip path, mask, blend mode, overflow
clipping, unsupported white-space/word-break/text-overflow/letter-spacing,
complex pseudo-elements, canvas, video, inline SVG, and embedded content. A
local SVG referenced by `<img>` is browser-rendered and captured as a PNG
element fallback with `image_svg_raster_fallback`; raw SVG is not embedded in
the PPTX. The whole-slide and semantic-subtree flattening guards still apply.

## Interpret the result

Read `diagnostics.operation_result`:

- `conversion.outcomes`, `conversion.kinds`, and `conversion.fidelity` separate
  native, editable approximations, and rasterized elements.
- `conversion.unsupported_css`, `blocked_resources`, and `font_evidence` are
  bounded aggregates with samples and truncation counts.
- Fallback samples include an element selector, reason, bounding box, area, and
  asset SHA-256. Font evidence records requested/resolved family, weight/style,
  platform matches, and observed substitutions; fonts are not embedded.
- `emission` and `manifest` report native object/run/media correspondence.
- `validation.gates` reports required semantic/package gates and optional visual
  evidence. Without LibreOffice, visual parity is `unavailable`, never `pass`.
- When source screenshots and LibreOffice rendering are available, visual
  evidence reports whole-slide metrics plus bounded 12x6 regional differences,
  font-substitution context, and fallback-element context. Context never grants
  an automatic visual exemption; threshold failures remain failures.
- `degraded` can mean declared approximation/raster fallback or optional visual
  parity was not established. It does not mean the whole slide was rasterized.
- `invalid_request`, `failed`, or `unavailable` means no new PPTX was promoted.
  Preserve the HTML and report that no PPTX was created.

Target-machine PowerPoint may substitute fonts again; capture-time font
evidence is diagnostic, not a promise of font embedding or visual identity.
