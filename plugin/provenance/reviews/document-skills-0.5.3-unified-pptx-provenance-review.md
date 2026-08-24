# CLEAN — Document Skills 0.5.3 Unified PPTX Provenance Review

Date: 2026-08-24

## Verdict

Status: `clean`

Approval claimed: `true`, limited to the source, classification, review-evidence,
and exact-inventory claims in this report. This is not a general implementation,
fidelity, remote-platform, or maintainer release approval.

Canonical findings after remediation: **0 Blocker, 0 Major, 0 Minor, 0 Trivial**.

The approved mapping contains **411 release files**: **319** risky module records,
**89** exact-hash data classifications, **0** executable exclusions, and exactly
**3** self-referential metadata exclusions. Its SHA-256 is:

`e9388609e9d3f7825c96a390d2f7085b847c226e13ef9d238378f3a7599fe297`

## Reviewer

- Reviewer: `OpenAI Codex independent provenance reviewer: unified-plugin-packaging/2026-08-24`
- Identity: `codex-reviewer/document-skills-0.5.3-unified-pptx-provenance/gpt-5-2026-08-24`
- Runtime: `codex`
- Role: `reviewer`
- Scope: `all-release-artifacts`
- Identity assurance: `self-asserted`
- Identity limitations: This self-asserted reviewer cannot cryptographically prove the backing
  model, service principal, or human operator and does not establish remote-platform execution
  or replace final maintainer approval.
- Attestation id: `document-skills-0.5.3-unified-pptx-provenance-review`

No pre-generated candidate, previous attestation, or historical clean verdict was treated as
approval evidence. Historical reports were inspected only as release data and are exact-hashed
by the current mapping.

## Findings remediated before binding

1. The checked-in manifest described the prior 345-file / 262-module release while the current
   tree contained 410 files / 319 risky artifacts. The current inventory was independently
   enumerated and the final mapping was regenerated only after all reviewed bytes were fixed.
2. Provenance policy promises a three-path self-reference boundary, but the implementation
   permanently excluded 15 historical review reports from hashing. Those reports contain prior
   mapping digests and are not circular in the current mapping. The generator and validator now
   reserve hashless classification for exactly `provenance/modules.json`,
   `provenance/audit-report.json`, and this current mapping-bound report. Every historical review
   is now `reviewed-data` with an exact SHA-256. Focused tests pin both the historical-data rule
   and rejection of an unlisted current-review filename.
3. The capability-parity provenance prose said MiniMax source was adopted even though the source
   manifest, notices, and repository history all say that no adopted source is present. The
   statement now truthfully says that this release has no adopted source and that future adoption
   requires notices plus module-level provenance.

## Independent inventory and classification review

- Every prospective release path is a tracked regular file. No symlink or submodule is present,
  and the shared inventory differs from tracked plugin content only by documented developer-only
  directories.
- The classifier found 298 Python files, 17 Node `.mjs` files, two extensionless release files,
  and two C#/.NET helper files under an execution-bearing provider location: 319 risky artifacts
  in total. Independent path, suffix, magic, executable-location, and hash checks agreed with the
  generated records.
- The 89 hash-bound data records comprise 62 high-text `reviewed-data` files and 27
  `fixture-data` files. All non-circular records match their current SHA-256; no path is omitted,
  duplicated, overlapped, or classified both as code and data.
- Every non-binary release file strictly decodes as UTF-8. None has a BOM, Unicode replacement
  character, or the checked common mojibake markers. JSON and TOML release files parse cleanly.

## Source and license review

- All 319 risky records are classified `original`, `clean_room: true`, `GPL-3.0`, with empty
  `third_party_files`. Git history attributes the shipped implementation files to project commits;
  source/header/reference searches found no copied-source copyright, SPDX, upstream repository,
  MiniMax, claude-office-skills, or Anthropic implementation reference in runtime, Skills,
  consumer validation, or provenance tooling.
- Public OPC, OOXML, PDF, JSON Schema, and browser APIs appear as interface vocabulary and do not
  turn the project-authored implementation into adopted source. The exact external package code
  remains outside the release inventory.
- The frozen production graphs are seven Python packages and six Node packages. Lock files,
  dependency allowlist, license map, third-party notices, and the deterministic CycloneDX SBOM
  agree. `npm audit --omit=dev` reported zero vulnerabilities; registry verification reported six
  signed packages and one attestation. `uv lock --check` and the independently printed frozen
  Python production/development trees succeeded.
- The SBOM scope is the redistributed/frozen Python and Node graph plus its three hashed Node
  provider files. System browsers, LibreOffice, .NET, and `DocumentFormat.OpenXml` are optional
  host-provided enhancements and are not claimed as redistributed components by this review.

## Executable and public-surface review

- Static execution audit inspected 315 Python/Node source files. Dynamic import, evaluation,
  reflection, MCP dependency/registration, transport, daemon, hook, and manifest execution
  surfaces remain rejected. The only local HTTP listener is a tokenized loopback asset server.
- Native child execution remains centralized in the project process runner with argv arrays,
  `shell=False`, bounded streams/time, private working state, cancellation, and process-tree
  cleanup. This containment is not claimed to be an operating-system privilege sandbox.
- Both registration manifests remain discovery-only. Command discovery found 21 approved public
  command examples, all through the four thin frozen-uv Skill entrypoints. The public Skill set is
  exactly `document-docx`, `document-pdf`, `document-pptx`, and `document-xlsx`.

## Fixture and evidence review

- All 27 fixture-data records are marked generated, redistributable, and GPL-3.0 with a concrete
  recipe and exact hash. The foundation probe regenerated byte-for-byte. The HTML/PPTX recipe
  regenerated twice to the checked-in HTML, image, scene, oracle matrix, and PPTX bytes.
- The deterministic audit, lock/SBOM test, mapping-completeness test, historical-review hash test,
  exact current-review allowlist test, and fixture tests passed before attestation binding.
- `git diff --check` and repository object verification completed without errors.

Post-binding verification passed all 40 tests in `tests/test_supply_chain.py` and all 89 tests in
`tests/test_structure.py` plus `tests/test_html_provenance.py`. Fresh deterministic regeneration
then reproduced both the checked-in manifest and audit report byte-for-byte.

## Evidence boundary

The automated gates prove current path coverage, hashes, declared classifications, static source
policy, lock/SBOM parity, fixture registration, and report-byte/mapping binding. They cannot prove
the asserted reviewer identity, detect every possible expression-level derivation, establish the
behavior of a compromised runtime or native host dependency, or substitute for remote Windows,
macOS, Linux, browser, LibreOffice, or .NET execution. No such broader claim is made.
