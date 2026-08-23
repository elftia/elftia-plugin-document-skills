# XLSX native charts

`xlsx.create` accepts a workbook-level `charts` array. These are real DrawingML chart parts,
not the legacy `chart_reference` placeholder. Each chart writes a chart part, worksheet drawing,
two-cell anchor, relationships, and content-type overrides and is reopened by an independent
consumer before promotion.

```json
{
  "name": "RevenueChart",
  "sheet": "Data",
  "type": "column",
  "title": "Quarterly revenue",
  "anchor": "E2:L18",
  "series": [
    {
      "name": "Revenue",
      "categories": "Data!$A$2:$A$5",
      "values": "Data!$B$2:$B$5",
      "color": "#4472C4"
    }
  ],
  "show_legend": true,
  "legend_position": "r",
  "x_axis_title": "Quarter",
  "y_axis_title": "Revenue",
  "y_axis_number_format": "#,##0.00",
  "data_labels": {"show_value": true}
}
```

Supported `type` values are `column`, `bar`, `line`, `pie`, and `scatter`. Scatter series use
`x_values` and `y_values`; all other series use `categories` and `values`. Every range must be a
one-dimensional, existing-sheet A1 range with equal point counts, and external-workbook ranges
are rejected. Colors use six-digit RGB or eight-digit ARGB. Pie charts do not accept axis fields.

`chart_add` carries a full `chart` object. `chart_update` uses `sheet` and the existing `name` as
its selector and carries a full replacement `chart`; this is the safe series/range update path.
`chart_delete` uses `sheet` and `name`. Names are unique, relationship targets remain contained,
and the final chart on an otherwise empty drawing removes its declared drawing/chart parts.
