# FINDINGS — Document Skills 0.5.3 XLSX Completion Final Review

Date: 2026-08-26

## Verdict

Status: `findings`

Approval claimed: `false`.

Canonical findings: **0 Blocker, 2 Major, 0 Minor**. The reviewed XLSX
completion merge is not ready for provenance binding or delivery until both
Major findings below are remediated and independently re-reviewed.

The current unbound all-release-artifacts mapping contains **541 release
files**: **423** risky module records, **115** exact-hash data classifications,
**0** executable exclusions, and exactly **3** self-referential metadata
exclusions. It contains **0** review attestations. Its independently
regenerated SHA-256 is:

`bcd354f97636491dec016968f5f093bff5cd33e7911935476d345860b189d3d3`

This digest is evidence for the exact reviewed bytes, not an approval. It will
change when the stale SBOM is regenerated and therefore must be recomputed
after remediation.

## Reviewer identity

- Reviewer: `Codex collaboration subagent /root/ship_xlsx_completion/xlsx_final_review`
- Identity: `codex-reviewer/document-skills-0.5.3-xlsx-completion-final/fresh-non-author-2026-08-26`
- Runtime: `codex`
- Role: `reviewer`
- Scope: `all-release-artifacts`
- Identity assurance: `self-asserted`
- Identity limitations: This self-asserted reviewer cannot cryptographically
  prove the backing model, service principal, or human operator; it does not
  replace maintainer approval and does not establish remote CI, pull-request,
  merge, live LibreOffice, live .NET/OpenXML, or unobserved operating-system
  behavior.
- Report id: `document-skills-0.5.3-xlsx-completion-merge-review`

No previous attestation, historical clean verdict, checked-in audit report, or
pre-generated mapping digest was treated as approval evidence. This reviewer
did not author the implementation, tests, planning artifacts, provenance
generator, or manifest under review.

## Reviewed target

- Review branch: `review/xlsx-completion-final-20260826`
- Base: `origin/main` at `6525b0ad79db705aa111c012b1c2ebd81d18afe1`
- Reviewed HEAD: `3c94b1c02c3fe87f094c706179eef208e83141f5`
- Reviewed tree: `56f1d1e3da8e1fc65a16fa137f24d7821c84e979`
- Diff scope: 183 files, 50,981 insertions, 3,154 deletions
- Runtime source allowlist SHA-256:
  `7d56bad75091de424e25b5f7de62074bce3fad1391975ad71d41d6d3921de722`

## Findings

### Major 1 — template sheet deletion always fails preservation validation

`xlsx.template.instantiate` advertises `optional_bounded_edits` and accepts the
normal `sheet_delete` edit contract, but a valid template instantiation that
deletes a plain worksheet fails instead of producing an XLSX.

The failing call chain is:

1. `formats/xlsx/template_operation.py:83` compares the original template with
   the edited output and correctly supplies `expected_removed`.
2. `formats/xlsx/package.py:257` computes preserved parts as
   `input_names - set(changed)` without subtracting `removed`.
3. The deleted worksheet therefore appears in both `manifest.removed` and
   `manifest.preserved`.
4. `formats/xlsx/validation.py:1086-1087` looks up every preserved part in
   `manifest.output_hashes`; the removed worksheet is absent. The resulting
   `KeyError` is captured as a failed `operation.part-preservation` gate.

A provider-free reproduction used a two-sheet `.xltx`, requested
`sheet_delete` for the second sheet, and called the public `XlsxService` path.
The result was `status=failed`, error `DS_VALIDATION_FAILED`, failed gate
`operation.part-preservation`, and no destination file was promoted.

Required remediation: exclude removed parts from the preservation set, for
example `input_names - set(changed) - set(removed)`, and add an end-to-end
template regression proving a supported `sheet_delete` edit succeeds while
the source remains unchanged.

### Major 2 — checked-in CycloneDX SBOM does not match the locked dependencies

The release SBOM is stale relative to the exact dependency locks. The
deterministic builder in `tools/supply_chain.py:83-103` derives its revision
from `uv.lock`, `package-lock.json`, and the NuGet `packages.lock.json`. It now
computes lock revision:

`7e15d508fed944f7e55e4d6993825030ae6006620cdc04b45ca7a4661ed3d52d`

The checked-in `sbom.cdx.json:443-444` still records:

`fc6f85098f948a3cb82b03ebf68eafe04eac54583b0c11a182b13b5e60a0e6d9`

The canonical generated SBOM SHA-256 is
`8f6709173225b4fe7a5dfc04ba50bae730fbf7e9bb4bcd54902775efc264072b`;
the checked-in file SHA-256 is
`46830e0f0d8a2746db70e6440ec7975a1cff9b3f990b3fdd7409baac9f22a5bf`.
The focused deterministic-SBOM regression fails at
`tests/test_supply_chain.py:225` on this exact mismatch.

This also means the checked-in audit report, which currently lists only the
missing independent attestation, is stale and cannot establish current release
parity. Required remediation: regenerate `sbom.cdx.json`, then regenerate the
provenance mapping/runtime metadata and audit report from the resulting exact
bytes before requesting another independent review.

## PATH-containment incident check

The previously reported Windows user-PATH incident is contained in this tree:

- `ProcessRunner._minimal_environment()` unconditionally sets
  `DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=0` for managed subprocesses.
- The dotnet provider supplies private `DOTNET_CLI_HOME`, NuGet, temp, and
  application-data roots through the shared `ProcessRunner` path.
- The two focused containment regressions passed, including an inherited
  hostile `DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=1` case and cleanup of the private
  operation root.
- Direct real-dotnet test entry points also construct an explicit opt-out
  environment; no real dotnet command was run during this review.

No remaining production launch path was found that invokes dotnet outside the
contained runner or permits dotnet to append a per-run tools directory to the
user PATH.

## Planning and implementation coverage

The proposal, design, specification, and task artifacts for both
`document-skills-xlsx-completion` and
`document-skills-xlsx-advanced-authoring` were read in full. Review coverage
included the seven completion operations, original-operation advanced
authoring, package/security boundaries, formula state and static analysis,
conversion typing and injection defenses, macro/template preservation,
summary and native pivot construction, structural reference migration,
render/schema provider gates, LibreOffice input/output/quota boundaries,
process identity pinning, and all-file provenance generation.

One investigated 3-D formula-reference concern was not retained as a finding:
the current static analysis rejects `Sheet1:Sheet3!A1` as unsupported before a
mutation candidate can be promoted, so the path fails closed rather than
silently publishing an incorrectly migrated workbook.

## Independent verification evidence

- Provider-free template `sheet_delete` reproduction: returned `failed` with
  `operation.part-preservation`; destination absent.
- `pytest -q
  tests/test_dotnet_provider.py::TestRunnerContainment::test_private_dotnet_environment_is_project_scoped_and_cleanable
  tests/test_dotnet_provider.py::TestRunnerContainment::test_env_sanitized_by_process_runner`:
  **2 passed**.
- `pytest -q
  tests/test_supply_chain.py::test_sbom_is_deterministic_and_matches_locks`:
  **1 failed**, confirming the stale lock revision in the checked-in SBOM.
- Two independent in-process/CLI regenerations produced mapping digest
  `bcd354f97636491dec016968f5f093bff5cd33e7911935476d345860b189d3d3`
  with 423 modules, 115 data records, 3 metadata exclusions, and 0
  attestations.
- The generated runtime allowlist matched the checked-in canonical bytes at
  SHA-256
  `7d56bad75091de424e25b5f7de62074bce3fad1391975ad71d41d6d3921de722`.
- Production and test dotnet environment construction was inspected without
  executing dotnet.

## Evidence boundary

This was a local review of exact repository bytes. Per explicit direction, it
did not investigate, wait for, or treat remote CI as a blocker. It did not run
the repository-wide verification suite, provider/full pytest suites,
`npm run verify`, `verify:repro`, a live LibreOffice process, or a real dotnet
process. No pull request, push, merge, or release approval is claimed here.

## Non-attestation

I attest only that the Codex reviewer identified above independently reviewed
the stated tree and found **0 Blocker, 2 Major, 0 Minor** issues within scope.
I do **not** approve binding this report as a clean review attestation, do not
approve the current mapping for release, and do not approve delivery until the
findings are remediated and a fresh independent review returns clean.
