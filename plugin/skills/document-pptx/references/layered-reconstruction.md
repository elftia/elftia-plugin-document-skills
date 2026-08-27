# Layered reconstruction from a raster

## Probe before reconstruction

Run the parent Skill's `capabilities --json` command and find the operation
named `pptx.reconstruct.from-image`. It is always discoverable, but only
`available: true` permits invocation. Its callable provider list must contain
`ocr-vision`.

The production provider is unavailable by default because this release does
not bundle, download, or invoke an OCR/vision model, executable, SDK, or network
service. An ordinary installation therefore returns `unavailable`, creates no
PPTX, and preserves any prior destination. Do not substitute a one-picture deck
or install a provider during the document operation. The deterministic adapter
used by the test fixtures is test-only and is not production availability.

## Input and policy contract

- `input` is a regular local `.png`, `.jpg`, or `.jpeg` whose suffix agrees
  with its magic bytes. The current ceilings are 8 MiB, 8,192 pixels per
  dimension, and 40,000,000 total pixels.
- `output` is a distinct `.pptx` path. In-place reconstruction is unsupported.
- `provider_policy` is exactly
  `{"provider":"ocr-vision","on_unavailable":"fail"}`. There is no `auto`
  selection, network fallback, or single-image fallback.
- `audit_asset_policy` is required and is exactly `retain` or `discard`.
- `confidence_threshold` is optional, finite, within `[0,1]`, and defaults to
  `0.75`.
- Optional `metadata` is limited to bounded `title`, `creator`, and `subject`
  strings. Unknown argument or metadata keys fail closed.

## Request

```json
{
  "schema_version": "1.0",
  "operation": "pptx.reconstruct.from-image",
  "input": "C:/absolute/deck/source.png",
  "output": "C:/absolute/deck/reconstructed.pptx",
  "arguments": {
    "provider_policy": {
      "provider": "ocr-vision",
      "on_unavailable": "fail"
    },
    "audit_asset_policy": "retain",
    "confidence_threshold": 0.75,
    "metadata": {
      "title": "Reconstructed slide",
      "creator": "Deck producer",
      "subject": "Optional subject"
    }
  },
  "options": {
    "fidelity": "core"
  }
}
```

Invoke it with the parent Skill's frozen `run --request` command.

## Layering and fallback boundary

The provider returns one canvas and at most 512 strictly validated elements.
Each element carries a stable id, kind, geometry, source region, unique reading
order, confidence, complete style, and text where applicable. Provider values
cannot control paths, relationships, OOXML, resource ceilings, or aggregate
coverage.

Confident text and shapes emit as native editable objects. A confident image
observation emits as its independently positioned cropped picture. An element
below the threshold becomes one visible picture cropped to that element's
smallest declared source region. An uncropped, hidden, undeclared, full-canvas,
or whole-slide source image is never accepted beneath nominally editable
objects. If only a full-slide raster could be produced, the operation fails and
publishes no deck.

## Interpret the result

Read `diagnostics.operation_result`:

- `source` reports the screened raster's media type, dimensions, byte count,
  and SHA-256.
- `provider_policy` repeats the exact selected fail-closed policy.
- `reconstruction.canvas` and `confidence_threshold` bind the receipt to the
  request and raster.
- `reconstruction.elements` contains bounded records with `id`, `kind`,
  `geometry`, `source_region`, `reading_order`, `confidence`, `text`, and final
  `editable` or `rasterized` outcome. `ocr_text` preserves text observations in
  stable reading order.
- `reconstruction.editable_coverage.by_area` and `by_object_count` each report
  `editable`, `total`, and `ratio`. Area uses overlap-safe union accounting over
  represented source regions; count uses emitted objects. They are independent
  evidence and may differ. `whole_slide_raster` must be `false`.
- `emission` and the required `reconstruction-layer-integrity` validation gate
  cross-check the receipt, scene, emitted inventory, crop evidence, and actual
  PPTX package.

A successful all-editable reconstruction reports `success`. Any disclosed
low-confidence element crop reports `degraded` while required gates still pass.
`invalid_request`, `failed`, or `unavailable` publishes no new destination.

## Audit asset lifecycle

`retain` publishes a content-addressed operation-owned copy beside the PPTX and
returns its path, media type, byte count, and SHA-256 under `audit_asset`; the
same file appears as a `report` artifact. It is evidence only and is not a
hidden slide background. If the identical audit file already exists it may be
reused; different content at that path fails closed.

`discard` returns only `{"policy":"discard","retained":false}` and leaves no
operation-owned source copy. Both policies preserve the caller-owned input.
Provider, validation, audit publication, or PPTX promotion failure also
preserves the input and any prior destination, then removes private snapshots
and staged files.
