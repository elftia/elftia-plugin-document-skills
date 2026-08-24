# PPTX outline and Markdown content entry

These two Core operations are content-entry routes, not visual importers.
`pptx.outline.create` produces planning JSON only.
`pptx.create.from-markdown` semantically reconstructs a native presentation
through the normal typed emitter, deep package validation, optional schema
gate, and atomic promotion path.

## Outline planning

```json
{
  "operation": "pptx.outline.create",
  "output": "plan.json",
  "arguments": {
    "title": "Quarterly review",
    "audience": "Leadership",
    "objective": "Choose the next investment",
    "slides": [
      {
        "title": "Decision",
        "purpose": "Frame the choice",
        "bullets": ["Option A", "Option B"],
        "notes": "Ask for a decision.",
        "metadata": {"recipe": "comparison", "tags": ["decision"]}
      }
    ]
  }
}
```

The output declares `kind: "pptx-outline"`,
`artifact_type: "planning-json"`, and `presentation_generated: false`. It is
not a placeholder PPTX and must not be presented as one.

## Markdown reconstruction

```json
{
  "operation": "pptx.create.from-markdown",
  "input": "deck.md",
  "output": "deck.pptx",
  "arguments": {
    "metadata": {"creator": "Me", "subject": "Q3"}
  }
}
```

The supported mapping is:

- H1, H2, and H3 start slides and default to `cover`, `content`, and `section`
  recipes respectively;
- paragraphs and ordered/unordered list items become native text paragraphs;
- fenced code becomes native monospaced text;
- one pipe table per slide becomes a native table;
- one standalone Markdown image per slide becomes a native image;
- `:::notes` ... `:::` becomes speaker notes;
- `<!-- pptx: {"recipe":"...","notes":"...","tags":[...]} -->` supplies
  bounded per-slide metadata.

The source must be non-empty strict UTF-8 `.md` or `.markdown`. Images must be
PNG, JPEG, or static GIF paths relative to the Markdown file's directory. The
resolved file must remain inside that directory. Remote, data, file, absolute,
UNC, missing, and escaping paths are rejected. Inline images, extra tables or
images on one slide, unsupported heading depths, malformed metadata, unclosed
code/notes blocks, and conflicting notes fail without output.

Optional `theme` and `layout_tokens` use the typed design contracts. A local
`.pptx` or `.potx` template may be supplied instead; template reuse and new `theme` tokens
are mutually exclusive. The result records source hash/bytes, slide source-line
ranges, recipes, tags, native-object counts, and the explicit facts
`semantic_reconstruction: true` and `visual_preservation_claimed: false` under
`diagnostics.operation_result.reconstruction`.
