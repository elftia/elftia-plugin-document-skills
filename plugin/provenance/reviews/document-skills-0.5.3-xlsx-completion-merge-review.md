# CLEAN — Document Skills 0.5.3 XLSX LibreOffice Live-Workflow Review

Date: 2026-08-27

## Verdict

Status: `clean`

Approval claimed: `true`.

Canonical findings: **0 Blocker, 0 Major, 0 Minor**.

This is a fresh, non-author review of the committed candidate on
`fix/xlsx-libreoffice-live`. The candidate corrects real formula
recalculation by using a private XLSX-to-ODS-to-XLSX round trip, gives the
two-stage required path a bounded public-worker budget, and adds local Windows
mechanism coverage for fail-closed detection, recalculation, PDF rendering,
and legacy XLS conversion. Approval is limited to the exact base, candidate,
mapping, and evidence boundary below.

The combined fresh dist E2E, focused non-live coverage, and local real
LibreOffice mechanism evidence are sufficient to support the XLSX completion
claim within the shipped contract. They do not establish that the default
Windows LibreOffice provider is enabled: the production hard-quota backend
remains unavailable and therefore fails closed before probing or launching
LibreOffice.

## Reviewer identity

- Reviewer: `/root/implement_xlsx_dist_e2e/xlsx_static_review`
- Identity:
  `codex-reviewer/document-skills-0.5.3-xlsx-libreoffice-live/final-non-author-2026-08-27`
- Runtime: `codex`
- Role: `reviewer`
- Review branch: `fix/xlsx-libreoffice-live`
- Review worktree:
  `elftia-plugin-document-skills-wt-xlsx-libreoffice-fix`
- Scope: `all-release-artifacts`
- Identity assurance: `self-asserted`
- Identity limitations: This reviewer cannot cryptographically prove the
  backing model, service principal, or human operator. This local review does
  not establish remote CI status, a pull-request state, a push, a merge,
  Microsoft Excel behavior, a production hard-quota backend, or behavior
  outside the commands and supplied execution evidence recorded below.
- Report id: `document-skills-0.5.3-xlsx-completion-merge-review`

The reviewer did not author the functional changes or tests and did not edit
the provenance manifest or audit report. The only repository write made by
this review is this canonical report.

## Reviewed target

- Base:
  `origin/main@861e86c4cbede6c6b69a0f13509e6f8813476235`
- Candidate:
  `9464dd8ad0ff5f1bd72a971b1631828a34e9190f`
- Candidate tree: committed, with a clean worktree before this report rewrite
- Branch: `fix/xlsx-libreoffice-live`
- Functional/test diff: 5 paths, 382 insertions and 26 deletions
- Independently regenerated unbound provenance mapping SHA-256:
  `6168661add50d9e24d437ce4779be02598266a0cdd620c09bd7f39cfb90c059f`
- Unbound inventory: 569 module records, 167 data classifications,
  0 executable exclusions, 3 metadata exclusions, 0 review attestations

The reviewed five-path scope is exact:

1. `src/document_skills_core/providers/libreoffice/output.py`
2. `src/document_skills_core/providers/libreoffice/recalc.py`
3. `src/document_skills_core/public_cli/supervisor.py`
4. `tests/test_libreoffice_provider.py`
5. `tests/test_xlsx_provider_qa.py`

## Scope and behavior review

Scope Check: **PASS**

The implementation is coherent with the stated XLSX live-workflow gap:

- `ods` is admitted only as a private intermediate output and receives the
  same independent byte ceiling as XLSX;
- formula recalculation now performs two shell-free runner conversions in one
  operation-owned temporary root: screened XLSX to bounded private ODS, then
  that ODS to bounded private XLSX;
- each conversion independently enters the runner's required hard-quota
  contract, validates the stopped private tree, reads one bounded regular
  output, publishes it only inside the operation root, and cleans its quota
  session;
- the final XLSX is reopened and its formula text, result type, and cached
  values are projected through the existing formula-identity and copy-through
  acceptance boundary before a public artifact can be promoted;
- required `xlsx.create`, required `xlsx.edit`, and explicit
  `xlsx.recalculate` receive a 90-second public-worker ceiling, which bounds
  the two 30-second conversion stages plus detection and orchestration; and
- automatic recalculation keeps the existing short, degradable behavior
  instead of silently turning a best-effort request into a long required path.

No new macro, DDE, shell, external-data, or destination-publication bypass was
introduced. The fixed headless argv and forbidden-token validation still
govern both conversion stages. Existing formula preflight rejects active or
external formulas before the provider, and existing formula acceptance
rejects missing, added, changed, error-valued, or uncacheable formula records.

## Live-test seam and production boundary

The real Windows tests deliberately inject `_RecordingTestHardQuotaBackend`.
That seam records both quota activations and verifies final-tree postconditions
and cleanup while allowing the installed LibreOffice executable to exercise
the conversion mechanisms. It is test-only evidence; it is not an operating
system hard-quota implementation and must not be described as one.

The production default remains fail-closed. On Windows, without a reviewed
backend that guarantees aggregate bytes, entry count, private namespace, and
fail-closed activation, the default registry reports LibreOffice unavailable
before its version probe and does not launch it. Consequently:

- the candidate proves the recalculation/render/legacy mechanisms against a
  real local LibreOffice installation;
- it proves that two quota activations and cleanup occur at the runner seam;
- it does not claim that default Windows users can execute those enhanced
  LibreOffice operations today; and
- it does not weaken the hard-quota requirement to make the live tests pass.

This boundary is an intentional retained safety contract, not a candidate
finding.

## Coverage assessment

The changed execution paths are covered at the appropriate levels:

- **Private ODS round trip:** focused tests assert the exact `ods`, then
  `xlsx` call order, the intermediate suffix, both required time budgets, and
  cleanup of the enclosing operation directories.
- **Real recalculation:** a stale-cache workbook exercises chained and
  cross-sheet formulas; real LibreOffice returns `5`, `20`, and `21`, with
  exact formula identity and no formula error token.
- **Real render:** the registered `xlsx.render` operation produces a PDF that
  is reopened, reports both visual-render and provider-reopen gates, preserves
  the source, uses the PDF quota, and cleans the quota root.
- **Real legacy conversion:** a benign real XLS fixture is converted to XLSX,
  reopened through the core mapper, preserves source inputs, records the
  declared legacy semantic loss, uses the XLSX quota, and cleans the quota
  root.
- **Default fail-closed path:** the Windows registry test establishes that an
  installed standard-path LibreOffice remains unavailable before probing when
  no production hard-quota backend exists.
- **Packaged user path:** the fresh dist E2E covers the packaged XLSX public
  command surface and completed with five passing cases.

Together with the existing release feature-to-node mapping and the complete
non-real-provider suite, this closes the previously missing evidence that the
real tools perform the claimed local mechanisms. Coverage is intentionally
bounded: it is not an exhaustive workbook corpus, live Microsoft Excel test,
remote CI result, or production hard-quota deployment test.

## PATH non-pollution review

No PATH-polluting environment path was added. All managed child processes
inherit the existing fixed `DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=0` guard from
`ProcessRunner`, including the public worker and the direct test fixture
process. LibreOffice also receives a unique private `UserInstallation` URI.

The final local real-workflow run recorded identical before/after process PATH
SHA-256 values:
`d8c7bcd8200b9360dc0f8942b40715342914fd0913aac25cee8798ef74ce29c9`.
The HKCU user PATH was also unchanged at SHA-256
`7e8f32ba3d944443bb9b3681810e355e11c99c40abd920e04012679051d6c2d3`,
18 entries, 697 characters, and zero private-dotnet entries. No PATH contents
were emitted as review evidence.

## Provenance review

The official generator was rerun in read-only `--print-mapping-only` mode by
this reviewer and returned exactly:
`6168661add50d9e24d437ce4779be02598266a0cdd620c09bd7f39cfb90c059f`.

The release inventory shape is unchanged: the five existing release paths
above have new content hashes, while record keys, classifications, exclusion
scope, and the exact three self-referential metadata exclusions remain stable.
The unbound state contains no review attestation; binding this exact report is
the expected next provenance step.

## Findings

No canonical finding remains.

- Standards: 0 Blocker, 0 Major, 0 Minor
- Spec and coverage: 0 Blocker, 0 Major, 0 Minor

## Verification evidence

Execution evidence supplied by the lead and reviewed against the exact
candidate:

- The final local Windows group covering default fail-closed detection, real
  recalculation, real XLSX render, and real legacy XLS conversion produced
  **4 passed, 0 skipped in 69.6s**.
- The relevant non-live tests in `tests/test_libreoffice_provider.py` and
  `tests/test_xlsx_provider_qa.py` all passed after the final rebase.
- Fresh dist E2E produced **5 passed in 57.09s** with artifact inventory
  SHA-256
  `307cc9e16dd63b7a174c497546a4693f23bc43f63ef62e86077116be41f58558`.
- The process and HKCU PATH measurements remained byte-for-byte stable as
  recorded above; the HKCU scan retained zero private-dotnet entries.

Independent checks run by this reviewer without launching LibreOffice:

- Six focused tests passed: both hard-quota fail-closed cases, the short-auto
  versus normal-required budget path, the canonical fake-provider dispatch,
  the exact private ODS round trip, and the public-worker timeout matrix.
- Ruff passed on all five changed Python files.
- Python byte-compilation passed on all five changed Python files.
- A direct policy assertion confirmed `output_limit("ods") == MAX_XLSX_BYTES`.
- Official read-only provenance regeneration returned the exact mapping above.
- Strict UTF-8 decoding, no BOM or replacement characters, conflict-marker,
  secret/debug-residue scanning, temporary-residue scanning, and
  `git diff --check` passed for the reviewed scope and this report.

## Evidence boundary

No remote CI status was queried, awaited, investigated, or used as evidence.
No pull request, push, merge, production hard-quota backend, Microsoft Excel
run, or POSIX live LibreOffice run was performed by this review. The reviewer
did not rerun LibreOffice; the recorded live evidence came from the lead's
final serialized Windows run against this exact candidate. Approval does not
extend beyond the local state and commands recorded here.

## Attestation

I independently approve candidate
`9464dd8ad0ff5f1bd72a971b1631828a34e9190f` on
`fix/xlsx-libreoffice-live`, based on
`origin/main@861e86c4cbede6c6b69a0f13509e6f8813476235` and unbound mapping
`6168661add50d9e24d437ce4779be02598266a0cdd620c09bd7f39cfb90c059f`.
Within the evidence boundary above, the candidate is **CLEAN with 0 Blocker /
0 Major / 0 Minor**.
