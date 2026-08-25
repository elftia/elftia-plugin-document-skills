# Pillow PDF compression adoption review

- Review date: 2026-08-24
- Candidate: `Pillow==12.3.0`
- Exact source release: `pillow-12.3.0.tar.gz`
- Source SHA-256: `3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce`
- License: HPND, as recorded by the locked wheel metadata and dependency-license policy.
- Cross-platform evidence: the locked release publishes CPython wheels for supported Windows,
  macOS, manylinux, and musllinux targets, including x86_64/AMD64, ARM64/aarch64, and the
  project's Python 3.11+ range.
- Existing graph: the same exact Pillow release was already locked transitively for the
  development-only `python-pptx` consumer suite. This decision promotes it to a direct
  production dependency; no new transitive package is introduced.
- Accepted responsibility split: Elftia owns the closed `lossless|balanced|aggressive`
  contract, strict PDF preflight, page/image/pixel limits, alpha fail-closed rule, mode policy,
  pypdf object replacement, byte-gain gate, semantic round trip, decoded-image PSNR evidence,
  and atomic promotion. Pillow only decodes, resamples, encodes, and compares bounded raster
  buffers in the isolated worker.
- Quality policy: balanced uses quality 82 and a 1920-pixel maximum dimension with PSNR at
  least 24 dB; aggressive uses quality 60 and a 1280-pixel maximum dimension with PSNR at
  least 18 dB. Candidate image pixels are compared after resampling to the source dimensions.
  This image-level evidence is not represented as a full-page render diff.
- Safety boundary: at most 1,000 distinct indirect images and 40 million decoded pixels per
  request. Inline and alpha-bearing images are skipped; decompression-bomb warnings, malformed
  images, no compatible images, quality failure, or non-positive final byte savings prevent
  publication.
- Rejected alternatives: PyMuPDF remains development-only because its distribution license is
  not accepted for this production path; external ImageMagick/GraphicsMagick commands would
  add an unregistered binary provider; blind pypdf rewriting provides no lossy quality metric.
- Decision: adopt the exact Pillow release for bounded PDF image compression and image-level
  visual-difference evidence. This is dependency-adoption evidence, not an independent
  whole-release provenance attestation.
