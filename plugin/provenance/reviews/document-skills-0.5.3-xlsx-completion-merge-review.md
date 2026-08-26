# CLEAN — Document Skills 0.5.3 .NET Helper Build Isolation Review

Date: 2026-08-27

## Verdict

Status: `clean`

Approval claimed: `true`.

Canonical findings: **0 Blocker, 0 Major, 0 Minor**.

This is a fresh Tier A review of the uncommitted candidate on
`fix/dotnet-helper-build-isolation`. The candidate redirects the locked
OpenXML helper restore/build graph out of the checked-in helper source tree
and executes the private DLL directly. Approval is limited to the exact base,
branch state, and unbound provenance mapping below.

## Reviewer identity

- Reviewer: `Codex collaboration agent /root/b5_review_round2`
- Identity:
  `codex-reviewer/document-skills-0.5.3-dotnet-helper-build-isolation/tier-a-review-2026-08-27`
- Runtime: `codex`
- Role: `reviewer`
- Review branch: `fix/dotnet-helper-build-isolation`
- Review worktree:
  `elftia-plugin-document-skills-wt-dotnet-helper-isolation`
- Scope: `all-release-artifacts`
- Identity assurance: `self-asserted`
- Identity limitations: This reviewer cannot cryptographically prove the
  backing model, service principal, or human operator, and this local review
  does not establish remote CI status, a pull-request state, a commit, a push,
  a merge, POSIX runtime behavior, or behavior beyond the commands recorded
  below.
- Report id: `document-skills-0.5.3-xlsx-completion-merge-review`

The reviewer did not author the functional changes, tests, regenerated
provenance manifest, or unbound audit report.

## Reviewed target

- Base: `origin/main@dff72d3b7334b923c008aa9b4c5f6031e9eec85e`
- HEAD: `dff72d3b7334b923c008aa9b4c5f6031e9eec85e`
- Branch: `fix/dotnet-helper-build-isolation`
- Candidate form: 7 tracked, uncommitted changed paths above the exact base;
  no functional commit was created by this review
- Candidate diff before this report: 7 paths, 1,679 insertions and 1,550
  deletions
- Functional/test diff: 5 paths, 187 insertions and 38 deletions
- Provenance/audit diff: 2 paths, 1,492 insertions and 1,512 deletions
- Independently regenerated unbound provenance mapping SHA-256:
  `4261788a90714af983f8c7fb86cc352a18c30b2b5e25bc46e2b66d79c6c0dbb5`
- Unbound inventory: 569 module records, 167 data classifications,
  0 executable exclusions, 3 metadata exclusions, 0 review attestations

The only writes made by this review are this canonical report and the required
external Rasen evidence copy. No functional code, generated manifest,
attestation, commit, push, pull request, or merge was changed.

## Scope check

Scope Check: **PASS**

The implementation:

- exposes one validated runner-owned private environment directory;
- places `BaseOutputPath`, `BaseIntermediateOutputPath`, and
  `MSBuildProjectExtensionsPath` beneath that runner's private
  `DOTNET_CLI_HOME`;
- restores in locked mode, builds with `--no-restore`, probes with
  `dotnet exec <private OpenXmlHelper.dll>`, and uses the same private DLL for
  real provider operations;
- preserves the legacy argv path only for injected/fake runners;
- shares one `ProcessPolicy` and `ProcessRunner` for the normal production
  detector/runner pair; and
- adds a real regression test that requires the helper source tree to have no
  `bin` or `obj` before and after detection.

The normal default registry path was traced through
`build_default_registry()` and `_optional_detector()`. With the normal profile,
the optional detector is `None`, so detector and operation runner share the
same process runner, private build location, and executable policy. With the
`core-only` profile, the injected detector is explicitly unavailable and no
operation is attempted.

## Safety and behavior review

The build-output properties are passed as shell-free argv elements and remain
beneath a unique, project-contained operation root. Private directory creation
rejects unsupported names, escapes, and symlinks; cleanup remains restricted
to managed `operation-*` roots. The .NET child environment still isolates
NuGet and Windows application-data roots and forces
`DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=0`.

The two focused real detection tests passed and left both helper `bin` and
`obj` absent. Three additional real provider tests exercised the private DLL:
the comprehensive public-operation case and OpenXML validator case passed.
The remaining comment-thread test reached the private helper for add/reply but
failed at an unrelated, pre-existing command allowlist omission described
below. The source helper tree remained clean after all real runs.

## Provenance review

Independent in-memory regeneration was semantically identical to the checked
`provenance/modules.json` and returned the exact mapping above. The manifest
contains 569 modules, 167 data classifications, zero executable exclusions,
three metadata exclusions, and zero review attestations.

After excluding reviewer and review-evidence binding fields, the record key
sets match the base and exactly five semantic record changes remain, all
SHA-256-only updates for the five functional/test paths:

1. `src/document_skills_core/core/process/runner.py`
2. `src/document_skills_core/providers/dotnet/constants.py`
3. `src/document_skills_core/providers/dotnet/detector.py`
4. `src/document_skills_core/providers/dotnet/runner.py`
5. `tests/test_docx_dotnet_real.py`

The unbound audit exits `2` with exactly one error:
`Independent review attestation is missing`. Every other audit section passes.
That is the expected pre-binding fixed point and is not a candidate finding.

## Findings

No canonical finding remains.

- Standards: 0 Blocker, 0 Major, 0 Minor
- Spec and coverage: 0 Blocker, 0 Major, 0 Minor

## Accepted known baseline observations

These observations are not introduced by the reviewed diff and do not count
as candidate findings:

1. `tests/test_structure.py::test_release_version_is_one_source_value_across_runtime_manifests`
   fails because `OpenXmlHelper.csproj` has no `<Version>`. The focused result
   is `{None, '0.5.3'} != {'0.5.3'}`; the csproj is byte-for-byte unchanged by
   this branch (`git diff` exit `0`) and the base has the same missing value.
2. `test_real_dotnet_profile_round_trips_comment_threads_and_resolution`
   fails reproducibly with `DS_PROVIDER_FAILED: Unknown dotnet helper
   subcommand: --comments-resolve`. The accepted-subcommand set and the
   comments implementation are unchanged by this branch; the omission exists
   on `origin/main`. The other two real tests in that run passed.
3. One-sided injection of a real detector with an implicit real runner returns
   the pre-existing executable-policy identity error because the factory gives
   those components separate policies. `service.py` has the identical blob
   `61b441920ce5072ba62521c5e0fff98848d4a840` in the candidate and base. The
   normal production path shares both policy and runner and passed real tests.

## Independent verification evidence

- `uv run --frozen python -B -m pytest tests/test_dotnet_provider.py`
  produced **67 passed in 2.37s**.
- The process PATH SHA-256 was
  `67ba66dcd785956a52236b3bc91e5b473bc6647b4ae055431efd36bf003177ba`
  before and after that suite; helper `bin`/`obj` were absent afterward.
- With `ELFTIA_REQUIRE_DOTNET_PROFILE=1`, the two focused detection tests
  (`test_real_dotnet_detection_does_not_mutate_user_path` and
  `test_real_dotnet_detection_keeps_helper_source_clean`) produced
  **2 passed in 43.54s** and left helper `bin`/`obj` absent.
- The other three real DOCX/OpenXML tests produced **2 passed, 1 failed in
  309.16s**. Direct replay of the failed request returned exit `2` and the
  exact pre-existing `--comments-resolve` allowlist error above. Helper
  `bin`/`obj` remained absent.
- The focused release-version test produced **1 failed in 0.40s** with the
  unchanged baseline `<Version>` omission above.
- `uv run --frozen python -B -m tools.regenerate_provenance --project-root .
  --print-mapping-only` returned the exact reviewed mapping.
- Independent in-memory regeneration reported `semantic_equal=True` with
  569 modules, 167 data records, 3 metadata exclusions, and 0 attestations.
- Independent base/current record comparison reported equal key sets and only
  the five SHA-256 changes listed above.
- `uv run --frozen python -B -m tools.audit --project-root .` returned audit
  exit `2` with exactly the expected missing-attestation error; the remaining
  audit checks passed.
- `ruff check` on all five changed Python files passed. Strict UTF-8 decoding,
  no BOM, no replacement/mojibake markers, JSON parsing, and
  `git diff --check` all passed for the changed text and JSON files.
- Tests explicitly set `PYTHONDONTWRITEBYTECODE=1` and
  `DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=0`; real-profile tests also set
  `ELFTIA_REQUIRE_DOTNET_PROFILE=1`.

## Evidence boundary

No remote CI status was queried, awaited, investigated, or used. No POSIX real
.NET run, concurrency stress test, pull-request check, commit, push, or merge
was performed. The review did execute the local Windows .NET/OpenXML provider,
locked NuGet restore/build path, real public DOCX operations, and registry PATH
preservation check. Approval does not extend beyond this recorded local state.

## Attestation

I independently approve the uncommitted candidate on
`fix/dotnet-helper-build-isolation` at base/HEAD
`dff72d3b7334b923c008aa9b4c5f6031e9eec85e` and unbound mapping
`4261788a90714af983f8c7fb86cc352a18c30b2b5e25bc46e2b66d79c6c0dbb5`.
Within the evidence boundary above, the candidate is **CLEAN with 0 Blocker /
0 Major / 0 Minor**.
