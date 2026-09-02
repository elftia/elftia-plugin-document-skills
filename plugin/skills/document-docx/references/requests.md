# DOCX typed requests

Every request uses `schema_version: "1.0"`. Unknown top-level or operation-specific fields are
rejected before provider execution.

## Structured read

```json
{
  "schema_version": "1.0",
  "operation": "docx.read",
  "input": "<input.docx>",
  "arguments": {
    "include_headers_footers": true,
    "max_content_controls": 1000,
    "max_fields": 1000,
    "max_notes": 2000,
    "max_paragraphs": 5000,
    "max_tables": 500,
    "max_table_rows": 5000,
    "max_text_chars": 250000
  }
}
```

Lower caller limits are useful for unknown documents. A reached limit is reported under
`diagnostics.operation_result.truncations` and as `DS_READ_TRUNCATED`.

## Inert structural inspection

```json
{
  "schema_version": "1.0",
  "operation": "docx.inspect.structure",
  "input": "<input.docx-or-docm>",
  "arguments": {
    "include_hashes": true,
    "max_parts": 2000,
    "max_relationships": 5000
  }
}
```

Inspection always reports `mutation_authorized: false`. `.docm` is admitted here only for inert
inventory; inspection does not authorize a later edit.

## Accessibility inspection

```json
{
  "schema_version": "1.0",
  "operation": "docx.inspect.accessibility",
  "input": "<input.docx>",
  "arguments": {"max_issues": 100}
}
```

The Core check is read-only and always evaluates four bounded semantic categories: embedded-image
alternative text, body-heading level continuity, repeating table-header rows, and document-level
language from `dc:language` or Word `docDefaults`. `max_issues` limits returned issue records from
1 through 1,000; `issue_count` still reports the total and `truncated` remains explicit. Findings
return `status: "success"` with accessibility `status: "review_required"`; they are authoring
feedback, not execution failure or WCAG certification.

The operation has no optional provider, so a provider-missing variant does not apply. Supplying an
`output`, a `.docm`/non-DOCX input, an unknown argument, or an out-of-range `max_issues` returns
`invalid_request` and never changes the source.

## Source-neutral creation

`docx.create` accepts exactly one of `document_spec` or `report`. Prefer the versioned
`document_spec` for new agent-authored documents. It is independent of Markdown or any other
source syntax: an upstream adapter may produce the same semantic nodes without changing the DOCX
emitter.

```json
{
  "schema_version": "1.0",
  "operation": "docx.create",
  "output": "<created.docx>",
  "arguments": {
    "document_spec": {
      "version": "1.0",
      "metadata": {"title": "Experiment results"},
      "resources": {
        "result_plot": {"type": "image", "path": "<local-image.png>"}
      },
      "nodes": [
        {"id": "document_title", "type": "title", "text": "Experiment results"},
        {"id": "section_intro", "type": "heading", "level": 1, "text": "Introduction"},
        {"id": "paragraph_summary", "type": "paragraph", "text": "Source-neutral body text."},
        {
          "id": "figure_result",
          "type": "figure",
          "resource": "result_plot",
          "alt_text": "Result plot",
          "width_inches": 4
        },
        {
          "id": "table_result",
          "type": "table",
          "rows": [["Metric", "Value"], ["Accuracy", "98%"]]
        }
      ]
    }
  }
}
```

Version `1.0` supports the generic nodes `title`, `subtitle`, `authors`, `affiliations`, `abstract`,
`keywords`, `heading`, `paragraph`, `figure`, `figure_caption`, `table`, `table_caption`,
`equation`, `equation_caption`, `reference`, `citation`, `bibliography`, and
`bibliography_entry`. Every node has a unique stable ASCII `id`; figures reference a named local
image resource rather than embedding a source-format-specific construct. Equations accept bounded
linear Unicode math and emit editable OMML; LaTeX commands/raw XML are rejected. `reference`
accepts a stable heading/figure/table/equation target and emits only a generated bookmark plus a
restricted dirty `REF <bookmark> \\h` field. A consumer refresh remains required.

Use `style_profile: {"id":"professional-generic","version":"1.0"}` for the built-in named
styles. A user `.docx/.dotx` can instead use `template-mapped` with `source`, exact
`expected_source_sha256`, and a closed `role_styles` map; missing/wrong-type styles, numbering-bound
styles, relationship-bound styles, and source hash drift fail closed. The template file is read
once and the captured `styles.xml` is the validation oracle.

`domain_profile` is independent of the style profile. `academic-paper` supports `en-US` and
`zh-CN`, validates required ordered front matter, adjacent typed captions, localized figure/table/
equation numbering, and bidirectional citation/bibliography keys. Optional `citation_style` is
`author-year` or `numeric`. `technical-report` reuses the same emitter without academic front-
matter requirements. Profile identities and document-spec version are stored in standard custom
properties and returned by `docx.read`.

Stable node identity is written as inert standard OOXML metadata. A later `docx.read` returns
`node_id` and `node_type` on the matching paragraph, image, or table projection. Unknown resources,
duplicate node IDs, unsupported versions/types, raw OOXML, and requests containing both creation
contracts fail before output promotion. See `assets/examples/create-document-spec.json`.

See `assets/examples/create-academic-paper.json` for a complete academic profile composition.

## Semantic comparison

`docx.compare.semantic` is read-only. Compare a spec with an output by passing the same
`document_spec`, or compare before/after with a local hash-bound `baseline` and stable node IDs in
`allowed_changes`. The two modes are mutually exclusive:

```json
{
  "schema_version": "1.0",
  "operation": "docx.compare.semantic",
  "input": "<after.docx>",
  "arguments": {
    "baseline": "<before.docx>",
    "expected_baseline_sha256": "<64-hex-sha256>",
    "allowed_changes": ["paragraph_summary"]
  }
}
```

The result never treats semantic equality as visual equality. See
`assets/examples/compare-semantic.json`.

## Compatible report creation

`report.blocks` is the only required member, and the document contains exactly the blocks
it lists. `metadata`, `header`, `footer`, `sections`, and the trailing `image` are all
optional — omit what the document does not need rather than inventing a placeholder.

```json
{
  "schema_version": "1.0",
  "operation": "docx.create",
  "output": "<created.docx>",
  "arguments": {
    "report": {
      "blocks": [
        {"type": "heading", "text": "Chapter 1", "level": 1},
        {"type": "paragraph", "text": "Body text."}
      ]
    }
  }
}
```

That request produces a one-section document with no table, no image, no header, and no
footer — the package simply has no such parts.

Block types: `heading` (levels 1–6, so a `1.1.1` outline needs no flattening), `paragraph`
(the `Normal` style, or `null`), `table` (the `TableGrid` style), and `image`. The package
carries a `Heading<n>` style for every level up to the deepest one used, and always at least
`Heading1`/`Heading2`. Image blocks render where they appear, so a caller controls placement:

```json
{
  "blocks": [
    {"type": "paragraph", "text": "Figure 1 shows the pipeline."},
    {"type": "image", "path": "<local-image.png>", "alt_text": "Pipeline", "width_inches": 4},
    {"type": "paragraph", "text": "The table below lists throughput."},
    {"type": "table", "style": "TableGrid", "rows": [["Metric", "Value"], ["Status", "Ready"]]}
  ]
}
```

The optional report-level members:

```json
{
  "metadata": {"title": "Quarterly report", "creator": "Elftia"},
  "image": {"path": "<local-image.png>", "alt_text": "Status chart", "width_inches": 4},
  "header": "Quarterly report",
  "footer": "Confidential",
  "sections": [{"orientation": "portrait"}, {"orientation": "landscape"}]
}
```

`report.image` appends one image after the last block; prefer an `image` block unless the
document really wants a trailing figure. A header or footer creates the corresponding part
and section reference; omitting it creates neither. `sections` defaults to a single portrait
section and accepts 1–32.

Header/footer strings retain the original one-plain-paragraph behavior. The additive structured
form contains 1–16 paragraphs with `left|center|right` alignment and 1–64 ordered runs. Each run
contains exactly `{"text":"..."}` or an allowlisted `{"field":"PAGE|NUMPAGES"}`; raw field
instructions and every other field are rejected before creation.

Legacy row-only tables receive deterministic positive fixed widths. A structured table may add
`width_twips`, one positive `column_widths_twips` value per logical column, and bounded `borders`
at `top|left|bottom|right|inside_h|inside_v|header_bottom`. Column widths must sum exactly to the
table width. The academic pack supplies explicit top/header-bottom/bottom rules and suppresses
side, vertical, and other inner rules.

Every image — block or trailing — must be a bounded local PNG, JPEG, or GIF between 0.25 and
10 inches wide. Remote assets and raw OOXML are not accepted.

Creation requests are also bounded in aggregate: at most 8,192 table cells, 32 images,
64 MiB of image bytes, 10,000 structured value/container nodes, and 524,288 UTF-8 bytes
across creation-contract string values. The request-file loader accepts at most 1,048,576 bytes. These
limits are enforced before provider selection and are intentionally below the 2 MiB worker
result envelope.

## Typed edit

Selectors resolve against the immutable input returned by `docx.read`. Paragraph insert/delete,
image/table insertion, bookmarks, links, fields, notes, and numbering continue to target a
top-level body paragraph with zero-based `paragraph_index` and exact `expected_text`.
`paragraph_style` and `run_style` additionally accept any paragraph projected in a body, header,
or footer story, including body table cells. For those two primitives, copy the public story
`part`; it is optional only for the body default `word/document.xml` and required for
header/footer stories. The paragraph index is zero-based within that exact story part.

```json
{
  "schema_version": "1.0",
  "operation": "docx.edit",
  "input": "<input.docx>",
  "output": "<edited.docx>",
  "arguments": {
    "edits": [
      {
        "type": "paragraph_insert",
        "target": {"story": "body", "paragraph_index": 2, "expected_text": "Total"},
        "position": "after",
        "text": "Reviewed total",
        "style": "Normal"
      },
      {
        "type": "paragraph_style",
        "target": {
          "story": "body",
          "part": "word/document.xml",
          "paragraph_index": 2,
          "expected_text": "Total"
        },
        "style": "Heading2"
      },
      {
        "type": "run_style",
        "target": {"story": "body", "paragraph_index": 2, "expected_text": "Total"},
        "match": {"text": "Total", "expected_matches": 1},
        "style": {
          "font_family": "Aptos",
          "font_size_pt": 12.5,
          "bold": true,
          "italic": false,
          "underline": true,
          "color": "1A2B3C",
          "highlight": "yellow"
        }
      }
    ]
  }
}
```

`paragraph_delete` contains only `type` and `target`. Paragraph style accepts a portable style id
that must already exist in the package, including custom paragraph styles. Run style accepts any non-empty
subset of the fields shown; size is 1–400 points in half-point increments. A run-style match may
span several complete eligible runs, but a match that starts or ends inside a run returns
`enhancement_required`. Header/footer formatting requires the exact referenced
`word/header*.xml` or `word/footer*.xml` part returned by read; no part name is invented.
Conflicting deletes/inserts/styles or any failed selector abort the whole transaction and preserve
an existing destination.

Images use the same transaction. `image_insert` takes a paragraph target, `before|after`, and a
local PNG/JPEG/GIF payload. `image_replace` instead targets one immutable body drawing by
`relationship_id`, exact `expected_alt_text`, and the SHA-256 of its resolved media part. Obtain
the relationship and alt text from `docx.read`; obtain the target media hash from
`docx.inspect.structure` with `include_hashes: true`. Width is 0.25–10 inches and preserves the
source aspect ratio. Optional crop sides are percentages from 0 through 100; opposing sides must
total less than 100.

```json
{
  "schema_version": "1.0",
  "operation": "docx.edit",
  "input": "<input.docx>",
  "output": "<image-edited.docx>",
  "arguments": {
    "edits": [
      {
        "type": "image_insert",
        "target": {"story": "body", "paragraph_index": 2, "expected_text": "Total"},
        "position": "after",
        "image": {
          "path": "<chart.png>",
          "alt_text": "Quarterly chart",
          "width_inches": 4,
          "crop": {"left": 5, "top": 0, "right": 5, "bottom": 0}
        }
      },
      {
        "type": "image_replace",
        "target": {
          "story": "body",
          "relationship_id": "rIdImage1",
          "expected_alt_text": "Old chart",
          "expected_media_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
        },
        "image": {
          "path": "<replacement.png>",
          "alt_text": "Updated chart",
          "width_inches": 4
        }
      }
    ]
  }
}
```

Both primitives freeze image bytes during planning, allocate deterministic contained media and
relationship identities, and validate the reopened relationship, alt text, dimensions, crop, and
media hash. A stale selector, missing/remote/invalid raster, whole-axis crop, duplicate target, or
unsupported drawing shape rejects the complete transaction without changing source or destination.

Table projections returned by `docx.read` include `selector_sha256`, a hash of the complete
immutable table subtree. Use it with `story: "body"` and the public `table_index`; any intervening
content, formatting, grid, or merge change invalidates the complete transaction.

```json
{
  "schema_version": "1.0",
  "operation": "docx.edit",
  "input": "<input.docx>",
  "output": "<table-edited.docx>",
  "arguments": {
    "edits": [
      {
        "type": "table_insert",
        "target": {"story": "body", "paragraph_index": 2, "expected_text": "Total"},
        "position": "after",
        "table": {"style": "TableGrid", "rows": [["Key", "Value"], ["Total", "42"]]}
      },
      {
        "type": "table_cell_update",
        "target": {
          "story": "body",
          "table_index": 0,
          "expected_table_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
        },
        "cell": {"row_index": 1, "cell_index": 1, "expected_text": "41"},
        "text": "42"
      }
    ]
  }
}
```

`table_row_insert` uses an `anchor` with `row_index` and exact `expected_cells`, plus
`before|after` and a full-width `cells` array. `table_row_delete` uses the same row precondition in
`row` and cannot remove the final row. `table_cells_merge` selects an unmerged rectangular range
with start/end row/column and an exact `expected_texts` matrix, then writes explicit merged text;
horizontal and rectangular vertical merges emit bounded `gridSpan`/`vMerge`. `table_cell_split`
accepts one horizontally merged cell selector plus one output text per spanned grid column.
Nested tables, protected/hyperlinked or multi-paragraph cells, pre-merged merge ranges, and
vertical-cell split return `enhancement_required`; stale hashes/text/widths fail without promotion.

Section projections include a `selector_sha256`; each concrete header/footer reference also
includes its resolved `story_sha256`. `section_update` accepts any non-empty subset of orientation,
explicit page size in twips, partial margins in twips, and a Word section break type.

```json
{
  "schema_version": "1.0",
  "operation": "docx.edit",
  "input": "<input.docx>",
  "output": "<section-edited.docx>",
  "arguments": {
    "edits": [
      {
        "type": "section_update",
        "target": {
          "story": "body",
          "section_index": 1,
          "expected_section_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
        },
        "updates": {
          "orientation": "landscape",
          "page_size": {"width_twips": 15840, "height_twips": 12240},
          "margins": {"top_twips": 720, "bottom_twips": 720},
          "break_type": "nextPage"
        }
      },
      {
        "type": "header_footer_update",
        "target": {
          "story": "body",
          "section_index": 1,
          "expected_section_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
        },
        "kind": "header",
        "variant": "first",
        "expected_story_sha256": null,
        "link_to_previous": false,
        "text": "First page header"
      }
    ]
  }
}
```

Header/footer `kind` is `header|footer`; `variant` is `default|first|even`. Set
`link_to_previous: true` without `text` to remove that section's concrete reference (never on
section zero). Setting it false requires bounded plain text, validates the expected current story
hash or null, allocates a new contained part/relationship, and preserves the prior shared story.
First-page stories enable `titlePg`; even-page stories add or update inert Word settings with
`evenAndOddHeaders`. Reopen validation proves the reference, story bytes, settings, and requested
section properties before publication.

Bookmarks and hyperlinks use immutable top-level body paragraph selectors too. `bookmark_insert`
accepts a bounded ASCII Word bookmark name and currently requires `range: "paragraph"`.
`hyperlink_insert` appends or prepends one simple text run that targets an existing bookmark or a
bookmark planned earlier in the same transaction. `hyperlink_update` matches exactly one simple
internal link by bookmark name and text, then changes its text, target bookmark, or both.

```json
{
  "schema_version": "1.0",
  "operation": "docx.edit",
  "input": "<input.docx>",
  "output": "<linked.docx>",
  "arguments": {
    "edits": [
      {
        "type": "bookmark_insert",
        "target": {"story": "body", "paragraph_index": 2, "expected_text": "Total"},
        "name": "SummaryTotal",
        "range": "paragraph"
      },
      {
        "type": "hyperlink_insert",
        "target": {"story": "body", "paragraph_index": 3, "expected_text": "See total"},
        "bookmark_name": "SummaryTotal",
        "placement": "append",
        "text": "Jump to total"
      },
      {
        "type": "hyperlink_update",
        "target": {"story": "body", "paragraph_index": 4, "expected_text": "Old link"},
        "match": {
          "bookmark_name": "OldTarget",
          "text": "Old link",
          "expected_matches": 1
        },
        "bookmark_name": "SummaryTotal",
        "text": "Updated link"
      }
    ]
  }
}
```

Bookmark names are unique across the body. Missing or duplicate bookmark targets, stale paragraph
text, or a stale hyperlink match aborts the whole transaction. Core does not create or update
external URL relationships, multi-run links, or links inside tables/headers/footers; those requests
return `enhancement_required` or fail validation without changing an existing destination.

### Fields, notes, content controls, and numbering

`field_insert` accepts only `AUTHOR|DATE|NUMPAGES|PAGE|TIME|TITLE`; `toc_insert` emits the fixed
safe heading TOC instruction and marks it dirty. `field_refresh` only marks a selected existing
field dirty—it does not claim to calculate its display value. DDE and external field instructions
are rejected. `note_insert|note_delete` cover plain-text footnotes/endnotes with immutable id/text
preconditions. `content_control_text_update` requires the public selector hash/text and only
updates an unlocked, non-nested, single-text control. `paragraph_numbering_update` selects an
existing `num_id` and level 0–8 from the immutable numbering graph. See the checked
`edit-fields-toc.json`, `edit-notes.json`, `edit-content-control.json`, and
`edit-numbering-style.json` examples.

### Explicit keep-VBA DOCM edit

```json
{
  "schema_version": "1.0",
  "operation": "docx.edit",
  "input": "<input.docm>",
  "output": "<edited.docm>",
  "arguments": {
    "keep_vba": true,
    "edits": [
      {
        "type": "paragraph_style",
        "target": {"story": "body", "paragraph_index": 2, "expected_text": "Total"},
        "style": "Heading2"
      }
    ]
  }
}
```

Both extensions must be `.docm`. `keep_vba` is a literal boolean opt-in, not a general dangerous
content bypass. Only the standard macro-enabled Word main type, contained `vbaProject.bin`, and
its internal relationship are preserved; any external, DDE, OLE, ActiveX, template, XLM, or
executable category rejects the request.

## Run-aware replacement

```json
{
  "schema_version": "1.0",
  "operation": "docx.edit.replace-text",
  "input": "<input.docx>",
  "output": "<replaced.docx>",
  "arguments": {
    "case_sensitive": true,
    "replacements": [
      {"search": "DRAFT", "replace": "FINAL", "expected_matches": 3}
    ]
  }
}
```

`expected_matches` is checked against the immutable original streams before any XML mutation.

## Scalar template and declarative paragraph regions

```json
{
  "schema_version": "1.0",
  "operation": "docx.template.apply",
  "input": "<template.docx-or-dotx>",
  "output": "<rendered.docx>",
  "arguments": {
    "missing_policy": "error",
    "variables": {
      "customer": {"name": "Ada"},
      "region": "APAC"
    }
  }
}
```

Only scalar global values are accepted. Nested global objects are flattened for dot lookup;
arrays, functions, raw XML, marker-based loops/conditions, and expression syntax are rejected.
An optional `regions` array adds only two typed top-level body paragraph operations:

- `paragraph_repeat` clones one immutable text-bound paragraph once per explicit scalar item;
  every item key must exactly match the tokens in that paragraph. An empty item array removes it.
- `paragraph_condition` keeps or removes one immutable text-bound paragraph from a literal boolean
  `include`; no variable lookup or expression is evaluated.

Region targets are distinct, use source paragraph indices, cannot select section boundaries or
protected Word structures, and are capped at 64 regions, 256 items per repeat, and 1,000 emitted
paragraphs. See `assets/examples/template-regions.json`.

The input may be `.docx` or a standard inert `.dotx`; output must be a distinct `.docx`. A `.dotx` base is converted only by
changing the main content type in private staging. Styles, theme, numbering, media, relationships,
sections, and untouched stories retain their original part payloads. Attached templates, macros,
and external relationships remain unsafe and block publication.

An optional `style_overlay` imports only an explicit bounded list of styles from another local
`.docx` or inert `.dotx`. Bind the overlay to its exact SHA-256. `keep-base` imports missing styles
but retains same-id base styles; `replace-existing` replaces only requested same-id styles. Every
unrequested base style remains present. A selected style may depend through `basedOn`, `link`, or
`next` only on another selected style or a style already present in the base. Styles with numbering
bindings or relationship attributes return `enhancement_required` until graph-aware merge exists.

```json
{
  "schema_version": "1.0",
  "operation": "docx.template.apply",
  "input": "<template.dotx>",
  "output": "<rendered.docx>",
  "arguments": {
    "variables": {"customer": {"name": "Ada"}},
    "style_overlay": {
      "source": "<style-library.docx>",
      "expected_source_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "style_ids": ["AccentQuote", "Normal"],
      "conflict_policy": "keep-base"
    }
  }
}
```

## Template-pack catalog, reference import, and instantiation

List built-ins and only the explicitly supplied local references; no ambient directory is scanned:

```json
{"schema_version":"1.0","operation":"docx.template.pack.list","arguments":{"local_packs":[]}}
```

Read exactly one built-in id/version or one local directory bound by its manifest digest:

```json
{
  "schema_version": "1.0",
  "operation": "docx.template.pack.read",
  "arguments": {"pack": {"kind":"builtin","id":"general-academic-paper","version":"1.0.0"}}
}
```

`docx.template.import.inspect` requires a local `.docx/.dotx` plus
`expected_source_sha256`. It writes nothing and returns package safety, paragraph/table styles and
dependencies, direct Chinese/Latin run formatting, paragraph alignment/indent/spacing, table
grid/width/cell-width/borders, story alignment/fields, recognized scalar variables, executable
direct-body region candidates, advisory role candidates, independent per-mode compatibility, and
stable unsupported-feature diagnostics. Scalar variables may be inventoried in nested stories,
but only direct `w:body/w:p` paragraphs are advertised as executable regions. Macro-enabled content, external or
attached-template relationships, embeddings/active parts, malformed/aliased archives, and quota
violations fail closed.

`docx.template.import.create` adds an absent directory `output`, repeats the same inspection and
digest check, and accepts `manifest` metadata plus `provenance`. `manifest.modes` is a subset of
`template|document-spec`; template variables/regions must exactly bind inspected controls, while
document-spec mode requires explicit `role_styles`, `document_spec_versions:["1.0"]`, a declared
domain profile, and `style_profile_versions:["template-mapped/1.0"]`. The payload is copied
byte-for-byte and the manifest binds every member. Missing local license evidence becomes
`unknown` with `redistributable:false`.

When inspection reports document-spec compatibility as `degraded` because material direct run or
paragraph formatting, table geometry/borders, or story fields require an explicit authoring map,
creation fails closed unless `manifest.authoring_format` is supplied. Version `1.0` maps one or
more declared semantic roles to bounded Latin/East Asian fonts, half-point sizes, emphasis, and
paragraph layout; it also declares the structured default footer and the fixed table width and
borders. Every value must match the inspection evidence exactly and all material formatting must
be consumed uniformly. An absent profile returns
`DS_DOCX_TEMPLATE_AUTHORING_FORMAT_REQUIRED`; an invented, conflicting, nonuniform,
unrepresentable, or otherwise lossy profile returns `DS_DOCX_TEMPLATE_AUTHORING_FORMAT_LOSSY`.
On success the canonical manifest stores the profile under `capabilities.authoring_format` and
records document-spec compatibility as `compatible` with
`mapped_by:"explicit-authoring-format/v1"`. See the complete executable request in
`assets/examples/template-import-create.json`; do not infer its values from candidate role names.

Network-origin provenance describes a prior download only. It requires `original_url`,
`retrieved_url`, `retrieved_at`, downloader id/version, `downloaded_sha256` equal to the local
source digest, declared/reviewed license identifier and evidence, and an explicit redistribution
decision. URLs are rejected as document inputs; the producer performs no HTTP request.

Instantiate one mode declared by the pack:

```json
{
  "schema_version": "1.0",
  "operation": "docx.template.pack.instantiate",
  "output": "paper.docx",
  "arguments": {
    "pack": {"kind":"builtin","id":"general-academic-paper","version":"1.0.0"},
    "mode": "document-spec",
    "verification": "core",
    "document_spec": {"version":"1.0","domain_profile":{"id":"academic-paper","version":"1.0","locale":"en-US"},"nodes":[]}
  }
}
```

The illustrative empty `nodes` above must be replaced with a valid non-empty academic spec; the
complete executable English and Simplified Chinese requests are
`assets/examples/template-pack-instantiate-academic-en.json` and
`template-pack-instantiate-academic-zh-cn.json`. A caller `style_profile` is always ambiguous and
rejected before creation. `verification:"enhanced"` records bounded LibreOffice PDF evidence when
the provider is callable and optional page/layout evidence when its raster seam is callable. A
missing/failed provider remains explicitly unavailable/failed, and the absence of a comparable
pack baseline never becomes visual-comparison success; the semantic/schema transaction remains
mandatory.

## Compatible high-fidelity merge

`docx.merge` appends one to sixteen hash-bound local `.docx` sources to a distinct `.docx` base
without extracting and rebuilding their text. Sources resolve relative to the invocation working
directory, must be unique after portable path normalization, and must differ from both base and
output. The base and every source are rehashed around atomic promotion.

```json
{
  "schema_version": "1.0",
  "operation": "docx.merge",
  "input": "<base.docx>",
  "output": "<merged.docx>",
  "arguments": {
    "sources": [
      {
        "path": "<appendix.docx>",
        "expected_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
      }
    ],
    "style_conflict_policy": "require-identical",
    "numbering_conflict_policy": "require-identical"
  }
}
```

The merge copies complete body blocks, tables, sections, referenced header/footer stories, and
their nested image graph while deterministically remapping relationship ids, drawing ids, copied
part names, bookmark ids/names, and internal bookmark anchors. `rename-source` imports source
styles and renames conflicting ids; `remap-source` imports numbering definitions and remaps
abstract/instance ids. `require-identical` remains available for either semantic graph. Theme and
font-table parts must be identical. Safe `AUTHOR|DATE|NUMPAGES|PAGE|TIME|TITLE|TOC` fields are
preserved byte-for-byte inside copied body blocks and counted after reopen. Malformed, DDE/external,
or unknown fields fail closed. Simple unlocked single-text-node content controls are also preserved
when their properties are limited to inert id/tag/alias/text metadata. Data-bound, placeholder,
locked, nested, or relationship-bound controls return `enhancement_required`. Source notes,
when self-contained, are copied as complete XML into the corresponding footnote/endnote part and
their positive ids are deterministically remapped in both definitions and body references. Notes
with their own relationship graph or revision/comment/field/control/style/numbering dependencies
remain unsupported. No partial dependency graph is published. Classic self-contained comments
with one range-start/range-end/reference
triple and its `comments.xml` definition are copied together with deterministic id remapping.
Thread/reply/resolve extension parts and comment relationship graphs still return
`enhancement_required`. Inline tracked insertions/deletions preserve their complete subtree and
remap numeric revision ids across ordinary paragraphs and nested tables. Complete move revisions
require one non-overlapping move-from range and one move-to range paired by the same name and exact
author/canonical-UTC date. Their wrapper ids, range ids, and colliding names are remapped as one
graph. Missing endpoints/wrappers, ambiguous overlap/nesting, custom-XML moves, and property/table
revision forms return `enhancement_required`. Unknown keys, more than sixteen sources, duplicate
or aliased paths, stale hashes, and unknown policies are rejected.

## Tracked revisions (.NET/OpenXML)

Read a bounded projection of revision id, type, author, canonical UTC date, and immutable
paragraph/table scope metadata. Optional filters are exact and conjunctive. A supplied scope must
match the immutable input before the provider runs:

```json
{
  "schema_version": "1.0",
  "operation": "docx.revisions.read",
  "input": "<input.docx>",
  "options": {"fidelity": "enhanced"},
  "arguments": {
    "max_revisions": 1000,
    "filters": {
      "authors": ["Alice"],
      "types": ["insertion", "deletion"],
      "date_from": "2026-01-01T00:00:00Z",
      "date_to": "2026-12-31T23:59:59Z"
    },
    "scope": {
      "story": "body",
      "range": "paragraph",
      "paragraph_index": 3,
      "expected_text": "Tracked paragraph"
    }
  }
}
```

Accept or reject all revisions by leaving `revision_ids` empty, or select up to 1,000 unique
portable ids returned by `docx.revisions.read`. When `filters` or `scope` is present, every named
id must satisfy it; with no ids, only the matching selection is applied. Paragraph scope uses exact
`expected_text`. Table scope uses the public table `selector_sha256` as
`expected_table_sha256`:

```json
{
  "schema_version": "1.0",
  "operation": "docx.revisions.apply",
  "input": "<input.docx>",
  "output": "<reviewed.docx>",
  "options": {"fidelity": "enhanced"},
  "arguments": {
    "action": "accept",
    "revision_ids": [],
    "filters": {"authors": ["Alice"], "types": ["insertion"]},
    "scope": {
      "story": "body",
      "range": "table",
      "table_index": 1,
      "expected_table_sha256": "<64 lowercase hex digits>"
    }
  }
}
```

## Comments (.NET/OpenXML)

```json
{
  "schema_version": "1.0",
  "operation": "docx.comments.read",
  "input": "<input.docx>",
  "options": {"fidelity": "enhanced"},
  "arguments": {"max_comments": 1000}
}
```

Each returned record contains `id`, nullable `parent_comment_id`, root `thread_id`, inherited
thread-level `resolved`, author/date/text, and a bounded body-paragraph anchor when available.
Only one-level root/reply graphs are accepted; dangling, nested, or independently resolved reply
metadata fails closed.

Root comment insertion anchors exactly one body paragraph. The zero-based paragraph index and
immutable `expected_text` precondition must both match:

```json
{
  "schema_version": "1.0",
  "operation": "docx.comments.add",
  "input": "<input.docx>",
  "output": "<commented.docx>",
  "options": {"fidelity": "enhanced"},
  "arguments": {
    "author": "Reviewer",
    "text": "Please verify this paragraph.",
    "anchor": {
      "story": "body",
      "paragraph_index": 3,
      "expected_text": "Quarterly total",
      "range": "paragraph"
    }
  }
}
```

A reply uses the root id returned by `docx.comments.add` or `docx.comments.read`. It must omit
`anchor`; nested replies and replies to resolved threads are rejected:

```json
{
  "schema_version": "1.0",
  "operation": "docx.comments.add",
  "input": "<commented.docx>",
  "output": "<replied.docx>",
  "options": {"fidelity": "enhanced"},
  "arguments": {
    "author": "Reviewer 2",
    "text": "Confirmed.",
    "parent_comment_id": "7"
  }
}
```

Resolve or reopen one root thread with a distinct output:

```json
{
  "schema_version": "1.0",
  "operation": "docx.comments.resolve",
  "input": "<replied.docx>",
  "output": "<resolved.docx>",
  "options": {"fidelity": "enhanced"},
  "arguments": {"comment_id": "7", "resolved": true}
}
```

## OpenXML schema validation (.NET/OpenXML)

```json
{
  "schema_version": "1.0",
  "operation": "docx.validate.schema",
  "input": "<input.docx>",
  "options": {"fidelity": "enhanced"},
  "arguments": {"max_errors": 100}
}
```

Only a real OpenXmlValidator run marks `schema.full` as `pass`.

## DOCX to PDF (LibreOffice)

Conversion is explicit, uses a distinct `.pdf` output, and bounds the complete provider payload:

```json
{
  "schema_version": "1.0",
  "operation": "docx.convert.pdf",
  "input": "<input.docx>",
  "output": "<converted.pdf>",
  "options": {"fidelity": "enhanced"},
  "arguments": {"max_output_bytes": 67108864}
}
```

## Legacy DOC conversion (LibreOffice)

Legacy binary Word input is accepted only through this explicit operation. `format` and the
distinct output extension must agree:

```json
{
  "schema_version": "1.0",
  "operation": "docx.convert.legacy",
  "input": "<input.doc>",
  "output": "<converted.docx>",
  "options": {"fidelity": "enhanced"},
  "arguments": {"format": "docx", "max_output_bytes": 67108864}
}
```

`format: "pdf"` requires a `.pdf` output. The provider result is privately staged, bounded,
reopened as the declared target format, and promoted only after the source `.doc` hash is rechecked.

## PDF/PNG page evidence and layout inspection (LibreOffice)

`docx.render` always promotes a bounded vector PDF. `page_range` is either `"all"` or an inclusive
one-based `{start, end}` object. With `include_page_pngs: false`, `dpi` is `null`. With
`include_page_pngs: true`, the fixed raster profile uses `dpi: 96` and returns bounded base64 PNG
page evidence plus deterministic `professional-v1` layout findings:

```json
{
  "schema_version": "1.0",
  "operation": "docx.render",
  "input": "<input.docx>",
  "output": "<rendered.pdf>",
  "options": {"fidelity": "enhanced"},
  "arguments": {
    "format": "pdf",
    "page_range": {"start": 1, "end": 3},
    "include_page_pngs": true,
    "dpi": 96,
    "layout_profile": "professional-v1",
    "max_pages": 3,
    "max_page_bytes": 500000,
    "max_png_total_bytes": 1000000,
    "max_total_bytes": 67108864
  }
}
```

The result separately reports `render_status`, `page_generation_status`, `layout_status`, and
`visual_comparison_status`. Layout findings have stable code/severity/page/node/evidence/suggestion
fields. Semantic-node-to-page mapping is explicitly degraded when LibreOffice cannot expose it.
The public PNG aggregate defaults to 512 KiB and cannot exceed 1,000,000 raw bytes; this keeps the
base64-bearing result inside the public worker protocol ceiling. Repair and reference comparison
use separate private raster budgets and do not return their full source-page rasters.

`docx.layout.repair` accepts only the closed
`DOCX_LAYOUT_OBJECT_EXCEEDS_TEXT_WIDTH` repair in this slice. It changes the targeted drawing
extent, rerenders, scores findings, and stops within 1–3 rounds on resolution, no improvement,
oscillation, or the round ceiling. See `assets/examples/layout-repair.json`.

## Reference visual comparison (LibreOffice)

`docx.compare.visual` is read-only and accepts a hash-bound `.docx`, `.pdf`, or `.png` reference.
The profile is fixed to `libreoffice-96dpi-v1`; `page_pairs` must be explicit, one-to-one, and cover
the full rendered page sets before the result can pass. It reports geometry, aggregate color, and
placement-proxy metrics plus bounded overlay/diff PNGs. Typography and spacing remain independently
`unavailable` rather than being inferred from the aggregate raster delta. See
`assets/examples/compare-visual.json`.

## Provider absence and rejection examples

Run `capabilities --json` first. If the named optional provider is absent, each otherwise-valid
success request above returns `status: "unavailable"`, `DS_PROVIDER_UNAVAILABLE`, an empty
provider chain, and no promoted output. Closed-contract rejections remain operation-specific:

| Operation | Required provider | Rejected request example | Result |
|---|---|---|---|
| `docx.revisions.read` | `.NET/OpenXML` | `{"max_revisions": 10001}` | `DS_REQUEST_INVALID` |
| `docx.revisions.apply` | `.NET/OpenXML` | `{"action": "delete", "revision_ids": []}` | `DS_REQUEST_INVALID` |
| `docx.revisions.apply` | `.NET/OpenXML` | stale paragraph text/table hash scope | `DS_VALIDATION_FAILED` |
| `docx.comments.read` | `.NET/OpenXML` | `{"max_comments": 0}` | `DS_REQUEST_INVALID` |
| `docx.comments.add` | `.NET/OpenXML` | both `anchor` and `parent_comment_id`, or anchor `story: "header"` | `DS_REQUEST_INVALID` |
| `docx.comments.add` | `.NET/OpenXML` | reply targets another reply or a resolved root | `DS_PROVIDER_FAILED`; no output |
| `docx.comments.resolve` | `.NET/OpenXML` | reply id, non-decimal id, or non-boolean `resolved` | `DS_PROVIDER_FAILED` or `DS_REQUEST_INVALID`; no output |
| `docx.validate.schema` | `.NET/OpenXML` | `{"max_errors": 1001}` | `DS_REQUEST_INVALID` |
| `docx.convert.legacy` | LibreOffice | `.docx` input or format/output mismatch | `DS_REQUEST_INVALID` |
| `docx.convert.pdf` | LibreOffice | output equals input or does not end in `.pdf` | `DS_OUTPUT_EQUALS_INPUT` or `DS_REQUEST_INVALID` |
| `docx.render` | LibreOffice | page PNG `dpi` other than fixed 96 | `DS_REQUEST_INVALID` |
| `docx.layout.repair` | LibreOffice | unknown finding code or `max_rounds: 4` | `DS_REQUEST_INVALID` |
| `docx.compare.visual` | LibreOffice | missing/duplicate page pairing or unbound reference | `DS_REQUEST_INVALID` or `DS_VALIDATION_FAILED` |

No provider-only operation silently falls back to text extraction, document rebuilding, or an
unregistered private provider command.
