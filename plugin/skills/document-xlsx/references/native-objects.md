# XLSX native tables, validations, and conditional formats

These fields create real SpreadsheetML objects and are also projected in detail by `xlsx.read`
and `xlsx.inspect.structure`. They are closed typed contracts; unknown fields are rejected.

## Native tables

Workbook `tables` entries use `name`, `sheet`, `ref`, and an optional built-in `style` such as
`TableStyleMedium2`. Names are workbook-unique, ranges on a sheet cannot overlap, and the first
row must contain unique non-empty text headers. Creation writes the table part, worksheet
relationship, `tableParts`, content-type override, columns, auto filter, and style information.

## Data validations

Each sheet may contain `data_validations`. Every rule has `ref`, `type`, and `formula1`.
Supported types are `list`, `whole`, `decimal`, `date`, `time`, `textLength`, and `custom`.
Numeric/date/time/text-length types also require an operator; `between` and `notBetween` require
`formula2`. Optional fields are `allow_blank`, input/error-message flags and text, and
`error_style` (`stop`, `warning`, or `information`). External-workbook formulas and overlapping
create/add ranges are rejected.

```json
{
  "ref": "B2:B100",
  "type": "whole",
  "operator": "between",
  "formula1": "1",
  "formula2": "100",
  "allow_blank": true,
  "show_input_message": true,
  "prompt_title": "Amount",
  "prompt": "Enter 1-100",
  "show_error_message": true,
  "error_title": "Invalid",
  "error": "Out of range",
  "error_style": "stop"
}
```

## Conditional formats

Each sheet may contain `conditional_formats`. All rules require `ref` and `type`; priorities are
assigned deterministically in request order. `cellIs` and `expression` use `formulas` and a
differential `style` containing `font`, `fill`, and/or `border`. Visual rules use `thresholds`:

- `colorScale`: two or three thresholds and the same number of `colors`;
- `dataBar`: two thresholds, `color`, and optional `show_value`;
- `iconSet`: a supported 3/4/5-icon set, matching thresholds, `show_value`, and `reverse`.

Threshold types are `min`, `max`, `num`, `percent`, `percentile`, and `formula`; all except
`min`/`max` require a string `value`. External-workbook formulas are rejected. Edit selectors
use exact `ref` plus `priority`, so ambiguous rules fail before promotion.
