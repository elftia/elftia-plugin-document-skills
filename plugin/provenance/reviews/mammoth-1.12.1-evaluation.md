# Mammoth 1.12.1 adapter evaluation

- Evaluation date: 2026-08-25
- Candidate: `mammoth@1.12.1`
- Candidate license: BSD-2-Clause
- Decision: **evaluated, not adopted**
- Runtime/package changes: none

## Question

Does Mammoth provide enough independent value as a lossy DOCX-to-HTML/Markdown
adapter to justify adding it to the production Node dependency graph, while the
native OOXML projection remains the source of truth for security, preservation,
stable IDs, styles, sections, references, and comparison gates?

## Reproducible evaluation slice

The published package was executed ephemerally with `npx` against the
self-authored `tests/fixtures/docx-rich.docx` fixture. It was not added to
`package.json`, `package-lock.json`, the runtime image, provenance allowlists, or
the SBOM.

Observed Mammoth HTML projection:

| Signal | Result |
|---|---:|
| UTF-8 HTML bytes | 582 |
| headings | 1 |
| tables | 1 |
| embedded images | 1 |
| links | 1 |
| footnote markers | 0 |

The native `docx.read` projection of the same fixture reported:

| Signal | Result |
|---|---:|
| stories | 3 |
| paragraphs | 14 |
| tables | 1 |
| images | 1 |
| links | 1 |
| sections | 2 |
| styles | 4 |
| numbering instances | 1 |
| truncated | false |

Mammoth's useful independent output is compact, human/LLM-readable semantic
HTML. It does not retain the document evidence required by this project:

- no stable Elftia semantic node IDs or precondition identity;
- no page, section, header/footer, style, numbering, or layout fidelity;
- no preservation manifest or package-security authority;
- no semantic/layout/visual comparison pass/fail authority;
- HTML is a lossy projection and would require a separate sanitization boundary
  before browser display.

## Supply-chain assessment

Registry metadata reported an unpacked candidate size of 2,169,523 bytes and
the following direct dependencies:

| Dependency | Observed license |
|---|---|
| `lop@0.4.2` | BSD-2-Clause |
| `jszip@3.10.1` | MIT OR GPL-3.0-or-later |
| `argparse@1.0.10` | MIT |
| `bluebird@3.7.2` | MIT |
| `base64-js@1.5.1` | MIT |
| `underscore@1.13.7` | MIT |
| `xmlbuilder@10.1.1` | MIT |
| `@xmldom/xmldom@0.8.11` | MIT |
| `path-is-absolute@1.0.1` | MIT |
| `dingbat-to-unicode@1.0.1` | BSD-2-Clause |

The license set is not the rejection reason. The rejection is proportionality:
ten direct packages, ZIP/XML parsing overlap, another untrusted-document parser,
and an HTML sanitization requirement are not justified by the current thin
presentation-only benefit.

## Decision and boundary

Mammoth is not adopted. Native OOXML remains the only preservation, security,
semantic comparison, and structural validation authority. No public Markdown or
HTML operation is registered, and no unavailable placeholder operation is
reserved.

Reconsider only when a concrete downstream workflow requires semantic HTML and
a native thin adapter has proven insufficient. A future proposal must include:

1. a version lock and complete transitive license/provenance/SBOM review;
2. production `--omit=dev` installation evidence on Windows, macOS, and Linux;
3. isolated execution, byte/time limits, image limits, and HTML sanitization;
4. differential fixtures for headings, lists, tables, images, links, and notes;
5. explicit `lossy_projection` status, with no style/layout/comparison authority.
