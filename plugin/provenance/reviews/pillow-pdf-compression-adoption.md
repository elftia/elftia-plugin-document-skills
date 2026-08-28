# Pillow PDF compression and oriented-JPEG adoption review

- Review date: 2026-08-24
- Scope-extension review date: 2026-08-26
- Candidate: `Pillow==12.3.0`
- Exact source release: `pillow-12.3.0.tar.gz`
- Source SHA-256: `3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce`
- License: HPND, as recorded by the locked wheel metadata and dependency-license policy.
- Locked-wheel availability: the locked release publishes CPython wheels for supported Windows,
  macOS, manylinux, and musllinux targets, including x86_64/AMD64, ARM64/aarch64, and the
  project's Python 3.11+ range. Wheel publication is availability evidence only; it is not a
  current-revision cross-platform run receipt or viewer-compatibility result.
- Existing graph: the same exact Pillow release was already locked transitively for the
  development-only `python-pptx` consumer suite. This decision promotes it to a direct
  production dependency; no new transitive package is introduced.
- Accepted responsibility split: Elftia owns the closed `lossless|balanced|aggressive`
  contract, strict PDF preflight, page/image/pixel limits, alpha fail-closed rule, mode policy,
  pypdf object replacement, byte-gain gate, semantic round trip, decoded-image PSNR evidence,
  and atomic promotion. Pillow only decodes, resamples, encodes, and compares bounded raster
  buffers in the isolated worker.
- Additional narrow creation path: for JPEG EXIF orientation values 2 through 8 only, Elftia
  owns caller-local input selection, regular-file and JPEG-magic validation, APP1/APP14 marker
  parsing, source hash and TOCTOU checks, the 16 MiB source / 40 million pixel / 160 MiB
  decoded-byte ceilings, the orientation 1-through-8 policy, frame/decoder-size agreement,
  closed Gray/RGB output, Flate PDF serialization, creation evidence, candidate reopen checks,
  and atomic promotion. Pillow receives only an already-local, marker-inspected,
  budget-preflighted orientation-2-through-8 JPEG and performs bounded decode,
  `ImageOps.exif_transpose`, Gray/RGB conversion, and pixel extraction. It does not discover
  inputs, access remote or system resources, write the PDF, own budgets, produce promotion
  evidence, or decide publication. PNG and orientation-1 JPEG creation remain on the
  Elftia-authored parser/embedder path and do not invoke Pillow pixel-decoding or transform
  APIs.
- Quality policy: balanced uses quality 82 and a 1920-pixel maximum dimension with PSNR at
  least 24 dB; aggressive uses quality 60 and a 1280-pixel maximum dimension with PSNR at
  least 18 dB. Candidate image pixels are compared after resampling to the source dimensions.
  This image-level evidence is not represented as a full-page render diff.
- Safety boundary: at most 1,000 distinct indirect images and 40 million decoded pixels per
  request. Inline and alpha-bearing images are skipped; decompression-bomb warnings, malformed
  images, no compatible images, quality failure, or non-positive final byte savings prevent
  publication.
- Test evidence: focused unit coverage checks orientation-6 grayscale decode/transpose into a
  bounded Flate `/DeviceGray` image, and public-operation coverage checks the locked
  orientation-6 fixture through create, semantic reopen, read, and validate with source hash,
  normalized geometry, filter, color space, and decoded pixels bound to expectations. Separate
  APP14/CMYK coverage checks Elftia's non-Pillow marker policy and `/Decode` binding, including
  candidate dictionary tamper rejection. These checks establish image-object semantics; they
  do not claim a whole-page visual comparison, a real-viewer receipt, or a current-revision
  cross-platform run.
- Rejected alternatives: PyMuPDF remains development-only because its distribution license is
  not accepted for this production path; external ImageMagick/GraphicsMagick commands would
  add an unregistered binary provider; blind pypdf rewriting provides no lossy quality metric.
- Decision: adopt the exact Pillow release for bounded PDF image compression, image-level
  visual-difference evidence, and the narrowly bounded EXIF-orientation-2-through-8 JPEG
  normalization step described above. This is dependency-adoption evidence, not an independent
  whole-release provenance attestation or whole-page visual/viewer certification.
