# CLEAN — Document Skills 0.5.3 XLSX Completion Final Review

Date: 2026-08-26

## Verdict

Status: `clean`

Approval claimed: `true`, limited to the exact `all-release-artifacts`
mapping identified below.

Canonical findings: **0 Blocker, 0 Major, 0 Minor**.

The two Major findings from the preceding review were remediated and
independently re-reviewed. The current all-release-artifacts mapping contains
**541 release files**: **423** risky module records, **115** exact-hash data
classifications, **0** executable exclusions, exactly **3** self-referential
metadata exclusions, and **0** review attestations. Its independently
regenerated SHA-256 is:

`09119c9db27bf5595a59f37d1c5dc43bebc1c70e722467f5793993260e925865`

This clean approval binds only to those exact reviewed bytes and mapping. Any
release-artifact change requires a new mapping and independent review.

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
- Base: `origin/main@6525b0ad79db705aa111c012b1c2ebd81d18afe1`
- Implementation commit: `c9b4e4dc8381fb3b18b24d97e6ef93f8298767e6`
- Implementation tree: `b1f49ecb67585578dfb24e819a98a1e74cb12721`
- Reviewer cherry-pick commit: `7fc04a48832d12c8a08aa07c19668db5b1e8f218`
- Mapping SHA-256:
  `09119c9db27bf5595a59f37d1c5dc43bebc1c70e722467f5793993260e925865`
- Runtime source allowlist SHA-256:
  `7d56bad75091de424e25b5f7de62074bce3fad1391975ad71d41d6d3921de722`
- CycloneDX SBOM SHA-256:
  `8f6709173225b4fe7a5dfc04ba50bae730fbf7e9bb4bcd54902775efc264072b`

The implementation tree was independently matched after cherry-pick: both the
source implementation and reviewer branch resolve to
`b1f49ecb67585578dfb24e819a98a1e74cb12721` before this excluded review report
is updated.

## Remediation review

### Major 1 — template sheet deletion preservation

Resolved. `compare_preservation()` now computes preserved package parts as:

`input_names - set(changed) - set(removed)`

Declared removals therefore no longer appear simultaneously in the preserved
set. A provider-free end-to-end `.xltx` regression now instantiates a
two-sheet template with `sheet_delete`, proves the operation succeeds, proves
the source template SHA-256 is unchanged, and proves the output contains only
the retained target sheet.

### Major 2 — stale CycloneDX SBOM

Resolved. The checked-in CycloneDX SBOM now matches the exact dependency locks
and records lock revision:

`7e15d508fed944f7e55e4d6993825030ae6006620cdc04b45ca7a4661ed3d52d`

The canonical generated SBOM matches the checked-in bytes at SHA-256
`8f6709173225b4fe7a5dfc04ba50bae730fbf7e9bb4bcd54902775efc264072b`.
The provenance module metadata and checked-in audit report were regenerated
for the remediated bytes.

## Independent verification evidence

- Focused remediation command:
  `pytest -q tests/test_xlsx_macro_template.py::test_xltx_template_instantiation_can_delete_a_plain_sheet tests/test_supply_chain.py::test_sbom_is_deterministic_and_matches_locks`
  — **2 passed**.
- Two independent mapping regenerations, including the CLI path, produced
  `09119c9db27bf5595a59f37d1c5dc43bebc1c70e722467f5793993260e925865`.
- Mapping inventory: 423 modules, 115 data classifications, 0 executable
  exclusions, 3 metadata exclusions, and 0 review attestations.
- The regenerated runtime source allowlist matches the checked-in canonical
  bytes at SHA-256
  `7d56bad75091de424e25b5f7de62074bce3fad1391975ad71d41d6d3921de722`.
- The regenerated CycloneDX SBOM matches the checked-in canonical bytes at
  SHA-256
  `8f6709173225b4fe7a5dfc04ba50bae730fbf7e9bb4bcd54902775efc264072b`.
- The independent local audit produced exactly one expected error:
  `provenance: Independent review attestation is missing`. Its locked `acorn`
  dependency was supplied temporarily for AST audit and removed afterward.
  All other audit checks passed; this report is the missing independent
  attestation.
- The earlier focused PATH-containment checks remained green:
  `TestRunnerContainment::test_private_dotnet_environment_is_project_scoped_and_cleanable`
  and
  `TestRunnerContainment::test_env_sanitized_by_process_runner` — **2 passed**.
  The remediation delta did not touch the process or dotnet runner.

## PATH-containment incident check

The reviewed implementation unconditionally sets
`DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=0` for managed subprocesses. The dotnet
provider supplies private `DOTNET_CLI_HOME`, NuGet, temporary, and
application-data roots through the shared contained runner. No reviewed
production launch path permits dotnet to append a per-run tools directory to
the persistent user PATH.

No real dotnet command was run during this review.

## Evidence boundary

This was a local review of exact repository bytes. Per explicit direction,
remote CI was not queried, awaited, or investigated and is not part of this
verdict. The repository-wide verification suite, provider/full pytest suites,
`npm run verify`, `verify:repro`, a live LibreOffice process, and a real dotnet
process were not run during this remediation re-review.

## Attestation

I attest that the Codex reviewer identified above independently reviewed the
remediated implementation tree and its exact all-release-artifacts mapping and
found **0 Blocker, 0 Major, 0 Minor** issues within scope. I approve binding
this report as the clean independent review attestation for mapping SHA-256
`09119c9db27bf5595a59f37d1c5dc43bebc1c70e722467f5793993260e925865`
and no other mapping.
