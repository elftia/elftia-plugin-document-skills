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

Supported `type` values are `column`, `bar`, `line`, `pie`, `scatter`, `area`, `radar`, `bubble`,
and `combo`. Scatter series use `x_values` and `y_values`; bubble series additionally require
`bubble_sizes`; category charts use `categories` and `values`. Every range must be a
one-dimensional, existing-sheet A1 range with equal point counts, and external-workbook ranges
are rejected. Colors use six-digit RGB or eight-digit ARGB. `style` is a built-in chart style id
from 1 through 48; radar charts also accept `radar_style: "standard"|"marker"|"filled"`.

Combo charts support column, line, and area series. Each series declares `chart_type`; optional
`axis: "secondary"` binds that series to a real second axis pair. The chart-level
`secondary_x_axis_*` and `secondary_y_axis_*` title/number-format fields are accepted only when
a secondary series exists. At least one primary series and at least two distinct combo plot types
are required.

Non-pie/radar series may carry one `trendline` and bounded `error_bars`. Trendlines support
linear, exponential, logarithmic, polynomial, power, and moving-average modes; polynomial order
and moving-average period are explicit. Error bars support fixed, percentage, standard deviation,
standard error, and custom plus/minus ranges. X-direction error bars are limited to scatter and
bubble series. Custom error ranges must match the plotted point count.

Chart readback reports the plot type(s), series-to-axis assignment, style, advanced series fields,
and both axis pairs. Structural row/column edits rewrite category/value/x/y/bubble/custom-error
references and drawing anchors; unsafe deletions fail closed. Series color and chart style are
reopened after the mutation, not inferred from the request.

`chart_add` carries a full `chart` object. `chart_update` uses `sheet` and the existing `name` as
its selector and carries a full replacement `chart`; this is the safe series/range update path.
`chart_delete` uses `sheet` and `name`. Names are unique, relationship targets remain contained,
and the final chart on an otherwise empty drawing removes its declared drawing/chart parts.
