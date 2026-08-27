# Public Document Skill Catalog

## Purpose

This directory contains the four Agent-visible routing documents. Each `SKILL.md` explains when to use one format, how to call the shared frozen Python façade, which operations are Core or provider-gated, and which reference must be read for a specialized workflow.

## Ownership and boundaries

Skill files are human/agent guidance, not an executable operation registry or a second JSON Schema. Registered capabilities come from provider registration; request/report envelopes come from [`../schemas/`](../schemas/README.md); implementation belongs to [`../src/document_skills_core/`](../src/document_skills_core/README.md).

Reference documents may define bounded operation arguments and examples. They do not authorize direct provider calls, dependency installation, in-place writes, raw OOXML/XML injection, or weaker fallback than the registered contract.

## Entry points

| Skill | Use for | Agent guide | Implementation guide |
| --- | --- | --- | --- |
| `document-docx` | Word read, inspect, author, edit, template, merge, compare, render/convert/validate | [SKILL.md](document-docx/SKILL.md) | [DOCX module](../src/document_skills_core/formats/docx/README.md) |
| `document-xlsx` | Workbook/tabular read, inspect, author, edit, summarize, pivot, convert, recalculate, render/validate | [SKILL.md](document-xlsx/SKILL.md) | [XLSX module](../src/document_skills_core/formats/xlsx/README.md) |
| `document-pptx` | Presentation planning, read, inspect, typed creation/editing, templates, SVG/HTML/reconstruction, render/convert/validate | [SKILL.md](document-pptx/SKILL.md) | [PPTX module](../src/document_skills_core/formats/pptx/README.md) |
| `document-pdf` | PDF read, inspect, create, edit, rewrite, structural validation | [SKILL.md](document-pdf/SKILL.md) | [PDF module](../src/document_skills_core/formats/pdf/README.md) |

Every Skill uses the same command family:

```text
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" doctor --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" capabilities --json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" run --request request.json
uv run --project "<project-root>" --frozen python "<skill-dir>/scripts/run.py" validate --input artifact.ext --json
```

## Safety and failure semantics

Check `capabilities --json` before promising an optional operation. Preserve sources, use distinct outputs, and interpret `unavailable`, `enhancement_required`, `degraded`, and `failed` literally. A provider that is installed but not accepted as callable still counts as unavailable. Structural inspection is inert and never authorizes mutation of active or external content.

## Verification

The documentation gate checks that all registered operations appear in the owning format README and that these links resolve. The public façade is exercised by the format public tests under [`../tests/`](../tests/README.md) and by the aggregate checks documented in the [producer verification guide](../../scripts/README.md).

## Related documentation

- [Runtime overview](../README.md)
- [Shared Core](../src/document_skills_core/README.md)
- [Provider model](../src/document_skills_core/providers/README.md)
- [Schemas](../schemas/README.md)
- [Tests](../tests/README.md)
