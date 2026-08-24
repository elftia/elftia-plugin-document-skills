# Ordinary grouped summaries

`xlsx.summary.aggregate` creates an ordinary worksheet and native Excel table in a distinct
`.xlsx` or `.xlsm` output. It is deliberately not a native pivot table or pivot cache.

```json
{
  "schema_version": "1.0",
  "operation": "xlsx.summary.aggregate",
  "input": "sales.xlsx",
  "output": "sales-summary.xlsx",
  "arguments": {
    "source": {"sheet": "Data", "range": "A1:D1000"},
    "group_by": ["Region"],
    "aggregates": [
      {"column": "Revenue", "function": "sum", "as": "Total Revenue"},
      {"column": "Units", "function": "average", "as": "Average Units"},
      {"function": "count", "as": "Rows"}
    ],
    "sort": [{"column": "Total Revenue", "direction": "desc"}],
    "top_n": 10,
    "target": {
      "sheet": "Summary",
      "start_cell": "A1",
      "table_name": "SalesSummary",
      "table_style": "TableStyleMedium2"
    },
    "formula_policy": "reject",
    "numeric_policy": "strict",
    "recalculation": "skip"
  }
}
```

Aggregate functions are `sum`, `average`, `min`, `max`, `count`, `count_nonblank`, and
`count_distinct`. Multiple stable sort keys and an explicit `top_n` are supported. `top_n`
requires a sort key so selection is deterministic. Text group keys remain text, including leading
zeros. Numeric aggregation is strict by default; `numeric_policy: "coerce-text"` explicitly
accepts finite decimal text.

The first source row supplies unique text headers. Bounded limits cover the source row/column
span, output group count, and output cells. The target sheet must not already exist. The output is
reopened and checked for exact values, native-table range/style/headers, and the absence of a pivot
relationship on the new sheet before atomic promotion.

Formula source cells fail closed by default. `formula_policy: "cached"` permits only present stored
formula results, never invokes a calculation provider, and always reports a warning/degradation.
For `.xlsm`, input/output must both be `.xlsm`, `keep_vba: true` is mandatory, VBA remains inert,
and the normal macro/signature copy-through evidence applies.
