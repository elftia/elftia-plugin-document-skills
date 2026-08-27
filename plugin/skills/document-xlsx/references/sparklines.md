# Native worksheet sparklines

Each sheet may declare a bounded `sparklines` array. Every entry creates a real x14 sparkline
group with one output cell and one one-dimensional data range:

```json
{
  "location": "E2",
  "data": "Data!B2:D2",
  "type": "line",
  "empty_cells": "connect",
  "markers": true,
  "high_point": true,
  "low_point": true,
  "negative_points": true,
  "manual_min": -10,
  "manual_max": 100,
  "color": "#4472C4",
  "negative_color": "#C00000"
}
```

Types are `line`, `column`, and `win_loss`; empty-cell policies are `gap`, `zero`, and
`connect`. Optional first/last/high/low/negative markers, right-to-left direction, bounded custom
axis limits, and series/negative/axis/marker/first/last/high/low colors are typed. The data range
must contain 2–10,000 cells on an existing sheet; external-workbook and two-dimensional ranges
are rejected. Output locations are unique single cells on the containing worksheet.

`sparkline_add` carries a full `sparkline` object. `sparkline_update` selects the old output cell
with `ref` and carries a full replacement, which may move it. `sparkline_delete` uses `sheet` and
`ref`. Readback projects all fields from the emitted x14 XML. Row/column structural edits rewrite
both data ranges and output cells; a destructive intersection fails closed.
