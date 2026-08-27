# Constrained SVG and scene export

Both B5 operations use the public frozen uv/Python façade. Do not invoke an
emitter module, provider script, Node, PowerPoint, or LibreOffice directly.

## SVG to editable PPTX

Create `request.json` with a regular local `.svg` input and a distinct `.pptx`
output:

```json
{
  "schema_version": "1.0",
  "operation": "pptx.create.from-svg",
  "input": "C:/work/slide.svg",
  "output": "C:/work/slide.editable.pptx",
  "arguments": {
    "fallback_policy": "reject",
    "metadata": {
      "title": "Editable SVG slide",
      "creator": "Elftia",
      "subject": ""
    }
  }
}
```

Run only:

```text
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" run --request request.json
```

The root must declare finite `width`, `height`, and `viewBox` values with a
16:9 aspect ratio. The closed native profile accepts bounded `path`, `rect`,
`line`, `ellipse`, `polygon`, `g`, `text`, `tspan`, bounded transforms, solid
fill/stroke, approved linear gradients, and adjacent local bounded PNG/JPEG
images. Typed table/chart semantic groups use project-authored
`data-elftia-kind`, `data-elftia-bounds`, and canonical `data-elftia-model`
attributes; arbitrary caller XML is not accepted as OOXML.

The following always fail closed: DTD/entity declarations, foreign XML
namespaces, `script`, `foreignObject`, event attributes, external/remote
references, animation, unsupported filters without an explicit allowed
element fallback, malformed or over-budget paths, duplicated ids, and
near-whole-slide fallback regions. `element-rasterize` is opt-in and requires
`data-pptx-fallback-image` on that one unsupported element. It never authorizes
a slide-sized background image.

Inspect `diagnostics.operation_result`:

- `mapping` binds each SVG source id to the emitted native shape id, kind,
  geometry, parent group, outcome, and asset hash;
- `coverage` separates native, approximated, and rasterized area and always
  reports `whole_slide_raster: false` on success;
- `conversion` reports node/resource limits and fidelity counts;
- schema and visual gates remain distinct. Missing LibreOffice makes the
  optional visual gate `unavailable` and the result `degraded`; it does not
  invalidate passed Core structure and does not become visual success.

## PPTX to A-Contract scene bundle

`pptx.scene.export` requires an installed owner copy of
`@elftia/presentation-contracts@1.0.0` with manifest digest
`sha256:78989d9891c80a3f89ad25d7d31e4a431737131226df4494fc14dee1bfe3215a`.
The caller supplies both its absolute root and exact digest:

```json
{
  "schema_version": "1.0",
  "operation": "pptx.scene.export",
  "input": "C:/work/source.pptx",
  "output": "C:/work/source-scene",
  "arguments": {
    "contract": {
      "root": "C:/contracts/presentation-contracts",
      "manifest_sha256": "sha256:78989d9891c80a3f89ad25d7d31e4a431737131226df4494fc14dee1bfe3215a"
    },
    "identity": {
      "namespace": "example.synthetic",
      "source_template_id": "source-deck",
      "source_template_version": "1.0.0"
    },
    "mode": "strict"
  }
}
```

Run only:

```text
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" run --request request.json
```

The output path must not already exist as a directory, file, junction,
symlink, or broken symlink. The operation validates the entire source and
bundle in a private root, copies the complete tree into the captured physical
destination parent, and atomically renames it into place without replacement.
Failure preserves the input and any pre-existing destination bytes.

`strict` mode publishes nothing when a shape, effect, inheritance form, image
format, chart, or graphic frame is outside the supported round-trip subset.
`tolerant` mode may publish a degraded bundle: unsupported objects retain
source slide/object identity, bounds when known, and a reason in opaque
inventory, but receive `editability: none`; they are not guessed or silently
dropped.

The published tree contains:

- `manifest.json`: input identity, A-Contract pin, source mapping, unsupported
  inventory, and SHA-256/byte count for every other member;
- `deck-ir.json`: schema-validated Deck IR with owner-defined canonical
  `contentHash` and stable deck/slide/object ids;
- `slide-*.svg`: constrained 1920x1080 per-slide SVG;
- `assets/<sha256>.<ext>`: content-addressed local images.

Core success proves structural/semantic projection and bundle hash integrity.
It does not claim PowerPoint, LibreOffice, or pixel-level visual parity unless
those consumers and visual checks actually ran and their separate evidence is
present.
