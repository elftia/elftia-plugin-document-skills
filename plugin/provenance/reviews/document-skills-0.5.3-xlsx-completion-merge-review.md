# CLEAN — Document Skills 0.5.3 XLSX Completion Final Review

Date: 2026-08-26 — incremental re-review of `3423c56`

## Verdict

Status: `clean`

Approval claimed: `true`, limited to the exact `all-release-artifacts`
mapping identified below.

Canonical findings: **0 Blocker, 0 Major, 0 Minor**.

The two Major findings from the preceding review remain remediated. The
subsequent test-only provenance correction in `3423c56` was independently
reviewed against the previously approved and bound `5809792` baseline and
introduced no new finding. The current all-release-artifacts mapping contains
**541 release files**: **423** risky module records, **115** exact-hash data
classifications, **0** executable exclusions, exactly **3** self-referential
metadata exclusions, and **0** review attestations. Its independently
regenerated SHA-256 is:

`0f6c27a7fa950aa02b5ddf854a392c3ea8bf8cbec4c2a0123a69bc39ccf48b6b`

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
- Incremental review baseline:
  `58097929bbff63cc9999f869b8ab4211312f77f6`
- Baseline tree: `58b8da327f1665f928b948808ce341760a9327d8`
- Implementation commit: `3423c561f8fa9b8e910d1ca94beccf885dc7997f`
- Implementation tree: `c6d75d5f6e64aadb59ac5a667470880ecce2cda1`
- Reviewer integration commit: `10ab0608fae674ea43f5624f6ec7012634a8be6d`
- Mapping SHA-256:
  `0f6c27a7fa950aa02b5ddf854a392c3ea8bf8cbec4c2a0123a69bc39ccf48b6b`
- Runtime source allowlist SHA-256:
  `7d56bad75091de424e25b5f7de62074bce3fad1391975ad71d41d6d3921de722`
- CycloneDX SBOM SHA-256:
  `8f6709173225b4fe7a5dfc04ba50bae730fbf7e9bb4bcd54902775efc264072b`

The implementation tree was independently matched after conflict resolution:
both the source implementation and reviewer branch resolve to
`c6d75d5f6e64aadb59ac5a667470880ecce2cda1` before this excluded review report
is updated. The only integration conflict was the expected bound-versus-
unbound `modules.json`; the reviewer selected the exact unbound bytes from
`3423c56`.

## Incremental review — canonical PPTX provenance owner

`5809792..3423c56` changes one test source plus its unbound generated
provenance and audit metadata. `tests/test_strategy3.py` now imports the
canonical `pptx_module_profile` from `tools.html_pptx_provenance` and derives
the expected requirement from tuple element 2. This removes its duplicate
reconstruction from separate HTML/Core helpers and makes the test use the same
combined requirement chosen by production provenance generation.

The canonical combinations were inspected for all eight PPTX-owned paths in
the shared XLSX test surface. They include HTML-only ownership, combined
HTML/Core ownership, and the special shared provenance requirement for
`tools/regenerate_provenance.py`. The focused tests verify those canonical
requirements compose with Core, completion, and advanced XLSX ownership in
the generated records.

The checked-in unbound `modules.json` is JSON-semantically equal to a fresh
in-process regeneration. Its only source hash delta from the previous unbound
tree is `tests/test_strategy3.py`, whose recorded and actual SHA-256 both equal
`cc2c01a91755500fec6137e6444dfafad1290b50126d003cb46d46592fec477f`.
The checked-in audit report is intentionally unbound and contains exactly the
expected missing-independent-attestation error.

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

- Focused incremental cases, passed to `pytest.main` after pinning the local
  `tests/` namespace:
  `pytest -q tests/test_strategy3.py::test_xlsx_provenance_composes_provider_and_existing_shared_owners tests/test_strategy3.py::test_xlsx_provenance_profiles_are_exact_and_cover_the_current_inventory tests/test_strategy3.py::test_shared_xlsx_provenance_composes_requirements_and_direct_evidence`
  — **3 passed**. Pinning avoided an unrelated user-site package named `tests`
  shadowing repository fixtures.
- `python -m tools.regenerate_provenance --project-root . --print-mapping-only`
  and a separate in-process regeneration both produced
  `0f6c27a7fa950aa02b5ddf854a392c3ea8bf8cbec4c2a0123a69bc39ccf48b6b`.
- Strict UTF-8 decoding passed without BOM, U+FFFD, or mojibake markers for all
  three increment files. Both JSON files parsed, the Python source parsed with
  `ast.parse`, and `git diff --check 5809792..3423c56` passed.
- Focused remediation command:
  `pytest -q tests/test_xlsx_macro_template.py::test_xltx_template_instantiation_can_delete_a_plain_sheet tests/test_supply_chain.py::test_sbom_is_deterministic_and_matches_locks`
  — **2 passed**.
- The current checked-in unbound manifest exactly matched fresh regeneration.
- Mapping inventory: 423 modules, 115 data classifications, 0 executable
  exclusions, 3 metadata exclusions, and 0 review attestations.
- The regenerated runtime source allowlist matches the checked-in canonical
  bytes at SHA-256
  `7d56bad75091de424e25b5f7de62074bce3fad1391975ad71d41d6d3921de722`.
- The regenerated CycloneDX SBOM matches the checked-in canonical bytes at
  SHA-256
  `8f6709173225b4fe7a5dfc04ba50bae730fbf7e9bb4bcd54902775efc264072b`.
- The prior full local audit produced exactly one expected error:
  `provenance: Independent review attestation is missing`. Its locked `acorn`
  dependency was supplied temporarily for AST audit and removed afterward.
  All other audit checks passed. For the current increment, the unbound audit
  JSON was parsed and independently checked to contain exactly the same sole
  missing-attestation error; this report is that missing attestation.
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
process were not run during this incremental re-review.

## Attestation

I attest that the Codex reviewer identified above independently reviewed the
incrementally updated implementation tree and its exact all-release-artifacts
mapping and found **0 Blocker, 0 Major, 0 Minor** issues within scope. I approve binding
this report as the clean independent review attestation for mapping SHA-256
`0f6c27a7fa950aa02b5ddf854a392c3ea8bf8cbec4c2a0123a69bc39ccf48b6b`
and no other mapping.
