# LibreOffice PPTX outputs and legacy conversion

Use these operations only when `capabilities --json` reports them available
through the LibreOffice provider. Availability requires a detected executable
that successfully answers the bounded version probe. The provider uses a
private per-operation user profile and a contained headless process; it does
not use the user's normal LibreOffice profile.

## PDF conversion

```json
{
  "schema_version": "1.0",
  "operation": "pptx.convert.pdf",
  "input": "deck.pptx",
  "output": "deck.pdf",
  "arguments": {},
  "options": { "fidelity": "enhanced" }
}
```

The input must be `.pptx`, the output must be a distinct `.pdf`, and arguments
are empty. Before invoking LibreOffice, the staged source passes the mandatory
deep PPTX package gate. The generated PDF must reopen and its page count must
equal the source slide count before atomic promotion.

## Legacy PPT semantic conversion

```json
{
  "schema_version": "1.0",
  "operation": "pptx.convert.legacy",
  "input": "legacy.ppt",
  "output": "converted.pptx",
  "arguments": {},
  "options": { "fidelity": "enhanced" }
}
```

The input must be a `.ppt`, the output must be a distinct `.pptx`, and
arguments are empty. The source is bounded to 128 MiB and must pass a Compound
File Binary magic and header preflight before LibreOffice receives a private
staged copy. Macros are never executed; LibreOffice runs under the same
macro-disabled, isolated profile policy as the other operations.

The generated `.pptx` must pass the standard OOXML reopen gate and the deep
package validator before atomic promotion. A successful conversion reports
`degraded` because this is semantic reconstruction: diagnostics set
`semantic_conversion` to `true` and `source_visual_preservation_claimed` to
`false`. It does not claim pixel-identical preservation of the binary source.
Provider failure, timeout, malformed output, or a failed gate preserves both
the source and any prior destination.

## Render evidence bundle

```json
{
  "schema_version": "1.0",
  "operation": "pptx.render",
  "input": "deck.pptx",
  "output": "deck-render.zip",
  "arguments": {},
  "options": { "fidelity": "enhanced" }
}
```

The output ZIP contains exactly:

```text
deck.pdf
manifest.json
slides/slide-001.png
slides/slide-002.png
...
```

`manifest.json` records the source hash, slide/page count, and every contained
artifact's relative path, byte count, SHA-256, and PNG dimensions. The required
`visual.render` gate passes only after the PDF page count, every PNG structure
and aspect ratio, ZIP member set, manifest, and contained hashes agree.

Rendering is bounded to 50 slides, 30 seconds per LibreOffice conversion, 120
seconds total provider work, 16 MiB per PNG, 256 MiB aggregate PNG data, 128 MiB
for the PDF, and 384 MiB for the final bundle. A limit, timeout, process failure,
page mismatch, or malformed output prevents publication and preserves the
source and prior destination.

This bundle proves that LibreOffice rendered each slide; it is not a browser or
reference-image parity claim. HTML conversion performs its separate thresholded
browser-source comparison when both screenshot and LibreOffice evidence exist.
