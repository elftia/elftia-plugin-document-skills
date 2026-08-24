# Transactional PPTX editing

`pptx.edit` accepts a non-empty bounded `edits` array and always writes a
distinct output. Ordinary `.pptx` input requires `.pptx` output. A `.pptm`
input requires `.pptm` output plus explicit `arguments.keep_vba: true`. The
entire array commits once: a bad selector,
precondition, local asset, relationship, or semantic validation result produces
no partial output.

## Inert PPTM keep-VBA policy

Keep-VBA never executes, parses, edits, or resigns macro code. It admits only a
macro-enabled presentation with one internal presentation-to-`vbaProject.bin`
relationship, the correct macro/VBA content types, and no ActiveX, OLE,
external target, DDE, executable, attached-template, or other dangerous graph.
Internal `.xlsx` chart workbooks remain allowed as data packages.

```json
{
  "operation": "pptx.edit",
  "input": "deck.pptm",
  "output": "deck-edited.pptm",
  "arguments": {
    "keep_vba": true,
    "edits": [
      {"type": "slide_text", "slide": 1, "ref": "", "value": "Updated"}
    ]
  }
}
```

The source and candidate VBA bytes must have the same SHA-256. The result
records part, content type, internal relationship, byte count, source/output
hash, and `copy_through: "exact-bytes"` under
`diagnostics.operation_result.macro_copy_through`. Digitally signed packages
are rejected with `signature_invalidation_required: true`; signatures are
never silently copied after content changes.

## Stable selectors and preconditions

Run `pptx.read` first. Every projected top-level object includes:

```json
{
  "selector": {"id": "7", "name": "Revenue chart", "type": "chart"},
  "precondition_sha256": "<sha256-of-selected-object-xml>"
}
```

Use the returned selector verbatim. `id` or `name` is required; supplying both
requires both to match. Supported selector types are `shape`, `image`, `table`,
and `chart`. A selector must match exactly one object. When a
`precondition_sha256` is supplied, it is checked against that selected object,
not the whole slide.

## Slide lifecycle primitives

| Type | Required fields | Notes |
|---|---|---|
| `slide_add` | `slide` | Optional `position`; reuses a named/part layout and accepts the typed slide object contract |
| `slide_delete` | `slide` | Removes only dependencies no longer reachable from the package root |
| `slide_duplicate` | `slide` | Optional `position`; deep-copies slide-local media/chart/notes dependencies |
| `slide_copy` | `source_slide` | Optional local `.pptx` `source` and `position`; cross-deck copy imports the contained dependency graph |
| `slide_move` / `slide_reorder` | `slide`, `position` | Changes presentation order without rewriting slide payloads |
| `slide_size` | `size` | One deck-level change per transaction; requires bounded integer `cx`/`cy` plus a supported PresentationML `type` and fails if any final slide object is unresolved or out of bounds |

`slide_delete`, `slide_duplicate`, `slide_copy`, and reorder operations accept
an optional slide-level `precondition_sha256`.

Slide size is never selected by slide number. The explicit deck-level form is:

```json
{
  "type": "slide_size",
  "size": {"cx": 12192000, "cy": 6858000, "type": "screen16x9"}
}
```

The edit does not implicitly scale or move content. It validates the final
transaction state, including inherited placeholder geometry, before emitting
the candidate and reports the previous/new size plus checked-object counts.

Master/layout/theme graph edits are also transactional but have their own
closed design-part selectors and contracts. Read `design-authoring.md` before
using `master_*`, `layout_*`, or `theme_update`.

## Object primitives

| Object | Add/update/delete forms | Supported values |
|---|---|---|
| shape | `shape_add`, `shape_update`, `shape_delete` | frame, geometry, fill, line, opacity, shadow, rotation, z-order, name, text |
| text | `text_update`, `text_style` | text/paragraphs; run/paragraph font, size, color, emphasis, alignment, spacing, bullets/numbering, autofit |
| image | `image_add`, `image_replace`, `image_crop`, `image_delete` | bounded local PNG/JPEG/static GIF, frame, fit/crop, opacity, rotation, alt text, z-order |
| table | `table_add`, `table_update`, `table_delete` | rectangular rows, widths, heights, bounded non-overlapping merges, frame, name, z-order |
| chart | `chart_add`, `chart_update`, `chart_delete` | native bar/column/line/pie/scatter data, title, legend, axes, labels, colors, frame, name, z-order |
| notes | `notes_update` | creates speaker notes when absent or replaces the editable notes text |
| hyperlink | `hyperlink_add/update/remove` | internal `target_slide` only |
| action | `action_add/update/remove` | `first`, `last`, `next`, or `previous` only |

Add operations use an `object`; selected updates use `properties`, except
`image_replace` and `chart_update`, which use a complete `object`.

Example:

```json
{
  "schema_version": "1.0",
  "operation": "pptx.edit",
  "input": "deck.pptx",
  "output": "deck-edited.pptx",
  "arguments": {
    "edits": [
      {
        "type": "shape_update",
        "slide": 1,
        "selector": {"id": "7", "name": "Callout", "type": "shape"},
        "precondition_sha256": "<hash returned by pptx.read>",
        "properties": {
          "fill": "336699",
          "opacity": 0.8,
          "rotation": 4,
          "z_order": 3
        }
      },
      {
        "type": "hyperlink_add",
        "slide": 1,
        "selector": {"id": "7", "name": "Callout", "type": "shape"},
        "target_slide": 3
      },
      {"type": "notes_update", "slide": 1, "value": "Presenter-only context"}
    ]
  }
}
```

## Explicit scope

- Speaker notes are created and updated natively.
- Existing comments and threaded comments are preserved by copy-through but are
  not created or edited by this contract.
- Existing hidden-slide state is preserved. There is no hidden-state mutation
  primitive in this contract.
- Group-child selection is not advertised; selectors address top-level slide
  objects.
- External hyperlinks/actions, scripts, macro creation/editing/execution, OLE
  activation, and raw OOXML injection are not accepted. The keep-VBA exception
  preserves only an already-present validated VBA project byte-for-byte.

Successful output reports the applicable `slide_lifecycle`, `slide_size`,
`design_edits`, and/or `object_edits` evidence under
`diagnostics.operation_result`, including copied dependency mappings, added and
removed parts, native image/chart records, inheritance checks, and object
hashes.
