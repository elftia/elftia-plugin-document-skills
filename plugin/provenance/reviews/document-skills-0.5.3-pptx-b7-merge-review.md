# Independent Re-Review: PPTX Ecosystem B7 — Fix Round 2

**Date:** 2026-08-27
**Mode:** dispatched, report-only, non-author re-review
**Reviewer identity:** Codex reviewer `/root/b7_release_review`
**Canonical attestation identity:** `codex-reviewer/document-skills-0.5.3-pptx-b7/repaired-release-review-2026-08-27`
**Reviewer role/runtime:** original independent non-author reviewer; runtime identity is self-asserted and is not signature-backed
**Reviewed base:** `origin/main@3bf90cbc7cbeea4afaa4fdba99dddca5b42aa374`
**Candidate form:** live uncommitted worktree delta on `feat/pptx-ecosystem-phase-bc-b7`; `HEAD` equals the reviewed base, with 22 tracked modified files and 28 untracked release files; worktree-local `.rasen/` excluded
**Fix round evidence:** `evidence/review-fix-round-1.md`, including its `Round 2 stale Strategy-3 repair` section; every disposition below was independently checked against the live worktree rather than accepted from the fixer report
**Exact unbound mapping SHA-256:** `2503d0510b97349b2b1cb81309a84e10e5c81e62f300236e54bae1bc1bc1806d`
**Canonical report path:** `evidence/review-report.md`
**Attestation status:** clean re-review evidence exists, but no provenance attestation was synthesized, rebound, or written by this reviewer

## Pre-Landing Review: No issues found

- **Standards axis:** CLEAN — the Round 2 Strategy-3 expectation now matches the canonical HTML → B7 → XLSX README ownership composition; the B1, M1, M2, and M3 repairs remain closed.
- **Spec axis:** CLEAN — Round 2 changes test/provenance bytes only; the B2, B3, and m1 production repairs remain closed and unchanged.
- **Scope drift:** none found in either fixer delta.
- **New findings introduced by Round 2:** none found.

## Round 2 delta disposition

### R2 — CLOSED — Stale Strategy-3 README ownership expectation

`plugin/tests/test_strategy3.py:585-651` now expects `README.md` to be owned by `Rasen html-to-editable-pptx + pptx-ecosystem-phase-bc-b7 + document-skills-core-xlsx + document-skills-xlsx-completion + document-skills-xlsx-advanced-authoring`. That is the exact composition produced by `html_pptx_data_profile("README.md")`, `reconstruction_b7_data_profile("README.md")`, and `xlsx_data_profile("README.md")` in HTML → B7 → XLSX order.

The regenerated README data record and checked-in `provenance/modules.json` both contain that exact requirement source. The Round 2 delta adds no production implementation, fixture, provider, transaction, or package-validation behavior. The prior binding was removed and the manifest is honestly unbound with zero review attestations.

## Finding dispositions

### B1 — CLOSED — Provider runtime inventory

`plugin/tests/test_runtime.py:96-113` now includes `ocr-vision` in the exact six-provider inventory and proves that its default detector is unavailable, its registry entry is non-callable, and its sole operation binding is `pptx.reconstruct.from-image`. A cache-free run of the complete `test_runtime.py` is green apart from the two existing platform-gated skips.

The B7 provenance profiles now include the B7-modified runtime/provenance tests. Independent regeneration and checked-in manifest comparison both resolve to the new mapping recorded above.

### B2 — CLOSED — Destination geometry and package-transform whole-slide refusal

`plugin/src/document_skills_core/formats/pptx/reconstruction_scene.py:25-40` rejects every raster-backed element whose source crop or independent destination geometry covers the full observation canvas. The deep gate in `plugin/src/document_skills_core/formats/pptx/reconstruction_validation.py:192-223,290-307` independently derives the expected projected transform, rejects a full-slide expected or actual package transform, and requires the emitted/package transforms to match it exactly.

The split source/destination adversarial regression at `plugin/tests/test_pptx_reconstruction_security.py:423-445` and package-transform tamper regression at `plugin/tests/test_pptx_reconstruction_validation.py:213-229` both pass.

### B3 — CLOSED — Exact receipt/scene/package crop binding

`plugin/src/document_skills_core/formats/pptx/reconstruction_validation.py:95-111,182-190,279-307` derives crop fractions from the receipt `source_region` and canvas, compares the normalized scene crop with fixed representation tolerance, derives the emitter's exact `round(fraction * 100000)` OOXML integers, and requires every package `<a:srcRect>` to equal those integers.

The valid-but-wrong `l=12345` tamper regression at `plugin/tests/test_pptx_reconstruction_validation.py:195-210` passes, while the untampered cropped-picture gate remains green.

### M1 — CLOSED — Closed-enum type checks

`plugin/src/document_skills_core/formats/pptx/reconstruction_contracts.py:33-39` proves exact `str` type before `audit_asset_policy` membership. `plugin/src/document_skills_core/formats/pptx/reconstruction_models.py:176-179,249-256` does the same for provider `kind` and `style.text_align`.

Public list/object/null/bool policy cases remain canonical `DS_REQUEST_INVALID`; provider list/object enum cases are contained as canonical `DS_PROVIDER_FAILED`. The complete parameterized regressions pass without raw `TypeError` escape.

### M2 — CLOSED — One-file-identity bounded raster read

`plugin/src/document_skills_core/formats/pptx/reconstruction_models.py:280-321` opens one regular-file handle, binds pathname and handle identities, admits only an initially bounded non-empty size, reads exactly at most `MAX_RASTER_BYTES + 1`, then verifies handle identity/size and post-read pathname identity/size before returning bytes. Growth can no longer cause an unbounded convenience read, and replacement cannot redirect the accepted identity.

The controlled growth regression at `plugin/tests/test_pptx_reconstruction_security.py:327-369` proves the requested read size is exactly `MAX_RASTER_BYTES + 1`; the pathname-identity-change regression at `:372-398` proves drift is rejected. Both pass.

### M3 — CLOSED — Pre-serialization bounded validation

`plugin/src/document_skills_core/formats/pptx/reconstruction_models.py:112-164` now validates the exact top-level shape, canvas, bounded element list, every element/style/scalar field, unique identities/order, and aggregate text before canonical serialization. `json.dumps()` receives only the normalized bounded envelope and is then used to enforce the final byte ceiling.

`plugin/tests/test_pptx_reconstruction_security.py:298-325` replaces `json.dumps()` with a forbidden sentinel and proves oversized top-level, 513-element, and 3 MB nested-scalar inputs fail before serialization. All three cases pass.

### m1 — CLOSED — Real supervisor hang and result-budget E2E

`plugin/tests/test_pptx_reconstruction_public.py:252-302` exercises the real `PublicCommandSupervisor`, `ProcessRunner`, private command/result files, and static worker process. The hang case sleeps in the worker and is terminated by the configured 0.25-second reconstruction budget; the over-budget case writes a result above 1 MiB and is refused by the supervisor.

Both cases return bounded canonical errors (`DS_PROCESS_TIMEOUT`/`timeout` and `DS_PROVIDER_FAILED`/`overflow`), preserve the caller source and prior destination bytes, and remove the private invocation tree. Both pass.

## Independent verification

Environment used for every Python test/provenance command:

```text
PYTHONDONTWRITEBYTECODE=1
PYTHONUTF8=1
DOCUMENT_SKILLS_PROVIDER_PROFILE=core-only
DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=0
```

### Round 2 delta and related provenance tests

Run from `plugin/`:

```powershell
uv run --project . --frozen pytest -p no:cacheprovider -q -ra `
  tests/test_strategy3.py::test_xlsx_data_provenance_respects_change_boundaries `
  tests/test_strategy3.py::test_xlsx_provenance_profiles_are_exact_and_cover_the_current_inventory `
  tests/test_strategy3.py::test_shared_xlsx_nuget_data_provenance_is_exact_and_composed `
  tests/test_html_provenance.py::test_reconstruction_b7_profiles_match_exact_release_inventory `
  tests/test_html_provenance.py::test_html_readme_uses_the_complete_xlsx_profile `
  tests/test_html_provenance.py::test_html_pptx_release_records_use_truthful_requirement_and_tests `
  tests/test_strategy2.py::test_current_review_is_the_only_hashless_review_metadata `
  tests/test_strategy2.py::test_b7_review_is_exact_self_referential_metadata_and_mapping_stays_stable `
  tests/test_strategy2.py::test_historical_reviews_are_hash_pinned_data_not_metadata
```

Result: **19 selected case invocations passed; 0 failed**, exit code 0. The directly repaired atomic Strategy-3 boundary test also passed alone before this related run.

Two broader reviewer attempts — complete `tests/test_strategy3.py`, and a combined Strategy-3/HTML-provenance/Strategy-2 run — exceeded the 244-second command-capture ceiling. Neither emitted a retained assertion failure; neither is claimed as a pass or failure. The fixer report separately records 84 Strategy-3 and 109 HTML-provenance/Strategy-2 passes, but those remain fixer evidence rather than independent-reviewer pass claims.

### Round 1 seven-finding targeted regression run

```powershell
uv run --project plugin --frozen pytest -p no:cacheprovider -q `
  plugin/tests/test_runtime.py `
  plugin/tests/test_pptx_reconstruction_contracts.py::test_parse_reconstruction_rejects_implicit_or_open_policy `
  plugin/tests/test_pptx_reconstruction_security.py::test_invalid_provider_observation_fails_without_artifact_changes `
  plugin/tests/test_pptx_reconstruction_security.py::test_invalid_provider_values_fail_before_canonical_serialization `
  plugin/tests/test_pptx_reconstruction_security.py::test_concurrent_raster_growth_is_bounded_during_the_read `
  plugin/tests/test_pptx_reconstruction_security.py::test_raster_path_identity_change_is_rejected `
  plugin/tests/test_pptx_reconstruction_security.py::test_full_slide_raster_geometry_is_refused_even_with_a_small_source_crop `
  plugin/tests/test_pptx_reconstruction_validation.py::test_reconstruction_gate_rejects_valid_but_wrong_package_crop `
  plugin/tests/test_pptx_reconstruction_validation.py::test_reconstruction_gate_rejects_full_slide_package_transform `
  plugin/tests/test_pptx_reconstruction_public.py::test_reconstruction_supervisor_enforces_real_worker_limits_end_to_end
```

Result: **pass**, exit code 0; two existing platform-gated runtime cases skipped.

### Round 1 focused B7 matrix

```powershell
$tests = @(Get-ChildItem -LiteralPath tests -Filter 'test_pptx_reconstruction_*.py' |
  ForEach-Object { $_.FullName })
$tests += (Get-Item -LiteralPath 'tests/test_runtime.py').FullName
$tests += (Get-Item -LiteralPath 'tests/test_html_provenance.py').FullName
uv run --project . --frozen pytest -p no:cacheprovider $tests -q -ra
```

Result: **148 collected; 146 passed; 2 skipped; 0 failed**. The skips are the existing POSIX-symlink identity cases at `tests/test_runtime.py:353,370` on Windows.

Both Round 1 runs above are preserved historical reviewer evidence. They were not repeated because Round 2 changes only one exact provenance expectation plus the deterministically regenerated unbound provenance files; the selected Round 2 matrix covers that changed chain.

### Provenance exactness

```powershell
$env:PYTHONPATH='.'
uv run --project . --frozen python -m tools.regenerate_provenance `
  --project-root . --print-mapping-only
```

Result: `2503d0510b97349b2b1cb81309a84e10e5c81e62f300236e54bae1bc1bc1806d`.

An independent in-memory `regenerate(root)` comparison found the generated manifest exactly equal to `provenance/modules.json`. A separate `mapping_digest()` over the checked-in records returned the same digest: 631 module records, 211 data records, 0 executable exclusions, 3 metadata exclusions, and 0 review attestations.

The independently generated runtime-source allowlist exactly equals `provenance/runtime-source-allowlist.json` with 399 Python and 10 Node sources. The checked-in audit report has every inventory, execution-boundary, fixture, clean-room, command, public-skill, manifest, and SBOM gate passing. Its sole error is the intentionally unbound `Independent review attestation is missing`; SBOM SHA-256 remains `bca9da6a21d022c2bcd367e3249e54928646304a2800828b401ef0635aad7394`. `git diff --check` passes.

## Review limitations and handoff boundary

- No production OCR/vision adapter exists to exercise; unavailable-by-default truth and the injected deterministic/provider-worker seams were reviewed instead.
- The complete Strategy-3 and combined provenance suites timed out under this reviewer's command-capture ceiling; only the 19-case related Round 2 matrix and the preserved Round 1 runs are claimed as reviewer passes.
- No PowerPoint, LibreOffice, remote CI, commit, push, PR, merge, or provenance-binding claim is made in this report.
- The candidate remains a live uncommitted worktree delta, so the LEAD must perform committed-tree freshness verification after binding and before delivery.
- The reviewer identity is runtime/self-asserted rather than cryptographically signed. The LEAD remains responsible for deciding whether and how to bind this clean report as the release attestation.

REVIEW VERDICT: CLEAN — Blocker:0 Major:0 Minor:0 Trivial:0

---

## Superseded Round-0 Review

The original blocked review is preserved below as historical evidence. Its seven findings are superseded by the closed dispositions above.

# Independent Pre-Landing Review: PPTX Ecosystem B7

**Date:** 2026-08-27
**Mode:** dispatched, report-only, non-author review
**Reviewer identity:** Codex reviewer `/root/b7_release_review`
**Reviewer role/runtime:** independent non-author reviewer; runtime identity is self-asserted and is not signature-backed
**Reviewed base:** `origin/main@3bf90cbc7cbeea4afaa4fdba99dddca5b42aa374`
**Candidate form:** live uncommitted worktree delta on `feat/pptx-ecosystem-phase-bc-b7`; `HEAD` equals the reviewed base, with 19 tracked modified files and 28 untracked release files; worktree-local `.rasen/` excluded
**Exact unbound mapping SHA-256:** `dc15cebb49a79d46d150123d3144f8e4750532d0bc2debe7f70d5286c410aa6c`
**Canonical report path:** `evidence/review-report.md`
**Attestation status:** blocked; this report is not a clean release attestation and must not be bound into provenance

## Scope check

**Scope Check: REQUIREMENTS MISSING**

- **Intent:** add bounded provider-gated raster-to-layered-PPTX reconstruction, exact policies, typed observations, crop-only fallback, truthful provider absence, transactional audit assets, fixtures, docs, and release provenance.
- **Delivered:** the candidate contains that complete surface and its deterministic fixtures/provenance, but the whole-slide and crop-integrity gates have bypasses, one existing provider-enum regression test fails, and resource ceilings are not enforced before the relevant allocations.
- **Scope drift:** none found. The broad fixture-registry dependency rewrite is a deterministic consequence of adding the reconstruction fixture generator.

## Pre-Landing Review: 7 issues

### Standards axis

#### B1 — Blocker — ASK — Provider enum addition leaves the existing runtime gate red

`plugin/src/document_skills_core/core/capabilities/catalog.py:13` and `plugin/src/document_skills_core/providers/defaults.py:234` add/register `ocr-vision`, but `plugin/tests/test_runtime.py:96-104` still requires the old five-provider set. An independent cache-free run of the full `test_runtime.py` produced one failure at that exact assertion. This is a failing gate and an enum/value-completeness miss; the verification report's scoped PPTX suite did not expose it.

**Required repair:** revise the runtime test's now-stale “optional descriptors never create callable operations” contract to include the unavailable-by-default `ocr-vision` provider and explicitly assert its sole operation binding and unavailable truth. Because `test_runtime.py` will then become a B7-modified release module, update the exact B7 provenance profile and regenerate the unbound mapping.

#### M1 — Major — AUTO-FIX — Unhashable policy values bypass the typed request contract

`plugin/src/document_skills_core/formats/pptx/reconstruction_contracts.py:33-34` performs set membership before proving `audit_asset_policy` is a string. A JSON-valid request containing `"audit_asset_policy": []` raises raw `TypeError` instead of `DS_REQUEST_INVALID`; the same pattern appears for provider-controlled enum values at `reconstruction_models.py:199-201` and `:267-268`. The outer provider boundary contains provider-origin exceptions, but a caller-owned invalid policy is misclassified as a provider crash rather than rejected by the exact public contract.

**Required repair:** type-check each closed enum before membership, retain canonical `DocumentSkillsError` translation, and add list/object/null/bool negative cases for the public policy plus unhashable provider values.

#### M2 — Major — ASK — The raster byte ceiling is checked before an unbounded path read, not enforced by the read

`plugin/src/document_skills_core/formats/pptx/reconstruction_models.py:71-80` stats the path and then calls `Path.read_bytes()`. A concurrent replace or append after the stat can make that call allocate/read far beyond `MAX_RASTER_BYTES`; only after the allocation does `len(payload) != size` reject it. This is a TOCTOU/resource-boundary defect in the untrusted local-input path.

**Required repair:** open one regular-file identity, read at most `MAX_RASTER_BYTES + 1`, verify EOF and the bound identity/size, and reject growth/replacement without an unbounded allocation. Add a controlled concurrent-growth/replacement regression test.

#### M3 — Major — ASK — The observation-envelope ceiling is measured only after full serialization

`plugin/src/document_skills_core/formats/pptx/reconstruction_models.py:131-146` fully `json.dumps()` the adapter result before the top-level shape check at `:147`, the element-count check at `:159`, and per-field text/style bounds. A configured hostile or defective adapter can therefore force a second arbitrarily large in-memory representation before `MAX_OBSERVATION_BYTES` is considered. The supervisor's output-file cap does not bound this in-worker allocation.

**Required repair:** reject top-level shape, element count, and bounded scalar/container fields before canonical serialization, or use a genuinely bounded encoder; add a resource test proving oversized nested/scalar provider values do not require full serialization.

**Standards axis result:** 4 findings; worst = Blocker (failing enum-completeness runtime gate).

### Spec axis

#### B2 — Blocker — ASK — A cropped raster can still be emitted as a full-slide picture

The whole-slide guard in `plugin/src/document_skills_core/formats/pptx/reconstruction_scene.py:28-30` checks only the untrusted `source_region`. The emitted picture extent instead comes from untrusted `geometry` via `:75` and `:130,162-164`. An independent adversarial probe set a low-confidence element's `geometry` to the entire 400x225 canvas while keeping a smaller `source_region`; projection produced a 1920x1080 raster picture and `reconstruction-layer-integrity` returned `pass` with `whole_slide_raster: false`.

This violates the spec's “raster element covering the full canvas” refusal and the documented prohibition on a full-slide source image beneath editable objects.

**Required repair:** reject raster-backed elements whose destination/projected geometry covers the slide, independently of source crop, and have the deep package gate verify the actual picture transform. Add the split-geometry/source-region negative regression.

#### B3 — Blocker — ASK — Deep validation accepts a wrong but syntactically bounded package crop

`plugin/src/document_skills_core/formats/pptx/reconstruction_validation.py:142-152` checks only that the scene crop is finite/non-empty, while `:170-179` checks only that package `<a:srcRect>` values are bounded and nonzero. It never binds the package crop to the receipt's `source_region` or the scene/emission crop. In an independent probe, changing the emitted left crop from `57500` to `12345` left receipt/scene evidence unchanged and the required gate still returned `pass`.

This fails the required crop-correctness and receipt/package integrity guarantee and permits silent reconstruction corruption to pass mandatory validation.

**Required repair:** derive the expected integer OOXML crop from the validated source region/raster dimensions (with the emitter's documented rounding) and compare every package picture to its receipt/scene record. Add a valid-but-wrong crop tamper test.

#### m1 — Minor — ASK — Public timeout/result-budget enforcement is configured but not exercised end to end

`plugin/tests/test_pptx_reconstruction_public.py:232-248` asserts only the `(60.0, 1_048_576)` tuple. Its timeout adapter voluntarily raises `DS_PROCESS_TIMEOUT`; no B7 test hangs the adapter so the supervisor must terminate it, and no test makes the worker exceed the result budget. These are named provider failure/resource scenarios in the change spec.

**Required repair:** reuse the public-worker harness with a hanging adapter and an over-budget result, asserting bounded canonical failure, source/prior-destination preservation, and private-tree cleanup.

**Spec axis result:** 3 findings; worst = Blocker (whole-slide bypass and unbound package crop).

## Coverage map

```text
CODE PATH COVERAGE
==================
[+] request contract
    ├── [★★★ TESTED] exact policies, suffixes, thresholds, metadata, distinct paths
    └── [GAP]        unhashable closed-enum values return canonical invalid_request
[+] raster screening
    ├── [★★★ TESTED] PNG/JPEG magic, suffix, bytes, dimensions, pixels
    └── [GAP]        concurrent growth/replacement is bounded during the read
[+] observation validation
    ├── [★★★ TESTED] ids/order, canvas, geometry, confidence, kinds, text, count
    └── [GAP]        pre-serialization memory ceiling and unhashable enum values
[+] scene projection and coverage
    ├── [★★★ TESTED] editable layers, isolated fallback, overlap-safe ratios
    └── [GAP]        full-slide destination geometry with a cropped source region
[+] mandatory deep validation
    ├── [★★ TESTED]  inventory, visibility, crop presence/range, hidden pictures
    └── [GAP]        package crop equals the receipt/source-region crop
[+] transaction and audit lifecycle
    └── [★★★ TESTED] retain/discard, occupied audit, promotion race, cleanup

USER FLOW COVERAGE
==================
[+] normal installation
    └── [★★★ TESTED] provider_unavailable, no single-image deck, no output
[+] injected deterministic provider
    ├── [★★★ TESTED] B-REC-01 editable receipt/audit and B-REC-02 mixed fallback
    ├── [★★ TESTED]  adapter crash and self-reported timeout isolation
    └── [GAP] [→E2E] supervisor kills a hung adapter and rejects over-budget output
[+] release truth
    └── [★★★ TESTED] fixtures, docs, exact provenance mapping, SBOM, reproducibility

UNRESOLVED GAPS: 6 edge paths across 8 reviewed path families
```

## Provenance, fixture, and release findings

- Independently regenerated the unbound mapping in memory: `dc15cebb49a79d46d150123d3144f8e4750532d0bc2debe7f70d5286c410aa6c`.
- Recomputed the checked-in mapping digest independently from `modules.json`; it matches the same digest.
- Generated manifest equals checked-in `modules.json` exactly: 631 module records, 211 data records, 0 executable exclusions, 3 metadata exclusions, and 0 review attestations.
- Fresh audit results: all inventory, execution-boundary, fixture, clean-room, command, public-skill, manifest, and SBOM checks pass; the sole audit error is the intentionally missing independent review attestation.
- SBOM parity passes at SHA-256 `bca9da6a21d022c2bcd367e3249e54928646304a2800828b401ef0635aad7394`; no component name contains OCR or vision, so no OCR dependency was introduced.
- Both untracked PNG fixtures were visually inspected; all six adjacent observation/manifest JSON files were read, and generator/registry/hash parity is covered by the passing audit and exact mapping comparison.
- The in-repository B7 review artifact remains honestly `PENDING`; it was not modified or treated as approval.

## Review limitations

- No production OCR/vision adapter exists to exercise; unavailable-by-default truth was reviewed instead.
- No PowerPoint, LibreOffice, remote CI, push, PR, or merge claim is made.
- No PR exists for the live uncommitted branch, so there were no Greptile comments to triage.
- The reviewed identity is self-asserted, not cryptographically signed.
- Because the candidate is blocked, no clean provenance attestation fields are issued and the mapping must be regenerated after repairs.

HISTORICAL ROUND-0 REVIEW VERDICT: BLOCKED — Blocker:3 Major:3 Minor:1 Trivial:0
