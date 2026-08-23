# Typed native PPTX creation

Use this reference only for `pptx.create` requests. Typed creation writes a
new `.pptx`; it does not accept an input deck and never mutates an existing
file.

## Image contract

`image_reference.path` (or the backward-compatible `filename` key) must name
an existing local PNG, JPEG, or single-frame GIF. The implementation checks
magic bytes rather than trusting the extension or declared content type,
enforces per-file, aggregate-byte, dimension, and decoded-pixel ceilings, and
applies JPEG EXIF orientation. Remote/UNC paths, SVG, animated GIF, malformed
metadata, and content-type mismatch are rejected without publishing output.

Supported image properties:

- `fit`: `contain`, `cover`, or `stretch`;
- `crop`: fractional `left`, `top`, `right`, and `bottom` values that leave a
  visible area;
- `opacity`: `0.0` through `1.0`;
- `rotation`: degrees from `-360` through `360`;
- `alt_text`, `z_order`, and an optional EMU `frame` (`x`, `y`, `cx`, `cy`).

Successful creation embeds the exact validated source bytes and reports
`source_asset_sha256`, `embedded_media_part`, detected content type and pixel
dimensions, EXIF orientation, fit, and `fallback: "native"`.

## Chart contract

Charts support `bar`, `column`, `line`, `pie`, and `scatter`. Category charts
use `categories` and series shaped as `{name, values}`. Scatter series use
`{name, x_values, y_values}`. Values must be finite bounded numbers and series
lengths must match their category or x/y counterpart.

Optional chart properties include:

- `title`;
- `legend.show` and `legend.position`;
- category/value axes, or x/y axes, with `title` and `number_format`;
- `data_labels.show_value`, `show_category_name`, and `show_series_name`;
- a bounded list of six-digit RGB `colors`.

Charts are native DrawingML chart objects backed by legal literal caches.
Successful creation reports `editable: true`, `fallback: "native"`, and
`data_storage: "literal-cache"`. Read and inspect return chart type, title,
series/categories/values, and axis ids, cross-axis ids, titles, positions, and
number formats.

## Example

```json
{
  "schema_version": "1.0",
  "operation": "pptx.create",
  "output": "C:/work/native-deck.pptx",
  "arguments": {
    "deck": {
      "metadata": {
        "title": "Regional plan",
        "creator": "Elftia",
        "subject": "Q3"
      },
      "slides": [
        {
          "layout": "content",
          "title": "Regional plan",
          "shapes": [
            {"text": "Editable summary", "runs": []}
          ],
          "table": null,
          "image_reference": {
            "path": "C:/work/map.png",
            "content_type": "image/png",
            "fit": "contain",
            "alt_text": "Regional coverage map"
          },
          "chart_reference": {
            "title": "Units by region",
            "chart_type": "column",
            "categories": ["North", "South"],
            "series": [
              {"name": "Plan", "values": [4, 7]}
            ],
            "legend": {"show": true, "position": "bottom"},
            "axes": {
              "category": {"title": "Region", "number_format": "General"},
              "value": {"title": "Units", "number_format": "0"}
            },
            "data_labels": {"show_value": true},
            "colors": ["3366CC"]
          },
          "notes": "Source data approved for Q3."
        }
      ]
    }
  }
}
```

Omitted `slide_size` uses the existing Core default. Omitted chart series keep
backward compatibility by creating one native `Series 1` point rather than an
empty chart shell.
