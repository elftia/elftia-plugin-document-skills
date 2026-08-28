# Anthropic Document-Skill Capability Parity Scan

## Clean-room invariant (North Star invariants 11 + 12)

This document is an Elftia-authored parity scan.  Anthropic document-skill
capabilities are cited by **capability name only**.  NO Anthropic restricted
prompt, script, schema, template, fixture, reference, or derived expression
is copied.  Selected GAP implementations are independently authored from
public Office Open XML / PDF ISO 32000 file-format specifications and
Elftia's own code. No adopted source is present in this release; a future
adoption would require both `THIRD_PARTY_NOTICES.md` and module-level provenance.

The implementation sources are:

* Public OPC / OOXML (ECMA-376) and PDF (ISO 32000-2) format specifications.
* Original Elftia-authored clean-room code.

## Status legend

| Status        | Meaning                                                       |
| ------------- | ------------------------------------------------------------- |
| `PRESENT`     | Delivered by Core or enhancement; implementing module cited.  |
| `GAP`         | Not yet delivered; deferral reason cites the slice/feature.   |
| `OUT-OF-SCOPE`| North Star non-goal; cited against the unified design §3.2.   |

---

## DOCX capability matrix

| Capability area                      | Status        | Implementation / Deferral reason                                         |
| ------------------------------------ | ------------- | ------------------------------------------------------------------------ |
| Read body / paragraphs / runs        | `PRESENT`     | `formats/docx/read.py`, `formats/docx/mapping.py`                        |
| Read tables (with spans/nesting)     | `PRESENT`     | `formats/docx/projection.py::project_tables`                             |
| Read headers / footers               | `PRESENT`     | `formats/docx/mapping.py::document_stories`                              |
| Read sections                        | `PRESENT`     | `formats/docx/projection.py::project_sections`                           |
| Read images                          | `PRESENT`     | `formats/docx/projection.py::project_images`                             |
| Read metadata (uniform block)        | `PRESENT`     | GAP-CROSS-1 closure: `core/io/core_properties.py`, `formats/docx/read.py`|
| Create (heading/paragraph/table/image) | `PRESENT`   | `formats/docx/create.py`                                                 |
| Source-neutral semantic document spec | `PRESENT`   | Stable ids plus native projection in `document_spec.py`, `read.py`       |
| Reusable style/domain profiles         | `PRESENT`   | `style_profiles.py`, `domain_profiles.py`; academic is an application    |
| Captions/references/equations/citations | `PRESENT`  | Closed semantic subsets in `references.py`, `equations.py`               |
| Typed structural and formatting edit | `PRESENT`     | `formats/docx/editing.py` and bounded primitive-specific modules         |
| Accessibility inspection             | `PRESENT`     | `formats/docx/accessibility.py`, bounded inert semantic issue report     |
| Image insertion/replacement in edit  | `PRESENT`     | `formats/docx/image_editing.py`, immutable selectors + reopen validation |
| Section and header/footer story edit | `PRESENT`     | `formats/docx/section_editing.py`, isolated story allocation             |
| Bookmarks and internal hyperlinks    | `PRESENT`     | `formats/docx/link_editing.py`, immutable paragraph/link selectors       |
| Safe fields and TOC dirty markers    | `PRESENT`     | `formats/docx/field_editing.py`, closed non-DDE instruction vocabulary   |
| Footnotes/endnotes edit              | `PRESENT`     | `formats/docx/note_editing.py`, deterministic note ids + relationships   |
| Simple content-control edit          | `PRESENT`     | `formats/docx/content_control_editing.py`, unlocked inert text controls  |
| Styles/numbering/theme inspection    | `PRESENT`     | `formats/docx/formatting_inspection.py`, `numbering_editing.py`          |
| Direct-formatting normalization report | `PRESENT`  | bounded contamination inventory; no automatic semantic normalization     |
| Declarative template regions/style overlay | `PRESENT` | `template_regions.py`, `style_overlay.py`; no expressions or raw XML    |
| Bounded high-fidelity graph merge    | `PRESENT`     | `formats/docx/merge_operation.py` and graph-specific remappers           |
| .dotx/.docm/legacy .doc handling     | `PRESENT`     | inert template/VBA boundaries + explicit LibreOffice legacy conversion  |
| Edit replace-text (run-aware)        | `PRESENT`     | `formats/docx/replace.py`, `formats/docx/transaction.py`                 |
| Edit template apply (core-node)      | `PRESENT`     | `formats/docx/template.py` (core-node provider)                          |
| Inspect structure (parts/rels/features) | `PRESENT`  | `formats/docx/inspect.py`                                                |
| Inspect security (dangerous_content) | `PRESENT`     | `core/io/ooxml_security.py`, `formats/docx/inspect.py`                   |
| Inspect security_summary (uniform)   | `PRESENT`     | GAP-CROSS-2 closure: `formats/docx/inspect.py::_project_security_summary`|
| Validate (package/content-type/reopen)| `PRESENT`    | `formats/docx/validation.py`, `core/validation/runner.py`                |
| Schema validate (.NET OpenXML)       | `PRESENT`     | `providers/dotnet/` enhancement (schema validator)                       |
| Revisions inventory                  | `PRESENT`     | `providers/dotnet/` enhancement (revisions read)                         |
| Revisions accept/reject              | `PRESENT`     | `providers/dotnet/` enhancement (revisions mutate)                       |
| Comments inventory                   | `PRESENT`     | `providers/dotnet/` enhancement (comments read)                          |
| Comments add                         | `PRESENT`     | `providers/dotnet/` enhancement (comments add)                           |
| Comments threads/replies/resolution  | `PRESENT`     | `providers/dotnet/` bounded one-level thread graph + root resolution      |
| LibreOffice render/page generation   | `PRESENT`     | `formats/docx/rendering.py`, `providers/libreoffice/`                     |
| Deterministic layout inspection/repair | `PRESENT`   | `layout_inspection.py`, `layout_repair.py`; bounded width repair          |
| Stable-ID semantic comparison        | `PRESENT`     | `semantic_compare.py`; spec/output and hash-bound before/after            |
| Full redline integrity scorecard     | `GAP`         | `CR-DOCX-001`: inventory + accept/reject shipped; full scorecard is a separate feature. |
| Threaded-comment extension merge     | `GAP`         | Public thread collaboration ships; merge rejects extension graphs closed. |
| Complex revision graph merge         | `GAP`         | Inline insert/delete and paired moves ship; nested/property/table graphs remain closed. |
| RTF/ODT public contracts             | `GAP`         | No bounded independent contract or validation evidence has been accepted. |
| Reference visual comparison QA       | `PRESENT`     | `visual_compare.py`; fixed 96-DPI pairing and bounded raster evidence     |

## XLSX capability matrix

| Capability area                      | Status        | Implementation / Deferral reason                                         |
| ------------------------------------ | ------------- | ------------------------------------------------------------------------ |
| Read cells / formulas / cached values| `PRESENT`     | `formats/xlsx/read.py`, `formats/xlsx/mapping.py`                        |
| Read defined names                   | `PRESENT`     | `formats/xlsx/mapping.py::map_workbook`                                  |
| Read styles / number formats         | `PRESENT`     | `formats/xlsx/styles.py`, `formats/xlsx/projection.py`                   |
| Read metadata (uniform block)        | `PRESENT`     | GAP-CROSS-1 closure: `formats/xlsx/read.py`                              |
| Read external_links (inert)          | `PRESENT`     | GAP-CROSS-3 closure: `formats/xlsx/projection.py::project_external_links`|
| Create                               | `PRESENT`     | `formats/xlsx/create.py`                                                 |
| Edit cells / rows                    | `PRESENT`     | `formats/xlsx/edit.py`                                                   |
| Inspect structure                    | `PRESENT`     | `formats/xlsx/inspect.py`                                                |
| Inspect security_summary (uniform)   | `PRESENT`     | GAP-CROSS-2 closure: `formats/xlsx/inspect.py`                           |
| Formula static check                 | `PRESENT`     | `formats/xlsx/formula_state.py`                                          |
| Formula recalc (LibreOffice)         | `PRESENT`     | `providers/libreoffice/` enhancement (recalc)                            |
| Data validation                      | `PRESENT`     | `formats/xlsx/projection.py` (inventory)                                 |
| Conditional format                   | `PRESENT`     | `formats/xlsx/projection.py` (inventory)                                 |
| `.xlsm` keep_vba                     | `PRESENT`     | `core/io/ooxml_security.py` (PRESERVE_DISABLED)                          |
| Tables                               | `PRESENT`     | `formats/xlsx/projection.py::project_tables`                             |
| Pivot caches                         | `PRESENT`     | `formats/xlsx/projection.py::project_pivot_caches`                       |
| Schema validate                      | `GAP`         | `CR-OFFICE-001`: only DOCX schema shipped via .NET; XLSX needs provider extension. |
| Native chart creation                | `GAP`         | Chart inventory exists; native chart creation is a separate feature.     |
| Pivot creation                       | `GAP`         | Pivot cache inventory exists; pivot creation is a separate feature.      |

## PPTX capability matrix

| Capability area                      | Status        | Implementation / Deferral reason                                         |
| ------------------------------------ | ------------- | ------------------------------------------------------------------------ |
| Read text / shapes / runs            | `PRESENT`     | `formats/pptx/read.py`, `formats/pptx/mapping.py`                        |
| Read tables                          | `PRESENT`     | `formats/pptx/mapping.py`                                                |
| Read notes                           | `PRESENT`     | `formats/pptx/mapping.py::map_slides`                                    |
| Read metadata (uniform block)        | `PRESENT`     | GAP-CROSS-1 closure: `formats/pptx/read.py`                              |
| Read external_links (inert)          | `PRESENT`     | GAP-CROSS-3 closure: `formats/pptx/projection.py::project_external_links`|
| Create                               | `PRESENT`     | `formats/pptx/create.py`                                                 |
| Edit text                            | `PRESENT`     | `formats/pptx/edit.py`                                                   |
| Inspect structure                    | `PRESENT`     | `formats/pptx/inspect.py`                                                |
| Inspect security_summary (uniform)   | `PRESENT`     | GAP-CROSS-2 closure: `formats/pptx/inspect.py`                           |
| Template analysis                    | `PRESENT`     | `formats/pptx/projection.py`                                             |
| Charts                               | `PRESENT`     | `formats/pptx/projection.py::project_charts`                             |
| Media                                | `PRESENT`     | `formats/pptx/projection.py::project_media`                              |
| Chart/axis/package corruption validator | `GAP`      | `CR-PPTX-001`: deep schema work; out of scope for final hardening slice. |
| Content/file/visual three-layer QA   | `GAP`         | `CR-PPTX-002`: large pipeline; out of scope.                             |
| Slide copy/delete/rearrange          | `GAP`         | Large feature work; out of scope for final hardening slice.              |
| Design (master/layout/theme)         | `OUT-OF-SCOPE`| Design authoring is a North Star non-goal (UI-level feature, not document-skill). |

## PDF capability matrix

| Capability area                      | Status        | Implementation / Deferral reason                                         |
| ------------------------------------ | ------------- | ------------------------------------------------------------------------ |
| Read text                            | `PRESENT`     | `formats/pdf/read.py`, `formats/pdf/mapping.py::map_text_blocks`         |
| Read page boxes / rotation           | `PRESENT`     | `formats/pdf/page_tree.py`, `formats/pdf/projection.py`                  |
| Read metadata (uniform block)        | `PRESENT`     | GAP-CROSS-1 closure: `formats/pdf/read.py::_project_uniform_metadata`    |
| Read fonts / images                  | `PRESENT`     | `formats/pdf/resources.py`, `formats/pdf/projection.py`                  |
| Read AcroForm fields                 | `PRESENT`     | `formats/pdf/mapping.py::map_acroform_fields`                            |
| Read annotations                     | `PRESENT`     | `formats/pdf/mapping.py::map_annotations`                                |
| Read outlines                        | `PRESENT`     | `formats/pdf/mapping.py::map_outlines`                                   |
| Read embedded files                  | `PRESENT`     | `formats/pdf/mapping.py::map_embedded_files`                             |
| Create                               | `PRESENT`     | `formats/pdf/create.py`                                                  |
| Edit (rotate/watermark/text)         | `PRESENT`     | `formats/pdf/edit.py`                                                    |
| Inspect structure                    | `PRESENT`     | `formats/pdf/inspect.py`                                                 |
| Inspect security_summary (uniform)   | `PRESENT`     | GAP-CROSS-2 closure: `formats/pdf/inspect.py::_project_security_summary` |
| Merge / split                        | `PRESENT`     | `formats/pdf/edit.py`, `formats/pdf/page_merge_split.py`                 |
| Watermark                            | `PRESENT`     | `formats/pdf/edit.py`                                                    |
| Rewrite extract/apply                | `PRESENT`     | `formats/pdf/rewrite.py`                                                 |
| Forms inspect                        | `PRESENT`     | `formats/pdf/mapping.py::map_acroform_fields` (inventory)                |
| Forms fill / flatten                 | `PRESENT`     | `formats/pdf/forms.py`, `formats/pdf/form_appearance.py`, `formats/pdf/form_flatten.py` |
| OCR                                  | `PRESENT`     | Provider-gated `providers/pdf_tools/ocr.py` + source-bound semantic gate |
| Image extraction                     | `PRESENT`     | `formats/pdf/images_extract.py`, bounded XObject/Form/inline extraction  |
| Encryption / decryption              | `PRESENT`     | Provider-gated `providers/pypdf/` AES-256-R5 implementation              |
| Compression                          | `PRESENT`     | Provider-gated `providers/pypdf/` measured compression/semantic evidence |
| Visual QA                            | `PRESENT`     | Provider-gated `providers/pdf_tools/` render geometry and visual diff    |

## Cross-cutting capability matrix

| Capability area                      | Status        | Implementation / Deferral reason                                         |
| ------------------------------------ | ------------- | ------------------------------------------------------------------------ |
| Security inventory across formats    | `PRESENT`     | `core/io/ooxml_security.py`, `formats/pdf/actions.py`, consolidated gate `tests/test_cross_format_security.py` |
| Fail-closed mutation policy          | `PRESENT`     | All four formats reject dangerous packages by default                    |
| Preserve-disabled inspection         | `PRESENT`     | `allow_dangerous_inventory=True` (OOXML) / `inspect_pdf` (PDF)           |
| Crash isolation (provider mutations) | `PRESENT`     | `tests/test_provider_crash_isolation.py` unified gate                    |
| Source preservation (default edit)   | `PRESENT`     | `tests/test_preservation_cross_check.py` cross-format gate               |
| Provenance (module-level)            | `PRESENT`     | `provenance/modules.json`, `tools/regenerate_provenance.py`              |
| SBOM (CycloneDX)                     | `PRESENT`     | `sbom.cdx.json`, `tools/supply_chain.py`                                 |
| Clean-room audit                     | `PRESENT`     | `tools/audit.py`, `provenance/clean-room-policy.md`                     |
| Metadata read uniformity             | `PRESENT`     | GAP-CROSS-1 closure across all four formats                              |
| External-link inventory              | `PRESENT`     | GAP-CROSS-3 closure (XLSX + PPTX)                                        |
| Security_summary uniformity          | `PRESENT`     | GAP-CROSS-2 closure across all four formats                              |
| Cross-format visual diff             | `GAP`         | Large feature work; out of scope for final hardening slice.              |
| Full dogfood coverage                | `OUT-OF-SCOPE`| North Star non-goal in this environment: requires live Electron clean-profile boot + multi-backend session; recorded as `unavailable` honestly. |
| Remote macOS/Linux CI                | `GAP`         | Workflow definitions exist, but observed current-revision receipts remain an external delivery gate. |
| MCP server / daemon / global command | `OUT-OF-SCOPE`| North Star non-goal: four narrow Skills are the sole agent surface.     |
| Macro execution / DDE / external refresh | `OUT-OF-SCOPE`| North Star non-goal: dangerous content is inventoried but never executed. |

## Deferred GAPs (consolidated)

| ID            | Gap                                         | Deferral reason                                        |
| ------------- | ------------------------------------------- | ------------------------------------------------------ |
| `CR-DOCX-001` | Full redline integrity scorecard            | Separate feature; inventory + accept/reject shipped.   |
| `CR-OFFICE-001` | Schema validator for XLSX/PPTX            | Needs .NET provider extension; out of scope.           |
| `CR-PPTX-001` | Chart/axis/package corruption validator     | Deep schema work; out of scope.                        |
| `CR-PPTX-002` | Content/file/visual three-layer QA pipeline | Large pipeline; out of scope.                          |

## Honest evidence boundaries

* **Full dogfood coverage** (live Electron clean-profile boot + multi-backend session): `unavailable` in this environment (no live Electron boot).  NOT claimed.
* **Remote macOS/Linux CI**: absent.  Local CI proves the Core-only path; mock injection proves the provider paths.  Observed remote CI on all three platforms remains a portfolio delivery gate when unavailable locally.  NOT claimed.
