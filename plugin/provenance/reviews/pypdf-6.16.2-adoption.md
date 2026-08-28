# pypdf 6.16.2 adoption review

- Date: 2026-08-24
- Candidate id: `pypdf==6.16.2` with `cryptography==50.0.0`
- Source project and exact revision: PyPI releases `pypdf 6.16.2`, `cryptography 50.0.0`, `cffi 2.1.1`, and `pycparser 3.0`, frozen by `uv.lock`
- Original distributions and SHA-256:
  - `pypdf-6.16.2.tar.gz`: `595647f6191de6f402cfde1d0c455d6cbccbd509aac32b34783009c032de5d6e`
  - `cryptography-50.0.0.tar.gz`: `eeac2acb5a20ed25e0ad6d1df9891a520b78b404266b6d11778f25d5d691a6c9`
  - `cffi-2.1.1.tar.gz`: `dd31f52ea1086513bb9df30f8fcee9b8918323ae067a3d5b78bc826a000712be`
  - `pycparser-3.0.tar.gz`: `600f49d217304a5902ac3c37e1281c9fe94e4d0489de643a9504c5cdfdfc6b29`
- License and redistribution evidence: PyPI SPDX metadata reports pypdf `BSD-3-Clause`, cryptography `Apache-2.0 OR BSD-3-Clause`, cffi `MIT-0`, and pycparser `BSD-3-Clause`; all are compatible with the GPL-3.0 plugin distribution
- Classification: A (adopt library APIs; no upstream source copied into Elftia modules)
- User-visible capability: `pdf.encrypt`, `pdf.decrypt`, and evidence-backed `pdf.compress(lossless)`
- Artifact fidelity evidence: public worker-boundary tests reopen AES-256-R5 output, verify `/V 5`, `/R 5`, 256-bit `/AESV3`, credentials, permission integrity, page/text semantics, explicit decrypt round-trip, wrong-password rollback, and strictly smaller lossless compression output
- Preservation/security findings: mutations use private staging, source SHA-256 verification, destination snapshots, canonical validation identity, and atomic promotion; password values are accepted only in bounded request fields and never returned in argv, results, diagnostics, warnings, or errors
- Runtime dependencies: exact production pins `pypdf==6.16.2` and `cryptography==50.0.0`; the frozen lock resolves `cffi==2.1.1` and `pycparser==3.0`
- Pure file/business logic retained: pypdf PDF clone/encryption/decryption/content-stream compression APIs behind Elftia-owned contracts and validation
- Wrapper/transport/registration/lifecycle code removed: none adopted; Elftia owns provider detection, worker dispatch, transaction/promotion, diagnostics, and capability registration
- Modifications: exact-version functional AES detector; strong-algorithm-only contract; explicit permission mapping; semantic and byte-size validation
- Reviewer: Codex implementation session, pending repository review cycle
- Reviewer identity and review evidence paths: `tests/test_pdf_public.py`, `src/document_skills_core/providers/pypdf/`, and this review
- Artifact tests: focused public encryption/decryption/compression suite plus full PDF suite before delivery
- Notice and SBOM updates: dependency allowlist/licenses updated; `sbom.cdx.json` regenerated from the frozen graph

## Decision

Adopt. pypdf is the smallest accepted production dependency that supplies strong PDF
encryption/decryption and lossless optimization without introducing the AGPL/commercial
distribution constraint of PyMuPDF. The AES code path is not considered callable unless the
exact cryptography runtime is present and an in-memory AES-256-R5 functional probe succeeds.
Balanced/aggressive optimization remains unavailable because this adoption does not provide
independent visual quality evidence for lossy image changes.
