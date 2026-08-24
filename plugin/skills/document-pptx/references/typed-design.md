# Typed themes, layout recipes, and template bases

Use these fields with `pptx.create` when the presentation needs a consistent
native design system. The emitter writes editable DrawingML objects and a real
theme/master/layout graph; it does not flatten slides to images.

## Theme and layout-token contract

`arguments.deck.theme` accepts these bounded groups:

- `name`
- `palette`: `dk1`, `lt1`, `dk2`, `lt2`, `accent1` through `accent6`,
  `hlink`, and `folHlink`
- `fonts`: `major` and `minor`
- `effects.shadow`: enabled, blur/distance in EMUs, direction in degrees,
  six-digit color, and opacity
- `background`
- `default_text`: title/body colors and sizes plus `bold_titles`
- `default_shape`: fill, line, and opacity
- `default_chart.colors`: a non-empty bounded palette

Colors are six-digit RGB values. Unknown tokens are rejected instead of being
ignored.

`arguments.deck.layout_tokens` accepts:

- `safe_margins`: top, right, bottom, and left in EMUs
- `grid`: 2-24 columns and an EMU gutter
- `spacing`: `xs`, `sm`, `md`, `lg`, and `xl` in EMUs
- `typography_scale`: title, section, body, and caption point sizes

Every slide may set `recipe` to one of `cover`, `section`, `content`,
`two-column`, `image-focus`, `comparison`, or `summary`. Legacy
`layout: title` maps to `cover`; `layout: content` maps to `content` when no
recipe is supplied. The result reports the selected layout part and recipe in
`diagnostics.operation_result.creation.layout_recipes`.

## Minimal request fragment

```json
{
  "operation": "pptx.create",
  "output": "designed.pptx",
  "arguments": {
    "deck": {
      "metadata": {"title": "Designed deck", "creator": "Me", "subject": ""},
      "theme": {
        "palette": {"accent1": "006D77", "accent2": "E29578"},
        "fonts": {"major": "Aptos Display", "minor": "Aptos"}
      },
      "layout_tokens": {
        "safe_margins": {"top": 300000, "right": 400000, "bottom": 300000, "left": 400000},
        "grid": {"columns": 12, "gutter": 200000}
      },
      "slides": [
        {
          "layout": "content",
          "recipe": "two-column",
          "title": "Comparison",
          "shapes": [{"text": "Left", "runs": []}, {"text": "Right", "runs": []}],
          "table": null,
          "chart_reference": null,
          "image_reference": null,
          "notes": null
        }
      ]
    }
  }
}
```

## Template as base

Set `arguments.template` to a bounded local `.pptx` or `.potx` file. Creation preserves
the template's master, layout, and theme parts byte-for-byte, removes its old
slides in the private staging package, and adds the requested typed slides
using compatible layouts. The source template is hash-checked before and after
the operation and is never modified.

Do not also supply `deck.theme` with a template: changing the theme would
contradict byte-for-byte design-graph reuse, so the request is rejected.
Changing the template slide size is also rejected. The result records the
template SHA-256 and preserved design parts under
`diagnostics.operation_result.creation.template_reuse`.

For `.potx`, the emitted `.pptx` changes only the package presentation-main
content type from the template identity to
`presentationml.presentation.main+xml`; it does not rename the source or leave
template identity in the output. The result reports `source_extension`,
`presentation_content_type`, and `template_main_type_normalized`.

For transactional master/layout/theme changes and template lint, read
`design-authoring.md`. Those edits use exact design-part selectors and are
separate from template-as-base byte-for-byte reuse.
