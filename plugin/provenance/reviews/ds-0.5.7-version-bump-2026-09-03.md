# Document Skills 0.5.7 exact-byte independent review

- Date: 2026-09-03
- Repository: `elftia-plugin-document-skills`
- Branch: `main`
- Base: `1a46440c4a966130620b95fbae633f4b87b3f9da`
- HEAD: `1a46440c4a966130620b95fbae633f4b87b3f9da` plus the uncommitted 0.5.7 delta
- Reviewer: Codex exact-byte independent reviewer
- Reviewer identity: `codex-reviewer/elftia-plugin-document-skills/0.5.7-exact-bytes`
- Runtime / role: `codex` / `reviewer`
- Identity assurance: `self-asserted`
- Scope: `all-release-artifacts`
- Status: `clean`
- Approval claimed: `true`
- Reviewed mapping SHA-256: `9f7d0772f0eaad9b8e9e0cc91511610bc2633bb485e26db56e4cc06b88c190ee`

## Verdict

The pre-binding 0.5.7 candidate has **0 Blockers and 0 Majors**. Approval is
granted for the exact source, provenance, dist, EPKG, and EPKG v2 sidecar bytes
reviewed here.

The working tree remained at `main` HEAD
`1a46440c4a966130620b95fbae633f4b87b3f9da` plus exactly the expected
uncommitted 0.5.7 delta: 15 modified files and the new
`provenance/reviews/ds-0.5.7-version-bump-2026-09-03.md` review artifact.
No unexpected file appeared before or after verification, and `git diff
--check` passed.

The tracked delta is limited to the root package manifest and lock, plugin
identity files, regenerated SBOM and provenance mapping, schema example,
version test, Python and .NET version declarations, current-review pointer,
and plugin lock metadata. The focused diff across `plugin/src`,
`plugin/tests`, `plugin/tools`, and `plugin/skills` contains only the intended
version-string and current-review-pointer changes; there is no substantive
source or skill drift.

## Exact mapping and provenance evidence

- Fresh in-memory regeneration produced mapping digest
  `9f7d0772f0eaad9b8e9e0cc91511610bc2633bb485e26db56e4cc06b88c190ee`.
- The stored `provenance/modules.json` equals the freshly regenerated PENDING
  mapping exactly.
- The mapping contains 813 module records, 252 data classifications, exactly
  three metadata exclusions, and zero executable exclusions.
- The 1,068 classified paths are unique and comprise the complete release
  inventory.
- The metadata set is exactly:
  - `provenance/audit-report.json`
  - `provenance/modules.json`
  - `provenance/reviews/ds-0.5.7-version-bump-2026-09-03.md`
- The 0.5.6 report is hash-pinned once as `reviewed-data`, with SHA-256
  `33b71f0ea4cc60aa954a2073d21d851b50f7f9913408b847fb24bfcf91eb9763`.
- All 1,065 hash-bearing module and data records match the current file bytes.
- Every provenance record remains `PENDING independent review`, and
  `review_attestations` is empty, as required before this report is bound.

The aggregate audit exited 2 in the intended pre-binding state. Its observed
check statuses were:

- `clean_room`: pass
- `commands`: pass
- `execution_boundary`: pass
- `fixtures`: pass
- `inventory`: pass
- `manifests`: pass
- `public_skills`: pass
- `sbom`: pass
- `provenance`: fail

The only reported error was:

```text
Independent review attestation is missing
```

No other audit error was present.

## Runtime, identity, and test evidence

All required release identity fields were parsed from their native structures.
Every observed value was exactly `0.5.7`, with no competing version:

- root `package.json`;
- root `package-lock.json`, both the top-level and root-package fields;
- plugin `package.json`;
- plugin `package-lock.json`, both version fields;
- `elftia-plugin.json`;
- `.claude-plugin/plugin.json`;
- `pyproject.toml`;
- the `elftia-document-skills` package in `uv.lock`;
- `document_skills_core.__version__`;
- the .NET helper `PropertyGroup/Version`;
- `doctor-report.schema.json` example project version;
- SBOM metadata component version;
- `test_structure.py` expected version set.

The regenerated SBOM passed the aggregate audit. Its observed SHA-256 was
`85499feb7471d2f530d922615ee4649dc3a63ed90abc0c7865c1a15077b063f0`.

The producer declaration is `@elftia/plugin-kit` range `^0.2.1`. The root lock
and installed producer copy both resolve exactly to version `0.2.1`. The lock
uses:

```text
sha512-HkJbJLWePD6aJ7M50hx9AvNWszkdTCH4L27Ai1vXfw5PzlikEqMd61Eu9fanS6YRqWgDs8ZxjsfNRHh4ZOs07Q==
```

The npm registry independently returned the same integrity and published
SHA-1 `ce66dcc587b0b0754cc7c02e3b1fd9f3d4bfd9de`.

All 16 changed or newly added text files decoded strictly as UTF-8, with no
BOM, replacement character, or detected mojibake signature.

## Package evidence

- The reviewed pre-binding EPKG starts with ZIP signature bytes
  `50 4b 03 04`.
- EPKG SHA-256:
  `f90c65eabc18efe54392c0ea5f1bed35aee679cfbbf4f466b2f8033ce73636c3`.
- EPKG size: 2,705,817 bytes.
- The ZIP contains exactly 1,068 regular file entries, no directory entries,
  no duplicate paths, no case-folded path collisions, and exactly one root
  `elftia-plugin.json`.
- ZIP CRC verification passed.
- There is no `node_modules` path and no `@elftia/plugin-kit` package path or
  implementation content. Exact-string occurrences are confined to the two
  provenance review reports describing the producer dependency and its
  absence from the plugin payload.
- The root packaged manifest identifies `document-skills`, kind `agent`,
  version `0.5.7`.

The sidecar has SHA-256
`2535a4ae3501de870ce5c601e92cec637d995a3ec153aa0d4a89b290b5b07681`
and declares:

```text
format: elftia-plugin-package
formatVersion: 2
id: document-skills
kind: agent
version: 0.5.7
sha256: f90c65eabc18efe54392c0ea5f1bed35aee679cfbbf4f466b2f8033ce73636c3
size: 2705817
fileCount: 1068
```

Every sidecar identity and measurement field matches the independently hashed
EPKG bytes and inventory.

The complete plugin release inventory, `dist/document-skills`, and EPKG entry
sets contain the same 1,068 paths. Per-file SHA-256 comparison found zero
source-to-dist mismatches and zero source-to-EPKG mismatches. Cross-format spot
hashes included:

- `elftia-plugin.json`:
  `e57c5ee7b82eaf05b112eaab2a94f75a601541517808c663dd9d71780309e38f`
- `pyproject.toml`:
  `47b0fde4cd348845638e02773c657fb5e8a81073ff15cb884d1ad1cd58a0f6fe`
- `src/document_skills_core/__init__.py`:
  `27765474b8672be4fe1ba7f65212d5617a89bfe915f5719e382ba9ac09c6b858`
- `src/document_skills_core/providers/dotnet/helper/OpenXmlHelper.csproj`:
  `b542ee7549356f136077048cdf3c12fbb9b8398a5417772d29420cca5634deb3`
- `schemas/doctor-report.schema.json`:
  `40298f0b92e71de36bffdf3b2b80a7cf8bae31f823431d27bde4f2c02c5ef915`
- `provenance/modules.json`:
  `02598d0a440cc2e4534f13cc8b042c603cc65ea77f9db0952e4ef8bc9c7b25d1`

## Limitations

The reviewer identity is self-asserted by the Codex runtime; the repository
cannot cryptographically prove the service or human principal operating this
session.

This review verifies repository bytes, declared provenance, the audit
fail-closed state, producer dependency metadata, full source/dist/archive
parity, and the generated package pair. It does not prove the behavior of a
compromised runtime, operating system, registry, native dependency, or future
code outside the reviewed inventory.

No command that writes repository output was run. In particular, I did not
install dependencies, regenerate files on disk, build packages, bind the
review, or use an audit output option. All Python verification used
`PYTHONDONTWRITEBYTECODE=1`.

## Durable findings

- The producer-only upgrade to `@elftia/plugin-kit@0.2.1` successfully re-cuts
  the package pair with an EPKG v2 sidecar without introducing plugin-kit
  package content into the plugin inventory.
- PENDING provenance with exactly one missing-attestation audit error is the
  correct pre-binding state; generated provenance is not itself approval.
- Historical review reports remain ordinary hash-pinned data, while only the
  current 0.5.7 report occupies the self-referential metadata seam.
- The release owner must bind this report, regenerate the affected provenance,
  dist, and release outputs, and expect the final container hash to change.
  The reviewed mapping digest remains stable because binding-only
  self-referential report bytes are excluded from that digest.