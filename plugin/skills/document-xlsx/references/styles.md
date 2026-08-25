# XLSX create styles and number formats

`xlsx.create` accepts the same closed `style` object on columns, rows, and cells. Styles are
merged in column → row → cell order, then deduplicated into stable workbook style ids. A cell
override changes only the nested fields it supplies.

```json
{
  "columns": [
    {
      "ref": "A:C",
      "width": 18,
      "hidden": false,
      "style": {"font": {"color": "#334455"}}
    }
  ],
  "rows": [
    {
      "height": 24,
      "hidden": false,
      "style": {
        "font": {
          "name": "Aptos",
          "size": 12,
          "bold": true,
          "italic": false,
          "underline": "single",
          "color": "#112233"
        },
        "fill": {"pattern": "solid", "color": "#DDEEFF"},
        "border": {
          "bottom": {"style": "thin", "color": "#445566"}
        },
        "alignment": {
          "horizontal": "center",
          "vertical": "top",
          "wrap": true,
          "rotation": 0,
          "shrink_to_fit": false,
          "indent": 0
        },
        "protection": {"locked": true, "hidden": false},
        "number_format": {"id": 165}
      },
      "cells": [
        {
          "ref": "A1",
          "value": "45292",
          "type": "n",
          "style": {"font": {"italic": true}}
        }
      ]
    }
  ],
  "number_formats": [
    {"id": 165, "code": "yyyy-mm-dd"}
  ]
}
```

Colors use six-digit RGB or eight-digit ARGB hex. Six-digit values receive an opaque `FF`
alpha prefix. Custom number-format ids are `164..65535`, must be uniquely declared in a sheet's
`number_formats`, and are workbook-global after parsing. A style may instead use
`{"number_format": {"code": "0.00%"}}`; built-in codes reuse built-in ids, while other codes
receive the next deterministic custom id.

For `xlsx.edit`, use a `number_format.code` to append or reuse a custom format without rewriting
the existing style table. A custom `number_format.id` is accepted only when that id already
exists in the source workbook; a missing id fails before promotion.

The supported style fields are:

- `font`: `name`, `size`, `bold`, `italic`, `underline`, `color`;
- `fill`: `pattern`, `color`, `background_color`;
- `border`: `left`, `right`, `top`, `bottom`, `diagonal`, plus diagonal/outline flags;
- `alignment`: `horizontal`, `vertical`, `wrap`, `rotation` (`-90..90`),
  `shrink_to_fit`, `indent`;
- `protection`: `locked`, `hidden`;
- `number_format`: exactly one of `id` or `code`.

`xlsx.read` returns the original `style_index`, the effective `resolved_style_index`, a
`style_source`, and the resolved `style` including theme/indexed color references when present.
