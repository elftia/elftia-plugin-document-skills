# DOCX Format Module

## Purpose

The DOCX module owns bounded WordprocessingML read, inspection, authoring, editing, template, merge, comparison, and provider-backed review operations. Direct OOXML remains the preservation, security, and comparison authority.

## Ownership and boundaries

Core Python owns package parsing, semantic projections, typed mutations, stable selectors, merge remapping, source preservation, and validation. A private Core Node adapter owns bounded scalar/region template expansion. LibreOffice and .NET/OpenXML add only their registered operations when accepted as callable.

The module does not accept raw caller XML, execute fields/macros, infer safe mutation from inert inspection, or treat HTML/Markdown conversion as native preservation. Agent workflow detail remains in the [DOCX Skill](../../../../skills/document-docx/SKILL.md).

## Entry points

Use the shared Skill façade and check capabilities before optional operations. Contract parsing starts in [`contracts.py`](contracts.py), service routing in [`service.py`](service.py), and the public provider registry in [`../../providers/`](../../providers/README.md).

## Operations and availability

| Operation | Availability | Contract summary |
| --- | --- | --- |
| `docx.read` | Core Python | Bounded semantic projection of body, tables, links, images, stories, sections, and stable semantic ids |
| `docx.inspect.accessibility` | Core Python | Inert authoring checks; not WCAG certification or visual equivalence |
| `docx.inspect.structure` | Core Python | Inert package, relationship, feature, and dangerous-content inventory |
| `docx.compare.semantic` | Core Python | Stable-id or hash-bound semantic/preservation comparison |
| `docx.create` | Core Python | Typed report or versioned document-spec authoring with styles/domain profiles |
| `docx.edit` | Core Python | Typed paragraph, run, image, table, section/story, field, note, control, style, and numbering edits |
| `docx.edit.replace-text` | Core Python | Exact run-aware replacement across supported document stories |
| `docx.merge` | Core Python | Deterministic high-fidelity OOXML graph merge with bounded advanced-object support |
| `docx.template.apply` | Core Node behind Python | Bounded scalar and declarative paragraph-region substitution over `.docx` or inert `.dotx` |
| `docx.template.pack.list` | Core Python | Deterministic built-ins plus only explicit hash-bound local packs |
| `docx.template.pack.read` | Core Python | Exact built-in/local manifest, compatibility, provenance, capability, and evidence summary |
| `docx.template.import.inspect` | Core Python | Read-only safe DOCX/inert DOTX style/control inventory and advisory role candidates |
| `docx.template.import.create` | Core Python | Canonical byte-preserving local pack import with atomic no-replace directory publication |
| `docx.template.pack.instantiate` | Core Node behind Python | Declared template or document-spec adapter with pack-owned mappings and transactional DOCX output |
| `docx.convert.legacy` | LibreOffice | Explicit bounded `.doc` to `.docx` conversion |
| `docx.convert.pdf` | LibreOffice | Explicit DOCX to PDF conversion |
| `docx.render` | LibreOffice | PDF and optional page-image evidence plus bounded layout findings |
| `docx.layout.repair` | LibreOffice | Bounded semantic-node repair loop with explicit stop conditions |
| `docx.compare.visual` | LibreOffice | Fixed-profile reference visual comparison; separate from normal render |
| `docx.revisions.read` | .NET/OpenXML | Filtered typed revision projection |
| `docx.revisions.apply` | .NET/OpenXML | Bounded accept/reject over immutable ids and scope |
| `docx.comments.read` | .NET/OpenXML | Typed root/reply thread projection |
| `docx.comments.add` | .NET/OpenXML | Bounded root or one-level reply insertion |
| `docx.comments.resolve` | .NET/OpenXML | Root-thread resolution state update |
| `docx.validate.schema` | .NET/OpenXML | Full OpenXML SDK validation; Core reopen is not a substitute |

## Safety and failure semantics

Mutations require distinct outputs and immutable selectors from public read/inspection results. Unknown fields, unsafe external relationships, unsupported complex Word graphs, unbound styles/numbering, ambiguous comment/revision graphs, and required validation failures publish nothing.

`.docm` editing requires explicit inert `keep_vba: true` copy-through and preserves VBA bytes without parsing or execution. Legacy `.doc` is accepted only by the provider-backed conversion operation. Missing optional providers return `unavailable` without output.

## Verification

The [plugin test suite](../../../../tests/README.md) owns the public DOCX contract, operation, and security coverage. Exact focused and aggregate commands belong to the [producer verification guide](../../../../../scripts/README.md).

## Related documentation

- [DOCX Skill and references](../../../../skills/document-docx/SKILL.md)
- [Shared Core](../../README.md)
- [Providers](../../providers/README.md)
- [Schemas](../../../../schemas/README.md)
- [Tests](../../../../tests/README.md)
