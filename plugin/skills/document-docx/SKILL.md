---
name: document-docx
description: Read, structurally inspect, create, template, safely replace text in, and validate .docx files through the bundled frozen uv/Python surface.
---

# DOCX documents

Use this Skill only for `.docx` work. It provides five Core operations:

- `docx.read` — deterministic headings, paragraphs, lists, tables, hyperlinks, images,
  headers/footers, and section metadata.
- `docx.inspect.structure` — inert package, relationship, feature, and dangerous-content
  inventory; it never authorizes mutation.
- `docx.create` — a styled document containing exactly the blocks the request lists:
  headings, paragraphs, tables, and inline local images, plus opt-in header, footer,
  sections, and metadata.
- `docx.edit.replace-text` — exact run-aware replacement across body, tables, referenced
  headers, and referenced footers.
- `docx.template.apply` — bounded scalar `{identifier}` substitution, including placeholders
  split across formatting runs.

`docx.create` never adds content of its own. A request listing only paragraphs produces a
document containing only those paragraphs — no placeholder image, no filler table, no empty
running head. Ask for a table, an image, a header, a footer, or extra sections only when the
document genuinely needs one; never invent one to satisfy the operation.

Before relying on an operation, check its callable capability. All executable examples use the
same bundled Python façade:

```text
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" doctor --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" capabilities --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" run --request request.json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" validate --input artifact.docx --json
```

Never replace `<project-root>` with another Python environment. Node is an internal template
backend selected by Python; do not invoke it or any provider directly.

## Safe workflow

1. Preserve the input. Every mutation requires an explicit, distinct output path; aliases and
   in-place requests are rejected.
2. Use `docx.inspect.structure` when normal read rejects active/external content. Inspection is
   inert: it does not fetch, execute, enable, rewrite, sanitize, or make the package safe.
3. For replacement, matches may span formatting runs within one eligible paragraph. Inserted
   text inherits the first affected run. Matches never cross hyperlinks, paragraphs, cells,
   fields, revisions, comments, content controls, drawings, tabs, or breaks.
4. For templates, use only scalar ASCII/dot identifiers. Missing variables block output; unused
   variables are warnings. Loops, conditions, raw XML, expressions, and caller-supplied parser
   code are rejected.
5. Treat required validation failure as no publication. Optional visual and full OpenXML schema
   gates remain `unavailable` unless an accepted callable enhancement actually runs.

## Interpret results exactly

- `success`: all required Core gates passed and any output was atomically promoted.
- `degraded`: a caller-authorized semantic fallback ran; read its `degradations`.
- `enhancement_required`: Core intentionally refused semantics such as tracked-change or comment
  mutation; the result may recommend `.NET/OpenXML`, but does not claim it ran.
- `invalid_request`: fix paths, operation-specific arguments, schema version, or template syntax.
- `failed`: no successful result; inspect the stable `DS_*` error and required gate evidence.

LibreOffice and `.NET/OpenXML` are optional enhancements, not Core prerequisites. Detection alone
does not advertise a capability or turn an unavailable gate into a pass.

## References

- [Typed request examples](references/requests.md)
- [Structured result and status guide](references/results.md)
- [Preservation, security, and validation policy](references/safety-and-validation.md)

Checked example request files live under `assets/examples/`.
