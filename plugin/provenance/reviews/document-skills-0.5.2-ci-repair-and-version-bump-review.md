# Document Skills 0.5.2 Codex CLI provenance review

Identity: codex-reviewer/document-skills-ci-repair-and-version-bump/gpt5-codex-provenance-2026-08-13

- Runtime: OpenAI Codex CLI 0.146.0
- Identity assurance: self-asserted
- Scope: all-release-artifacts
- Reviewed mapping digest: 12501bf5135bf0aa9f16bd7dbb41312a74cf642c6dbd73c30dda97e571bff1e3
- Status: objections
- Approval claimed: no

## How this review was conducted

This review was commissioned because the 0.5.1 attestation had been rebound on 2026-08-13 to a
mapping the reviewer never saw, and that gap was closed by disclosure rather than by review. The
0.5.2 release bumps the version and therefore changes the mapping again, so an actual independent
review was performed instead of a second disclosure.

It ran in two passes, both by OpenAI Codex CLI 0.146.0 driving its own shell against a full
checkout, on a different vendor and model family from the 0.5.1 Claude reviewer.

**Pass 1 — delta scope.** Returned `objections` with two findings, both about the truthfulness of
the checked-in narrative rather than the behaviour of the code:

- The new non-core assertion in `tests/test_pptx_public.py` was described as validating provider
  truthfulness, but `reports.py` always supplies a constant non-empty reason when an operation is
  unavailable, so the assertion's failure branch is unreachable for current production output. It
  is a regression guard, not an exercised negative path.
- The comment claimed the old assertion failed on "all six CI legs". It did not.

Both were corrected in the working tree before pass 2, and the corrected per-leg account was
independently verified against the archived CI logs by both the maintainer and the reviewer.
Pass 1 is reproduced in the appendix.

**Pass 2 — `all-release-artifacts` scope.** Verified the corrections and covered the mapping, the
delta and the audit tooling. Its verdict is the verdict of this attestation. It found two further
objections, both pre-existing defects in the provenance model rather than regressions introduced
by this release. They are recorded here, unresolved, and are the reason this attestation carries
`Status: objections` rather than `clean`.

## Review result

Two material objections remain. The rewritten comment resolves prior objections (A) and (E): it now limits the repaired failure to the two Ubuntu legs and explicitly calls the new assertion an unreachable regression guard, not provider-truthfulness validation (`tests/test_pptx_public.py:118`, `tests/test_pptx_public.py:125`). Production always supplies the constant failure reason (`src/document_skills_core/core/capabilities/reports.py:69`), while the HTML operation is bound solely to the optional provider (`tests/test_runtime.py:89`, `src/document_skills_core/providers/html_browser/provider.py:23`). I independently checked run 31529508680 logs and confirmed the supplied per-OS counts; runs 31691425158 and 31691432513 had zero steps, so I did not count them as executed verification.

## Scope actually examined

I exhaustively reconciled all 344 computed release paths against `modules.json`: every path appeared exactly once as 262 modules, 67 data records, or 15 metadata exclusions, matching the checked-in counts (`provenance/audit-report.json:26`, `provenance/audit-report.json:36`). I recomputed all 329 non-metadata hashes. Six reflect the expected unbound working-tree delta; the other 323 matched. The current complete audit therefore fails on hash drift and was not counted as passing (`tools/audit_provenance.py:78`).

I reviewed every hunk in the eight-file non-provenance delta from `7792a6c`. The version changes are consistent, and the added allowlist/test changes are syntactically valid. Twelve focused tests passed, including the rewritten PPTX test and provenance rebound tests. I did not run the approximately 25-minute `npm run verify`, so no full-suite pass is claimed.

For classification, I examined all 67 data paths and all 15 metadata paths by name, classification, hash treatment, and executable-marker scan, then manually read 12 representative data files selected across workflows, manifests, policy, locks/allowlists, and HTML fixtures. I exhaustively checked all 27 fixture records for location, manifest membership, SHA-256, redistribution permission, and recipe presence; I did not regenerate every fixture. They are genuine generated fixtures (`tests/fixtures/manifest.json:2`, `tests/fixtures/manifest.json:285`).

For originality, I spot-checked 23 of 262 modules, stratified across consumer validation, Node runtime, four entrypoints, core process/I/O, all document formats, providers, public worker code, changed tests, and provenance tools. I also scanned the source tree for third-party attribution markers. I found no contrary evidence to `original`: observed third-party use was through package imports or references, not vendored source (`runtime/node/docx_template.mjs:12`, `src/document_skills_core/providers/dotnet/helper/OpenXmlHelper.csproj:19`). Thus empty `adopted_sources` and `executable_exclusions` are credible for that sample, not exhaustively proven authorship (`provenance/modules.json:2`, `provenance/modules.json:783`).

## Findings

1. Executable CI instructions escape module-level classification. `.github/workflows/core-docx.yml` contains executable `uses:` and `run:` steps (`.github/workflows/core-docx.yml:22`, `.github/workflows/core-docx.yml:40`) but is labelled “non-execution” `reviewed-data` (`provenance/modules.json:15`). The classifier recognizes executable suffixes, execution directories, shebangs, binary magic, modes, extensionless files, and opaque bytes, but not workflow YAML (`tools/release_inventory.py:102`). The execution audit then inspects only artifacts already marked risky and only selected source suffixes (`tools/audit_execution.py:47`, `tools/audit_execution.py:113`). Because the release builder copies the entire computed inventory, the workflow ships (`scripts/artifact.mjs:30`, `scripts/artifact.mjs:48`). This is a concrete executable-content escape.

   The embedded script in `html-adversarial-deck.html` is different: it is explicitly generated adversarial fixture material (`tests/fixtures/manifest.json:380`), and browser execution disables JavaScript and service workers (`runtime/node/html_browser_policy.mjs:14`). I do not object to its `fixture-data` classification.

2. The hashless metadata allowlist is not minimal and permits unreviewed release bytes. The mapping digest includes only metadata path and classification, never its bytes (`tools/provenance_records.py:24`). Validation accepts 15 exact paths without checking their hashes (`tools/provenance_records.py:87`), including twelve historical review reports beyond the manifest, audit report, and currently bound review report. Only the current attestation report receives a separate hash check (`tools/audit_provenance.py:226`). This contradicts the documented three-path circularity boundary (`PROVENANCE.md:11`).

   In a controlled copy, I appended bytes to `core-docx-review-cycle-round-1.md`; the mapping digest remained identical and `audit_provenance` passed before and after. The new delta extends this accumulating exemption to the 0.5.2 report (`tools/regenerate_provenance.py:207`, `tools/provenance_records.py:102`). Historical reports should instead be ordinary hash-bound data once they are no longer the current self-referential attestation.

## Verdict

objections

- Reclassify executable workflow configuration for module-level scrutiny.
- Reduce hashless metadata to the genuinely circular files and hash-bind historical review reports.

## Appendix — pass 1 (delta scope, superseded by pass 2)

## Review result

The functional repair and version bump are sound, but the release evidence is not clean. The new assertion’s advertised negative path is unreachable in the current producer, and the “all six CI legs” account is contradicted by the archived workflow results.

Targeted PPTX, provider-registration, allowlist, JSON, UTF-8, and diff checks passed. Full `npm run verify` did not complete within 15 minutes, so it is not counted as a pass.

## Findings

### A. Repaired assertion

Yes, `assert item["available"] or item["reason"]` fails for a synthetic or regressed report containing `available: false` with an empty reason (`plugin/tests/test_pptx_public.py:122-125`). However, the actual code exercised cannot currently emit that state: every unavailable operation receives the constant non-empty reason, while every available operation receives `None` (`plugin/src/document_skills_core/core/capabilities/reports.py:69-76`). Consequently, the non-core assertion always passes for current production output. It is a regression guard over `reports.py`, not an exercised negative path. The comment’s claim that it presently validates provider truthfulness is overstated (`plugin/tests/test_pptx_public.py:119-125`).

Yes, every missing core operation fails at the membership assertion, and every present-but-unavailable core operation fails separately (`plugin/tests/test_pptx_public.py:107-110`). The four operations are registered on the always-available core Python provider (`plugin/src/document_skills_core/providers/defaults.py:52-78`).

### B. Browser dependency

The weakened availability requirement does not conceal a product defect. `pptx.create.from-html` is registered solely by `html-browser`, which is explicitly optional through `required=False` (`plugin/src/document_skills_core/providers/html_browser/provider.py:11-31`). The detector requires Node, the locked Playwright library, a supported local Chromium-family browser, and a successful launch probe (`plugin/src/document_skills_core/providers/html_browser/detector.py:38-55`, `plugin/src/document_skills_core/providers/html_browser/detector.py:68-104`). The sole-provider relationship is independently asserted at `plugin/tests/test_runtime.py:89-90`.

### C. Provenance allowlists

The three additions are minimal: both functional allowlists and the corresponding exact-path test receive only the new report path (`plugin/tools/regenerate_provenance.py:207-223`, `plugin/tools/provenance_records.py:101-120`, `plugin/tests/test_strategy2.py:286-305`). `_is_metadata` uses exact set membership, so no wildcard, directory, suffix, or neighboring report is newly excluded.

The report’s raw bytes do escape the mapping digest by design: metadata contributes only path and classification (`plugin/tools/provenance_records.py:24-29`). No other path’s bytes escape. The report bytes remain separately bound by `review_attestations[].report_sha256`, which the audit recomputes from the canonical file (`plugin/tools/audit_provenance.py:210-232`). Thus adding this path cannot hide arbitrary unreviewed code or data, assuming the required attestation is generated and validated.

### D. Version consistency

The four release manifests consistently carry 0.5.2: `package.json:3`, `package-lock.json:3`, `package-lock.json:9`, `plugin/elftia-plugin.json:3`, and `plugin/.claude-plugin/plugin.json:3`. No tracked source/configuration file retains 0.5.1 as a component version; remaining occurrences are historical review filenames.

The Python facade and internal Node runtime remain a separate, longstanding 0.1.0 version family (`plugin/pyproject.toml:2-3`, `plugin/package.json:2-3`, `plugin/src/document_skills_core/__init__.py:3`). They did not previously carry 0.5.1 and are not missed instances of this bump.

### E. Other objection

The checked-in comment says the capability assertion failed on all six CI legs (`plugin/tests/test_pptx_public.py:112-117`), but archived run `31529508680` contradicts that account. Only both Ubuntu legs reported the claimed PPTX failure and `1 failed, 1026 passed, 26 skipped`; Windows failed a different consumer-timeout test, and macOS reported 86 failures plus four errors. The workflow does define six OS/Node combinations (`.github/workflows/verify.yml:14-20`). Post-repair runs executed zero steps, so no completed matrix proves this delta makes CI green.

## Verdict

objections

- Correct the false “all six CI legs” provenance narrative and obtain an executed post-repair matrix result.
- Describe the reason assertion accurately as a regression guard, or add genuine negative-path evidence; current production output makes its failure branch unreachable.
