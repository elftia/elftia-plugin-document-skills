# Advanced PPTX object inventory

`pptx.inspect.structure` classifies advanced presentation content without
executing or mutating it. The request remains the ordinary read-only inspect
contract:

```json
{
  "schema_version": "1.0",
  "operation": "pptx.inspect.structure",
  "input": "deck.pptx",
  "arguments": { "include_hashes": true }
}
```

Read `diagnostics.operation_result.advanced_objects` for:

- SmartArt/diagram data, drawing, layout, color, and style parts plus their
  contained relationships;
- equation counts by slide;
- audio and video media parts;
- OLE relationship and target-part inventory;
- animation timing and transition presence by slide;
- classic/threaded comment and person metadata parts.

The result always reports `inert_only: true` and
`mutation_supported: false`. Audio/video playback, OLE activation, and
animation/transition execution are explicitly false. Inspection does not
claim that unsupported advanced objects can be rendered, created, or edited.
When `include_hashes` is true, every classified part record includes its
SHA-256; false omits those hashes without changing the inventory.
