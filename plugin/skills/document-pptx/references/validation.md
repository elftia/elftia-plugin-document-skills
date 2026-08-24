# PPTX validation evidence

Core PPTX creation and mutation always run package magic, bounded archive,
reopen, semantic, operation-specific, and deep package gates before publishing
an artifact. HTML conversion uses the same mandatory Core path in addition to
its browser-scene and optional visual comparison gates.

The deep gate validates:

- root reachability and orphan parts;
- relationship sources, targets, XML relationship bindings, and content types;
- slide order plus slide → layout → master → theme and notes dependency chains;
- unique positive drawing ids and unique numeric slide ids;
- chart series/order, data caches, axes and cross-axis references;
- bounded simple-range agreement between chart caches and internal embedded
  `.xlsx` workbooks;
- slide, notes, chart, media, layout, master, and theme inventory.

Unsupported workbook formulas are reported as unchecked ranges, not as passes.
Only internal chart package relationships to bounded `.xlsx` workbook parts are
accepted by this validation path. Macros, OLE objects, ActiveX, external links,
and other dangerous inventory remain rejected.

`static_layout` evidence is a bounded heuristic audit. It reports warnings for
invalid or out-of-bounds boxes, major overlap risk, text overflow risk, small
fonts, low direct RGB contrast, empty title/body placeholders, and residual
debug/TODO/template tokens. These warnings do not pretend to be rendered visual
failures and do not replace LibreOffice/browser comparison.

## OpenXML SDK schema operation

Request shape:

```json
{
  "operation": "pptx.validate.schema",
  "input": "deck.pptx",
  "arguments": {},
  "options": { "fidelity": "enhanced" }
}
```

The operation is read-only, accepts no output or arguments, preserves the input
hash, and is advertised only when `dotnet-openxml` is callable. A valid package
returns `success` and a required passing `schema.full` gate. Schema errors return
`failed` and bounded error evidence. Provider absence returns `unavailable`; it
is never converted into a passing schema result.
