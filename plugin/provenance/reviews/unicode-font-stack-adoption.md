# Unicode PDF font stack adoption review

- Review date: 2026-08-24
- Candidate graph: `fonttools==4.63.0`, `uharfbuzz==0.56.0`, and
  `python-bidi==0.6.11`
- Exact source releases and sdist SHA-256:
  - `fonttools-4.63.0.tar.gz` — `caeb583deeb5168e694b65cda8b4ee62abedfa66cf88488734466f2366b9c4e0`
  - `uharfbuzz-0.56.0.tar.gz` — `77f4ad1c9f32f44cc6f0c0c4f98fab54587719c96c810a043d01669f704d3e0c`
  - `python-bidi-0.6.11.tar.gz` — `034090c597af250d699299d7e7f1e83eb016f9e47b3b707bd89ab2bdec77bce0`
- License evidence from installed wheel metadata: FontTools MIT, uharfbuzz
  Apache-2.0, python-bidi LGPL-3.0-only. The python-bidi wheel's
  `LICENSE-THIRD-PARTY.yml` identifies its bundled Rust crates and their
  MIT/Apache-2.0/Unicode-DFS-2016 licenses.
- Cross-platform evidence: PyPI publishes CPython wheels for Windows, macOS,
  manylinux, and musllinux for both native packages; FontTools also publishes a
  universal wheel. All three require Python versions compatible with this
  project's `>=3.11` policy.
- Production dependency surface: the three direct packages add no Python
  runtime dependency edges. Optional FontTools extras are not selected.
- Accepted responsibility split: Elftia owns the closed font request contract,
  byte/hash/embedding-right checks, deterministic subset policy, Type0/CIDFont
  emission, ToUnicode maps, layout bounds, validation, and atomic promotion.
  FontTools is used only for bounded sfnt parsing/subsetting, uharfbuzz only for
  in-memory glyph shaping, and python-bidi only for resolved directional levels.
- Rejected alternatives: system-font discovery is non-portable and unauditable;
  ReportLab would duplicate the existing PDF object/layout engine; handwritten
  Arabic reversal is not shaping; PyMuPDF remains development-only because its
  distribution license is not accepted for this production path.
- Security boundary: font files never enter argv and are never executed. The
  public request binds a resolved local path to SHA-256; runtime rejects
  collections, CFF/WOFF containers, embedding-restricted flags, oversized files,
  excessive glyph counts, and changed-while-read assets before a candidate is
  written.
- Decision: adopt the exact graph for the Unicode PDF font slice. This review is
  dependency-adoption evidence only and is not the independent whole-release
  provenance attestation.
