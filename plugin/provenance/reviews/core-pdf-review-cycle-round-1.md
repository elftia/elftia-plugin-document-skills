---
status: clean
approval_claimed: true
identity: codex-reviewer/document-skills-core-pdf/native-pdf-independent-review-rounds-1-15-0.5.5-2026-08-27
reviewer: "Codex native non-author review team/process: PDF completion rounds 1-15 and 0.5.5 release delta 2026-08-27"
scope: all-release-artifacts
identity_assurance: self-asserted
identity_limitations: >-
  Self-asserted composite native Codex non-author review-process identity on
  local Windows; it cannot cryptographically prove the service principal or
  claim that one individual reviewer executed all rounds. Rounds 1-14 retain
  the role and scope limitations recorded in their sections below. The fresh
  read-only Round 15 reviewer examined only the one-file Windows lock-fixture
  harness deadline delta against
  `cf2ea23c27feaeff72105070dedca41b8b0e7586`; it did not independently
  re-review the historical implementation or write source, tests, provenance,
  or this report.
  The nested reviewer `/root/pdf_independent_review/pdf_independent_review`
  executed round 1; its non-author parent `/root/pdf_independent_review`
  executed rounds 2 and 3. The fresh non-author reviewer
  `/root/pdf_final_independent_review` executed rounds 4 through 6. A fresh
  Codex non-author reviewer executed round 7 over the frozen uncommitted PDF,
  test, notice, adoption-review, and runtime-allowlist delta against baseline
  `120d60be42b3a29b85fc34af2bcd352f1ab40b75`. A fresh Codex non-author
  reviewer executed round 8 over only the Windows consumer-timeout harness
  delta and its prospective provenance identity. Round 2 re-reviewed only the
  fixer delta against the six round-1 findings; rounds 3-7 reviewed the
  generated artifacts and final deltas described below, and round 8 reviewed
  only the harness delta described below. The review process
  could not execute remote CI, a live host consumer, Poppler, Tesseract, qpdf,
  or a native PDF viewer, and does not claim OS-level resource-quota or current
  host-fleet evidence.
reviewed_mapping_sha256: 8a8b0f188b56fe74dd4f248e69366c7447733b2dbe06a7c16cf35c8ef71e449a
report_evidence: provenance/reviews/core-pdf-review-cycle-round-1.md
baseline: cf2ea23c27feaeff72105070dedca41b8b0e7586
review_round: 15
review_mode: windows-lock-fixture-full-suite-startup-budget-attestation
---

# PDF completion independent review - rounds 1-15

## Attestation and verdict

The machine identity above names a composite native Codex non-author review process, not one
individual agent. The nested child reviewer
`/root/pdf_independent_review/pdf_independent_review` executed round 1 and recorded the initial
four Blockers and two Majors. Its non-author parent reviewer `/root/pdf_independent_review`
executed round 2 over the fixer delta and round 3 over the generated-artifact delta. Round 2 was
deliberately limited to the fixer delta for the six recorded findings. Round 3 was deliberately
limited to `runtime-source-allowlist.json`, `sbom.cdx.json`, provisional `modules.json`, and
their generator consistency. The fresh non-author reviewer `/root/pdf_final_independent_review`
executed round 4 over the final PDF delta closures, the regenerated allowlist/SBOM/modules/audit
set, and delivery hygiene. After a full npm run surfaced four failures, the same fresh reviewer
reopened the verdict and executed round 5 over only those fixes and the newly regenerated
artifacts. Round 6 narrowly reviews the post-review removal of one terminal LF from
`rewrite_fonts.py` and rebinds provenance to the resulting file identity. Round 7 reviews the
frozen uncommitted JPEG/create-image and watermark semantic-closure delta against
`120d60be42b3a29b85fc34af2bcd352f1ab40b75`, including a producer fix made after the reviewer
reproduced an ordering failure. Round 8 narrowly reviews the single Windows consumer-harness
timeout change from 0.25 to 2.0 seconds and the resulting prospective provenance identity.
Rounds 9-13 are recorded in their dedicated sections below. Round 14 is a fresh read-only review
of the final six-file PDF read/pypdf safety delta and the producer's successive fixes. None of
the delta reviews restarted or generalized the review over the full historical implementation
diff. Reviewers did not author the production fixes. The write roles and limitations for the
historical review/provenance rounds remain recorded in their respective sections; the Round 14
reviewer made no file changes.

**Verdict: clean; approval claimed.** All four round-1 Blockers and both round-1 Majors are
closed by source inspection, independent public supervisor/worker reproductions, exact object
and byte-preservation checks, and focused regression runs. No new Blocker or Major was found in
the fixer delta, final PDF delta, or scoped generated-artifact deltas. Round 7 initially found a
Blocker in page-identity-replacement followed by watermarking; the producer fix is independently
verified closed below, and no release-significant finding remains. The final mapping digest
above is approved for the Round 14 reviewed snapshot. Round 8 found that the failed full `npm test` run
was startup-starved at the 0.25-second consumer-harness timeout rather than exposing a product
cleanup failure; the unchanged cleanup contract passes the independent evidence below. That
failed full run is not passing evidence, and a fresh full `npm test` run remains mandatory before
delivery. The round-8 report edit remains outside the mapping hash because this canonical report
is an explicit self-referential metadata exclusion. Round 14 initially found three related
read-projection Majors: a silent 5,000-block truncation, semantic filtering after a raw sentinel
that could hide later readable text, and a multi-page raw-block retention regression introduced
by the first fix. The producer closed all three with explicit warning evidence,
semantic-before-projection ordering, and page-local compaction; the fresh reviewer returned
`CLEAN — Blocker:0 Major:0 Minor:0 Trivial:0` on the final delta. Round 15 then reviewed the
single test-harness deadline change produced after the first complete verify run exposed Windows
startup starvation; the product's measured supervisor and cleanup assertions remain unchanged,
and the Round 15 reviewer also returned a clean verdict.

## Review-cycle history and disposition

| Round | Native non-author executor | Responsibility |
| --- | --- | --- |
| 1 | `/root/pdf_independent_review/pdf_independent_review` | Full initial review; recorded four Blockers and two Majors. |
| 2 | `/root/pdf_independent_review` | Fixer-delta re-review; independently reproduced closure evidence for the six findings. |
| 3 | `/root/pdf_independent_review` | Generated-artifact delta review; verified allowlist, SBOM, provisional mapping, and final prospective digest. |
| 4 | `/root/pdf_final_independent_review` | Fresh final-delta and generated-artifact review; closed B5/B9/B10, revalidated final walker bytes, and approved the current mapping. |
| 5 | `/root/pdf_final_independent_review` | Reopened review after four full-suite failures; verified the three exact fixes, focused 19-test closure, and regenerated artifacts. |
| 6 | `/root/pdf_final_independent_review` | Narrow review of one removed terminal LF; provenance report/modules/runtime/audit rebinding to the resulting exact mapping. |
| 7 | Fresh Codex non-author reviewer | Frozen uncommitted JPEG/create-image and watermark closure review; reproduced and closed the ordering Blocker, reran focused/P0 gates, and approved the prospective mapping. |
| 8 | Fresh Codex non-author reviewer | Narrow Windows consumer-timeout harness review; distinguished startup starvation from cleanup behavior, independently reran the unchanged contract, and approved the prospective mapping with a fresh full npm run still required. |
| 9 | Fresh Codex non-author reviewer | Monotonic 0.5.5 release-version and generated-artifact delta review. |
| 10 | Fresh Codex non-author reviewer | Bounded pipe worker boundary and identity-bound private-workspace review. |
| 11 | Fresh Codex non-author reviewer | Generated runtime-source allowlist and final mapping re-review. |
| 12 | Fresh Codex non-author reviewer | Volatile runtime-root test-copy isolation review. |
| 13 | Fresh Codex non-author reviewer | Public worker protocol documentation-truth delta review. |
| 14 | `/root/pdf_read_honesty_fixer` | Read-only six-file PDF read/pypdf hardening review; reproduced three projection/resource findings, re-reviewed their fixes, and approved the final prospective mapping. |
| 15 | `/root/pdf_worker_retry_review` | Read-only one-file Windows lock-fixture harness review; confirmed the outer deadline change does not relax measured product behavior. |

| Round-1 finding | Severity | Round-1 observed failure | Round-2 disposition |
| --- | --- | --- | --- |
| Shared `/Contents` page-scoped rewrite | Blocker | Targeting page 1 changed both pages from `Shared` to `Changed` and returned success. | **CLOSED** - shared ownership is detected before mutation; the public request returns `enhancement_required` / `DS_ENHANCEMENT_REQUIRED`, identifies owner pages 1 and 2, and preserves a pre-existing destination byte-for-byte. |
| Rotate polluted nested resources | Blocker | One rotation inserted `/Rotate 90` into the page, `/Resources`, and nested `/Font`. | **CLOSED** - the parsed outer page dictionary is serialized once; the candidate contains one `/Rotate`, nested resource/font dictionaries have none, and objects 1, 2, and 4 retain their source hashes. |
| Unicode rewrite ignored the resolved operator | Blocker | Hex `Tj` remained visible, `/ActualText` was changed, and duplicate visible text was published. | **CLOSED** - the Unicode branch consumes the resolved locators, blanks only the selected `Tj`/`TJ` operand, appends the shaped overlay, and verifies the reopened stream against the locator-derived expected prefix. Hex `Tj`, mixed `TJ`, duplicate visible text, `/ActualText`, and multiple streams were replayed. |
| Form fill corrupted escaped literal `/V` | Blocker | `/V (A\\)B)` became `/V (Alice)B)` while the public result claimed success. | **CLOSED** - `/V` is updated on the parsed top-level field dictionary and deterministically reserialized. Escaped-parenthesis, nested-parenthesis, backslash, and non-empty values all reopen with the requested value. |
| Text containing `BI` broke image extraction | Major | `(Power BI dashboard)` was treated as an inline-image opener and failed `DS_ARCHIVE_UNSAFE`. | **CLOSED** - inline-image discovery now uses a token-aware operator locator that skips literal strings, hex strings, comments, names, arrays, and dictionaries. String/comment/hex/name `BI` input returns success with zero images and a published archive. |
| `form_fill` authorized the whole object graph | Major | An unrelated Catalog hash fault was accepted because every existing object was preauthorized. | **CLOSED** - authorization is derived from selected fields/widgets, the AcroForm object, deterministic appearance additions, and flatten closures. The simple text-field plan is changed `{6,7}`, added `{8}`, removed `{}`; Catalog object 1 fault injection is rejected with `DS_VALIDATION_FAILED`. |

### 1. Shared content ownership - closed

- `rewrite_ownership.py:19-45` builds the content-object owner-page set and rejects any target
  whose owners are not exactly the selected page. Both Latin and Unicode paths invoke the gate
  at `rewrite_operator_targeting.py:88` and `rewrite_fonts.py:73`.
- Independent public replay: status `enhancement_required`, error
  `DS_ENHANCEMENT_REQUIRED`, capability `pdf.rewrite-shared-content-clone`, owner pages
  `[1,2]`; the destination remained the original `sentinel` bytes. No candidate was promoted.
- Regression coverage: `test_pdf_review_rewrite_regressions.py:178-202` covers Latin and
  Unicode replacement attempts through the public script and asserts fail-closed destination
  preservation.

### 2. Top-level rotation - closed

- `edit.py:345-365` copies the parsed page `PdfDict`, sets only its top-level `/Rotate` entry at
  line 359, serializes the dictionary, and writes the object through the mutation writer.
- Independent public replay: status `success`, promotion state `committed_clean`, exactly one
  `/Rotate` token, no `/Rotate` in `/Resources`, `/Font`, or the inline font dictionary, and
  unchanged hashes for every non-page object.
- Regression coverage: `test_pdf_review_edit_regressions.py:98-137` reopens the output and
  checks the entire nested resource path plus token count.

### 3. Locator-bound Unicode rewrite - closed

- `rewrite.py:93-99` passes the same resolved locator set into `apply_unicode_rewrites`.
  `rewrite_fonts.py:74-133,252-312` groups by the located content object, verifies the original
  operand bytes, replaces only the located `Tj`/`TJ` operand with `<>`, `()`, or `[]`, and
  appends the shaped overlay. `rewrite_unicode_verification.py:9-38` reopens the candidate and
  checks it against the exact locator-derived source transformation.
- Public hex replay: `/ActualText (Title)` remained byte-identical, the selected hex operand
  became `<> Tj`, the public result was `success`, and the only non-empty extracted visible
  text was the requested CJK replacement.
- Independent mixed-`TJ`/duplicate/multi-stream replay: source visible text was
  `[Title, Title]`; the selected mixed array became `[] TJ`, the second `(Title) Tj` and the
  separate `/ActualText` stream were preserved, output visible text was
  `[CJK_REPLACEMENT, Title]`, changed objects were `[3,6]`, and preserved objects were
  `[1,2,4,5,7]`. Promotion was `committed_clean`.
- Regression coverage: `test_pdf_review_rewrite_regressions.py:205-252` covers hex `Tj`, mixed
  `TJ`, `/ActualText`, and multiple streams. The independent replay adds a second visible
  duplicate on another stream to prove only the bbox-selected operator changes.

### 4. Parsed form-value replacement - closed

- `form_updates.py:51-66` requires a parsed field dictionary, assigns `/V` at line 60, and
  serializes the complete dictionary instead of matching literal-string bytes with a regex.
- Independent public replays used existing `/V` values `(A\\)B)`, `(A(B)C)`, and
  `(A\\\\B)`, then wrote a replacement containing parentheses and a backslash. All returned
  `success`, reopened with the exact requested value, retained one `/V`, and promoted with
  `committed_clean` state.
- The nested-value replay reported changed objects `[6,7]`, added object `[8]`, no removals,
  preserved objects `[1,2,3,4,5]`, and matching hashes for all preserved objects.
- Regression coverage: `test_pdf_review_edit_regressions.py:138-171` covers escaped,
  nested, backslash, and ordinary non-empty source values through the public boundary.

### 5. Token-aware inline-image discovery - closed

- `content_tokenizer.py:7-43` locates bare operators while skipping strings, comments, and
  compound tokens. `inline_images.py:34-45` uses it for both `BI` and bounded `ID` discovery.
- Independent public replay included `BI` in a literal string, hex string, comment, and name.
  It returned `success`, reported `image_count: 0`, and atomically published the empty image
  archive. Existing real-inline-image regressions remained green.
- Regression coverage: `test_pdf_review_edit_regressions.py:174-200` covers string/comment/hex
  negative tokens; `test_pdf_inline_images.py` covers supported and malformed real inline
  images.

### 6. Exact form-fill mutation authorization - closed

- `form_mutation_plan.py:11-49` computes the selected field/widget/AcroForm/page/annotation
  closure and deterministic addition range. `mutation_plan.py:88-89,150-171,374-388` applies
  that plan to both actual and declared object sets before accepting candidate hashes.
- Independent direct gate replay produced changed `{6,7}`, added `{8}`, removed `{}`. Replacing
  only Catalog hash 1 and declaring it changed raised `DS_VALIDATION_FAILED` with
  `unexpected_changed_objects: [1]`.
- Regression coverage: `test_pdf_review_edit_regressions.py:203-228` locks the exact plan and
  unrelated Catalog rejection.

## Delta coverage

```text
ROUND-1 FAILURE                 FIXER DELTA                         NON-AUTHOR ROUND-2 GATE
-----------------------------  ----------------------------------  ----------------------------
shared /Contents corruption -> exclusive-owner fail-closed      -> public failure + sentinel intact
nested /Rotate pollution     -> parsed top-level serialization  -> nested graph + object hashes
wrong Unicode raw bytes      -> locator-bound operand mutation  -> hex/TJ/duplicate/multi-stream
escaped form /V corruption   -> parsed PdfDict serialization    -> escaped/nested/backslash reopen
false BI inline-image token  -> token-aware operator search     -> string/comment/hex/name replay
all-object form permission   -> exact selected-field closure    -> Catalog fault rejected
```

Every round-1 path now has public or direct-gate regression coverage. No uncovered
Blocker/Major path was found in the named fixer delta. The shared-content behavior is an honest
fail-closed capability boundary rather than a silent partial implementation.

## Independent commands and results

| Command | Result |
| --- | --- |
| `uv run --project plugin --frozen pytest plugin/tests/test_pdf_review_rewrite_regressions.py plugin/tests/test_pdf_review_edit_regressions.py -q` | PASS - 11 passed in 23.4s |
| `uv run --project plugin --frozen pytest plugin/tests/test_pdf_review_rewrite_regressions.py plugin/tests/test_pdf_rewrite_targeting.py plugin/tests/test_pdf_unicode.py plugin/tests/test_pdf_inline_images.py -q` | PASS - 21 passed in 65.4s |
| `uv run --project plugin --frozen pytest plugin/tests/test_pdf_review_edit_regressions.py plugin/tests/test_pdf_edit_semantic_gate.py plugin/tests/test_pdf_form_flatten.py plugin/tests/test_pdf_form_reconciliation.py plugin/tests/test_pdf_mutation_writer.py -q` | PASS - 31 passed in 57.4s |
| `uv run --project plugin --frozen python -` with ephemeral public requests for shared `/Contents`, rotate, Unicode hex/duplicate/multi-stream targeting, escaped/nested/backslash form values, and non-operator `BI` | PASS - statuses and object/byte evidence recorded in the six closure sections above |
| `uv run --project plugin --frozen python -` with `declare_mutation_plan` plus unrelated Catalog hash fault injection | PASS - exact plan `{changed:[6,7], added:[8], removed:[]}`; fault rejected with `DS_VALIDATION_FAILED` |
| `uv run --frozen python -m tools.regenerate_provenance --project-root . --print-mapping-only` from `plugin` | PASS - `810403e80e82e19d7aa5e469b3f271537f7a355484f3075d10a415b1b0dae58a` |

The round-2 reviewer did not use the fixer's reported `378 passed` as evidence. The counts above are
fresh commands from this round. One initial inline Unicode probe was discarded because a
PowerShell native-process pipeline encoded the literal source text as question marks; the
independent replay was rerun with ASCII `\\u` escapes and is the result recorded above. This was
a reviewer-harness encoding issue, not a product result.

## Round-2 source size and prospective provenance checks (historical)

- Strict UTF-8 line-budget scan over PDF Core, `providers/pdf_tools`, and `providers/pypdf`
  found zero files at or above 600 physical lines and zero files at or above 400 effective
  nonblank/noncomment lines.
- The maxima are `rewrite_operator_targeting.py` at 453 physical / 399 effective,
  `compression_evidence.py` at 446 / 399, and `mutation_plan.py` at 426 / 393.
- Prospective mapping digest:
  `810403e80e82e19d7aa5e469b3f271537f7a355484f3075d10a415b1b0dae58a`.
  This was the correct pre-generation digest for round 2, but it was superseded when the runtime
  allowlist, SBOM, and provisional mapping were regenerated. It must not be bound or represented
  as the final snapshot.
- `plugin/provenance/modules.json:9276` currently contains an empty `review_attestations` list.

## Round 3 - generated-artifact delta re-review

### Verdict

**CLEAN in the explicitly scoped generated delta.** The runtime source allowlist, checked-in
SBOM, and provisional provenance manifest exactly match their generator results. The provisional
manifest remains PENDING and unbound. No in-scope Blocker, Major, Minor, or Trivial finding was
identified.

### Runtime source allowlist

- `runtime_source_allowlist()` and the checked-in
  `provenance/runtime-source-allowlist.json` are structurally identical: 255 Python sources and
  9 Node sources.
- The four fixer helper additions are present at allowlist lines 85, 115, 161, and 162:
  `content_tokenizer.py`, `form_mutation_plan.py`, `rewrite_ownership.py`, and
  `rewrite_unicode_verification.py`. Each path exists in the release tree.
- No allowlist entry begins with `tests/`, `consumer_validation/`, `tools/`, `docs/`, or
  `.github/`, and no listed basename begins with `test_`.
- A fresh frozen/offline `--no-dev` environment successfully ran public DOCX and PDF commands;
  `openpyxl`, `pymupdf`, `python-docx`, and `python-pptx` were absent while production `pypdf`
  and Pillow remained available.

### SBOM and dependency graph

- `sbom.cdx.json` is byte-for-byte equal to `canonical_json(build_sbom(root))` and contains
  24 unique components plus 22 unique dependency records. Every dependency edge resolves to a
  component or the application root.
- The SBOM lock identity is
  `2d5e8da7a5ba74d47ac09f3d7aadc9ba56f91ce9b0d74ff06e3714d135c8af90`, derived from the
  exact `uv.lock` and `package-lock.json` bytes and reproduced in both metadata and the serial
  number.
- Runtime dependencies include Pillow, pypdf, font shaping, crypto, schema, and the declared
  Node providers. Consumer/dev-only `openpyxl`, `pymupdf`, `python-docx`, `python-pptx`, and
  `pytest` are absent.

### Provisional release mapping

- Parsed `provenance/modules.json` is exactly equal to in-memory `regenerate(root)` output:
  394 executable/risky modules, 93 data classifications, 17 metadata exclusions, zero adopted
  sources, zero executable exclusions, and 504 total release inventory records.
- Every provisional record still names `PENDING independent review`; `review_attestations` is
  empty at `modules.json:9276`. The four fixer helpers appear as exact-hash module records at
  lines 3098, 3728, 4694, and 4715.
- Independent CLI regeneration returned the round-3 prospective mapping digest:
  `c0f2100dcaa527d740d4f304d25bd05f70595bc4c8292fc4abaf746880a68da8`.
  The previous `810403...` value is historical and superseded.

### Independent commands and results

| Command | Result |
| --- | --- |
| `uv run --frozen python -` comparing `runtime_source_allowlist`, `build_sbom`, `regenerate`, locks, release inventory, helper paths/hashes, forbidden runtime paths, and provisional review state | PASS - exact generator matches; 255 Python / 9 Node sources; 24 components / 22 dependencies; 394 modules + 93 data + 17 metadata = 504 release records; zero attestations |
| `uv run --frozen pytest tests/test_supply_chain.py::test_sbom_is_deterministic_and_matches_locks tests/test_supply_chain.py::test_sbom_application_identity_matches_both_plugin_manifests tests/test_supply_chain.py::test_sbom_records_docx_node_provider_and_transitive_graph tests/test_supply_chain.py::test_consumer_dependencies_are_exactly_allowlisted_but_not_in_runtime_sbom tests/test_supply_chain.py::test_provenance_covers_implementation_modules -q` | PASS - 5 passed in 16.6s |
| `uv run --frozen pytest tests/test_runtime_without_consumer_dev.py::test_runtime_sync_and_public_command_exclude_consumer_dev_dependencies -q` | PASS - 1 passed in 12.4s |
| `uv run --frozen python -m tools.regenerate_provenance --project-root . --print-mapping-only` | PASS - `c0f2100dcaa527d740d4f304d25bd05f70595bc4c8292fc4abaf746880a68da8` |

### Round-3 transitional audit follow-up (historical)

The existing `provenance/audit-report.json` was not one of the three generated artifacts in this
round and still contains its pre-delta counts: 389 module/risky records, 382 inspected source
files, and 499 release files (`audit-report.json:7,15,17,19,27-29`). Consequently, the combined
six-test exploratory command produced 5 passes and one failure at
`test_machine_readable_audit_report`; a direct comparison found seven count-only differences,
while both stored and current reports correctly remained `status: fail` because the provisional
manifest is not yet attested.

No pass is claimed for that out-of-scope transitional audit receipt. After the LEAD binds the
approved review to `modules.json`, it must regenerate `audit-report.json` from the bound final
artifacts and rerun `test_machine_readable_audit_report`. The audit report and this review report
are self-referential metadata exclusions, so that post-bind refresh does not alter the approved
mapping digest. This is a mandatory delivery follow-up, not an in-scope defect in the three
generated artifacts reviewed here.

## Round 4 - final delta and regenerated-artifact review

### Verdict and scope

**CLEAN in the reviewed final delta and generated snapshot.** The fresh non-author reviewer
`/root/pdf_final_independent_review` inspected the final B5, B9, and B10 implementation bytes,
replayed the focused/public/operation gates described below, and independently recomputed the
runtime allowlist, SBOM, provenance mapping, and provisional audit receipt. No in-scope Blocker,
Major, Minor, or Trivial finding remained at the end of round 4. The round-3 `c0f210...` digest is
historical. The round-4
`d2bba3aaf86810f85ea49fc6f8ce2cba1adf3d50783c8dbfb86e3ca23e6d3dbd` digest was approved at
that point but was superseded by the subsequent full-suite failure fixes and is not valid for
final binding.

### Final PDF delta closures

- **B5, simple-font encoding:** exact WinAnsi, MacRoman, and StandardEncoding tables are used
  only for closed Base14 Latin Type1 fonts. Canonical same-glyph duplicates select the stable
  byte (including WinAnsi space `0x20`); Symbol, embedded/custom Type1, `/Differences`, explicit
  null encoding, unrepresentable soft hyphen/Euro cases, and inconsistent `/ToUnicode` mappings
  fail closed. Eleven direct encoding probes passed. Stable SHA-256 identities are
  `23E563E049DB84976C7F56DBB56C0A8A988A8E5E317CD2BD9E245C56A6A45364` for
  `pdf_simple_encodings.py` and
  `A2B1C0A722A0E0F3D3AF7F05978D64BA737E44ACE6684EF41D46C5619B2AD82E` for
  `rewrite_font_encoding.py`.
- **B9, image source binding:** `expected_pages` is carried from the trusted request into archive
  validation; full-document and explicit-page requests are rebound to a fresh source traversal
  with strict ordered one-to-one manifest identity, inline payload/decode/pixel/source checks,
  and per-page `page_image_index` handling for repeated Forms. The five image source/decode/
  limits/inline/nested suites passed `38` tests. Stable SHA-256 identities are
  `9772F053C3EA546E62E643F3127AB4F3310288DC6E94D08A04A58B5823E9BE88` for
  `image_extraction_archive.py`,
  `F6166419275E954F2ECF54503A5070929AC1318ED2FD4699CC28DA55FB04110D` for
  `image_source_semantics.py`, and
  `6BC5F8CC449B7076466E3B057E2065114614536571ED559CC7189800531CF24D` for `service.py`.
- **B10, exact rewrite targeting/layout:** state traversal covers CTM and `q/Q`, state carry
  across `/Contents`, `Tj/TJ` advance, `TL/T*`, explicit widths, and fail-closed non-default
  text/graphics state. Prewrite and reopened candidates both pass page/selector/bbox gates.
  The final execution-boundary fix replaced runtime `setattr` with explicit dataclass-field
  assignments; the final `rewrite_operator_walker.py` SHA-256 is
  `8D9B7D58C3D995B6A4B69DC609BE0D7509BF2590158D1E770B72D859EFD576F9`.
  The initially observed four operation failures were obsolete success selectors whose `y0=754`
  excluded the fresh glyph bound `y0=753.89`; the test-only correction to `y0=753` conforms to
  the tightened caller-selector contract, while the CJK failure selector remains fail closed.

### Final local test and static evidence

| Final command or check | Result |
| --- | --- |
| C-drive frozen Python environment, `pytest -p no:cacheprovider` over `test_pdf_rewrite_font_encoding.py`, `test_pdf_rewrite_targeting.py`, `test_pdf_review_rewrite_regressions.py`, and `test_pdf_unicode.py` after the final walker edit | PASS - 47 passed in 127.1s |
| Same environment, full `test_pdf_operations.py` after the final walker edit | PASS - 54 passed in 3.8s |
| Same environment, `test_pdf_public.py -k "rewrite or edit"` after the final walker edit | PASS - 27 passed in 120.5s |
| Five B9 image source/decode/limits/inline/nested suites | PASS - 38 passed |
| Eight focused supply-chain, provenance, SBOM, machine-audit, and runtime-without-consumer-dev tests | PASS - 8 passed in 33.8s |
| Strict UTF-8 scan over PDF source, tests, and PDF skill assets | PASS - zero decode errors and zero UTF-8 BOM files; no replacement-character or Chinese-mojibake pattern found |
| PDF module effective-line gate | PASS - maximum 395 effective nonblank/noncomment lines (`create.py`) |
| `git diff --check` | PASS - no whitespace errors; Git emitted only existing LF-to-CRLF conversion warnings for `create.py`, `edit.py`, and `rewrite.py` |

The reused C-drive environment did not contain Ruff, so round 4 does not claim a fresh Ruff
receipt and did not install dependencies into the space-constrained E-drive worktree. This does
not replace the test and deterministic generator evidence above.

### Final generated-artifact identity

- `runtime_source_allowlist(root)` is structurally identical to
  `provenance/runtime-source-allowlist.json`: 274 Python paths and 9 Node paths.
- `sbom.cdx.json` is byte-for-byte identical to `canonical_json(build_sbom(root))`: 24
  components, 22 dependency records, and zero unresolved dependency edges.
- Parsed `provenance/modules.json` is exactly equal to `regenerate(root)`: 421 risky/module
  records, 107 data classifications, 3 exact self-referential metadata exclusions, zero adopted
  sources, zero executable exclusions, zero attestations, and 531 total release files. The three
  metadata paths are `provenance/audit-report.json`, `provenance/modules.json`, and this report.
- `provenance/audit-report.json` is byte-for-byte identical to
  `canonical_json(run_audits(root))`. Every non-provenance check, including
  `execution_boundary`, passes; its only error is `Independent review attestation is missing`.
- No `__pycache__`, `.pyc`, `.pytest*`, `.venv`, `.document-skills-tmp`, or `tmp/` path appears
  in the 531-file release mapping. Workspace-only untracked `.pytest-b10-layout-full/`,
  `.pytest-b10-rtl-detail/`, and root `tmp/` directories are not reviewed deliverables and must
  not be added to the commit or package.

The canonical review report is a self-referential metadata exclusion, so updating these report
bytes does not change the approved mapping digest. The LEAD must bind the latest exact attestation
returned with the final review round, hash these canonical report bytes into that attestation,
regenerate `modules.json`, and then regenerate `audit-report.json`. Those post-approval binding
operations are intentionally outside this reviewer's write authority.

## Round 5 - reopened full-suite failure delta

### Reopen reason and disposition

The round-4 CLEAN verdict was reopened when the first full `npm test` run completed with
`1464 passed, 3 skipped, 4 failed`. The failures were:

- `test_core_only_profile_runs_real_public_smokes` and
  `test_full_profile_runs_available_pypdf_smokes_before_reporting_unavailable`, whose shared
  provider-profile rewrite smoke used a replacement wider than its exact source selector;
- `test_public_create_text_overflow_preserves_destination`, whose error details no longer exposed
  the historical `content_bottom` diagnostic alongside the newer content-box evidence; and
- `test_public_create_embeds_real_png_and_read_projects_it`, whose static expected image bbox
  predated the candidate-derived heading ascender layout.

Each failure now has a narrow disposition:

- `tools/pdf_provider_profile.py` changes only the smoke replacement to `Provider verified`,
  which is shorter than the created `Provider profile smoke` heading. No rewrite selector,
  source binding, layout bound, or fail-closed gate was relaxed.
- `create_layout.py` retains the full `content_bbox` diagnostic and restores
  `content_bottom: layout.bottom` to the same invalid-request details. It does not alter overflow
  detection, promotion, or destination preservation.
- The PNG public test now expects candidate-derived bbox `[72.0, 698.29, 112.0, 738.29]` and
  binds that value independently across creation image evidence, the page/block mapping, and the
  reopened create-semantics gate's visible bbox. Production image placement was not changed by
  this failure fix.

Strict UTF-8 decoding found no errors or BOM in the three changed files. Their final SHA-256
identities are:

| File | SHA-256 |
| --- | --- |
| `src/document_skills_core/formats/pdf/create_layout.py` | `67A9BE7148F460D5FA0022049DC431BB925974A62D27AD7194D757867CFD6791` |
| `tests/test_pdf_public.py` | `5EF9BA9026E202D56364E61B588E227E7CEDCDCA6EBB890996ADCD7686F9D081` |
| `tools/pdf_provider_profile.py` | `278D8974FDB299299DDD33B9A35D2C4F0B92B9193E91F6D8E663D055610578F8` |

### Round-5 local evidence

| Command or check | Result |
| --- | --- |
| C-drive frozen Python environment, `pytest -p no:cacheprovider tests/test_pdf_provider_profiles.py tests/test_pdf_public.py::test_public_create_text_overflow_preserves_destination tests/test_pdf_public.py::test_public_create_embeds_real_png_and_read_projects_it -q` | PASS - 19 passed in 40.9s; covers all four previously failing cases |
| Eight focused supply-chain, provenance, SBOM, machine-audit, and runtime-without-consumer-dev tests | PASS - 8 passed in 35.5s |
| `git diff --check` over the three changed files | PASS - no whitespace errors |
| LEAD delivery run, exact `npm test` receipt on the fixed snapshot | PASS - exit 0; 1468 passed, 3 skipped in 1717.31s; compileall and audit passed later in the same run |

The mandatory post-fix full-suite gate is satisfied. The exact receipt above was executed and
reported by the LEAD rather than rerun by this reviewer; its passing total accounts for the four
previous failures (`1464 + 4 = 1468`) while retaining the same three skips. The subsequent
compileall and audit steps also passed, and the approved mapping digest remained unchanged.

### Round-5 generated artifacts

- Independent regeneration returns mapping
  `369627cb646c48fc1f5f6019663f11d537e1955bcde406b6910844eca9943719`.
- The checked-in runtime allowlist exactly equals `runtime_source_allowlist(root)` with 274 Python
  and 9 Node paths.
- The checked-in SBOM exactly equals `canonical_json(build_sbom(root))` with 24 components, 22
  dependency records, and zero unresolved edges.
- `provenance/modules.json` exactly equals `regenerate(root)`: 421 module/risky records, 107 data
  classifications, 3 metadata exclusions, zero attestations, and 531 release files.
- `provenance/audit-report.json` exactly equals `canonical_json(run_audits(root))`; its only error
  is `Independent review attestation is missing`, and `execution_boundary` passes.
- No pytest/tmp/venv/cache artifact appears in the release mapping. Existing workspace-only
  generated directories remain outside the reviewed deliverable and must not be committed or
  packaged.

## Round 6 - terminal-LF delta and provenance rebind

### Exact narrow-delta proof

Producer commit `fd1e7d571e98e2bf1d723e6290add317f52ebae6` records the completed PDF
change as one commit relative to its baseline, so the commit-to-parent diff is not evidence for
the post-review one-byte delta. Round 6 instead binds both sides to exact retained artifacts:

- The previously bound `modules.json` record gives the reviewed `rewrite_fonts.py` SHA-256 as
  `f134ac3085faa6025cb744037cdeab3731afebaa3879f0fc782df8ef9106210e`.
- Git's unreachable staged blob `0e88a6fa0ea0b9fe092a419e135cbf970ef29397` has that exact SHA-256
  and is 12489 bytes.
- The committed file is 12488 bytes with SHA-256
  `c0ae8f85de5541fccd0581061d939cbeb300b4fdc010395c148dd6bbb9b15832`.
- Direct byte comparison proves `new == old[:-1]`, the removed byte is exactly `0x0a`, and the
  terminal LF count changes from two to one. All executable/source characters are identical.

The round-5 full npm receipt was produced before this terminal-LF normalization, so it is not
misrepresented as an exact-hash test receipt for the new blob. The byte proof establishes that
the delta has no Python semantic effect; round 6 therefore confines reruns to provenance,
supply-chain, audit, encoding, and diff gates.

### Pre-rebind state

Independent frozen regeneration returned prospective mapping
`03359057d7502b9921d844ace98fa95c226fe3ced4b50746680b22041a490965`. Before rebinding,
`run_audits(root)` failed only with
`Module hash drift: src/document_skills_core/formats/pdf/rewrite_fonts.py`, as expected from the
one-byte identity change. No production source or test is modified by the rebind.

### Round-6 focused verification

| Command or check | Result |
| --- | --- |
| Frozen provenance regeneration with the existing unique review identity, followed by `tools.audit` generation | PASS - mapping `03359057...0965`; generator exit 0; audit exit 0 |
| Eight focused mapping coverage, metadata-boundary, SBOM, machine-audit, and runtime-without-consumer-dev tests | PASS - 8 passed in 30.2s |
| Bound-review drift and forged/unrooted attestation rejection tests | PASS - 5 passed in 35.5s |

One exploratory run of the entire `test_supply_chain.py` file plus the runtime gate exceeded the
240-second command limit and was terminated without a failure result; no pass is claimed for that
attempt. The two bounded focused runs above are the review evidence.

## Round 7 - frozen JPEG and watermark semantic-closure delta

### Scope and verdict

**CLEAN after one reproduced Blocker was fixed and re-reviewed.** The frozen worktree HEAD is
`120d60be42b3a29b85fc34af2bcd352f1ab40b75`. Round 7 reviewed the uncommitted PDF production
modules, their focused/public tests, the Pillow notice and adoption-review extension, and the
runtime-source allowlist delta. Existing workspace-only `.pytest-*` and `tmp/` trees were not
reviewed deliverables and were neither edited nor included in release/provenance checks. The
reviewer made no production, test, generated-artifact, cleanup, commit, or staging change.

### Initially reproduced ordering Blocker - closed

The first independent public reproduction applied `page_sequence` with `pages: [2]` and then a
text watermark to final page 1. It returned exit 2 with `DS_VALIDATION_FAILED`; the only failed
gate was `operation.mutation-semantics`, with direct mismatch `watermark-evidence:1`. A
pre-existing destination remained byte-identical and no staging residue remained. The cause was
stale original-source object ownership: an identity-replacing stage renumbered the document, so
a valid new watermark content object could collide numerically with the original object set.

The closure is narrow and independently sourced. `edit_pipeline.py` parses the current input or
previous authorized stage immediately before each watermark and snapshots its object-number set;
the watermark writer cannot supply that baseline. `service.py` removes both private watermark
commitment maps before public preservation validation/evidence. `edit_semantics.py` rejects a
missing or malformed baseline and supplies the stage-derived set to expectation planning.
`watermark_expectations.py` refreshes only object ownership while retaining independently
request-derived content, resource, font, image, soft-mask, geometry, and baseline semantics.
Role-specific generation, membership, canonical-payload, and trusted stage-hash checks remain in
`watermark_report_semantics.py`.

An independent OS-`TemporaryDirectory` public supervisor/worker harness then passed all six
ordering families: page-sequence then text, page-sequence then RGBA image, split then text,
page-insert then text, merge then text, and text watermark then page-sequence. Each final
candidate was reparsed and scanned; the exact text or asset SHA-256 was present once, the RGBA
soft mask was present, page counts matched, and neither `_watermark_stage_hashes` nor
`_watermark_source_objects` appeared anywhere in public operation evidence. One initial harness
invocation failed before product import because the standalone interpreter lacked the test
suite's `src` path bootstrap; no product result is claimed for it. The corrected in-memory
bootstrap produced the six passing results above.

### JPEG, image-object, and watermark closure

- Orientation-1 JPEG embedding is guarded by marker inspection plus a bounded Pillow decode
  proof while preserving original DCT bytes. EXIF orientations 2 through 8 are decoded,
  transposed, and emitted as bounded Flate Gray/RGB data. Adobe CMYK uses `/DeviceCMYK` with the
  closed `/Decode [1 0 1 0 1 0 1 0]` policy. Source hashes, dimensions, color spaces, filters,
  decode/decode-parameter fields, stream bytes, alt text, reference generations, and optional
  soft masks are rebound from reopened candidates.
- Watermarks now use one dedicated content object per target page and copy-on-write page
  resources. Candidate scans require closed content, ExtGState, font, image, and soft-mask
  dictionaries; exact request-derived operator bytes and bboxes; unique content ownership; and
  per-primitive image/mask ownership. Existing shared content and untargeted source objects remain
  preserved.
- A separate valid-PDF probe with source content generation 2 and free xref gaps exercised an
  RGBA watermark. The predeclared plan authorized objects 7 through 10, the writer added 7
  through 9, the public operation succeeded, and the original generation/free entries remained
  valid. This closes the reviewer's exploratory allocation concern without a finding.

### Round-7 independent commands and results

| Command or check | Result |
| --- | --- |
| Ephemeral public supervisor/worker ordering harness using OS `TemporaryDirectory` | PASS - 6/6 orderings; final candidate scans and private-key absence verified |
| `uv run --frozen pytest -p no:cacheprovider tests/test_pdf_jpeg_creation.py tests/test_pdf_jpeg_direct_embedding.py tests/test_pdf_watermark_blockers.py tests/test_pdf_watermark_semantic_closure.py tests/test_pdf_watermark_ordering.py -q` | PASS - 78 tests |
| `uv run --frozen pytest -p no:cacheprovider tests/test_pdf_create_promotion.py tests/test_pdf_edit_semantic_gate.py tests/test_pdf_image_alt_structure.py tests/test_pdf_watermark_fonts.py -q` | PASS - 78 tests |
| `uv run --frozen pytest -p no:cacheprovider tests/test_pdf_contracts.py tests/test_pdf_operations.py tests/test_pdf_public.py -q` | PASS - 166 tests |
| Strict UTF-8/no-BOM scan over all 32 changed/new deliverable source, test, notice, review, and allowlist files | PASS - no decode error, BOM, replacement character, or checked mojibake marker |
| PDF production-module line gate | PASS - maximum 445 physical lines (`create.py`) and 396 effective nonblank/noncomment lines (`service.py`) |
| `git diff --check` | PASS - no whitespace errors |
| In-memory allowlist/SBOM/audit comparison | PASS - 284 Python / 9 Node allowlist paths; 24 unique SBOM components / 22 unique dependency records; all edges resolve |
| `uv run --frozen python -m tools.regenerate_provenance --project-root . --print-mapping-only` before and after this report edit | PASS - both returned `4e3a1719780b16f50cecb14629c0e4553d7628c29a6991d8fb829bdf5437c985` |

The checked-in runtime allowlist is structurally identical to `runtime_source_allowlist(root)`.
The checked-in SBOM is byte-identical to `canonical_json(build_sbom(root))`. `run_audits(root)`
passes public skills, manifests, commands, inventory, execution boundary, fixtures, clean-room,
and SBOM checks; its sole pre-attestation failure is provenance with
`All-file provenance mapping does not match the release inventory`, which is the expected
unbound state for this frozen delta. The report path is explicitly listed in
`SELF_REFERENTIAL_METADATA_ALLOWLIST`, so changing only these report bytes leaves the prospective
mapping unchanged.

Round 7 is local Windows evidence only. It does not claim current-revision remote Windows,
macOS, or Linux CI; native Poppler render, OCR, qpdf, or viewer evidence; live host-consumer
fleet synchronization; OS-enforced CPU/memory/disk/process quotas; or a fresh full npm,
build/dist, or reproducibility run.

## Round 8 - Windows consumer-timeout harness delta

### Scope, failed full run, and verdict

**CLEAN for the narrow test-harness delta; no release-significant finding remains.** The only
round-8 implementation delta is
`tests/test_consumer_validation.py::test_real_consumer_timeout_kills_descendant_and_preserves_file`
changing the `open_with_office("word", artifact, ...)` timeout from 0.25 to 2.0 seconds. The
PowerShell parent and child still sleep for 30 seconds, and the test still requires a timeout,
`descendants_cleaned is True`, creation of a real child PID, death of that descendant, an
unchanged artifact SHA-256, and total elapsed time below 10 seconds. Round 8 made no production,
test, generated-provenance, cleanup, commit, or staging change; this canonical report is its only
write.

The full `npm test` attempt on the round-7 snapshot completed with 1563 passed, 3 skipped, and
one failed Windows consumer-harness test: the exact test above. It failed again in isolation at
0.25 seconds, before the PowerShell body created the child/PID file. **That full run is failed and
is not claimed as passing evidence.** Read-only timing exploration found that 0.25, 0.5, and
0.75 seconds never reached PID creation, while 1.0 and 2.0 seconds did. The delta therefore gives
the real descendant enough Windows startup time to exist before exercising the intended timeout
and process-tree cleanup contract; it does not relax the 30-second workload or the under-10-second
timeout bound.

### Independent contract and source verification

Source tracing confirms that `consumer_validation/office.py` launches an isolated PowerShell
process, waits only for the supplied bounded timeout, and on timeout invokes the Windows tree
terminator. That path uses `taskkill.exe /PID <pid> /T /F`, enumerates/waits/kills descendants,
and reports `descendants_cleaned=True` only after successful cleanup. Timeout evidence still
projects the timeout category, cleanup category, drain status, and bounded stream metadata.

The exact unchanged test contract was independently run five times at 2.0 seconds and passed
5/5. A separate direct OS-temporary harness observed a real descendant and returned:

```text
cleanup_category: taskkill-complete
descendants_cleaned: True
child_dead: True
artifact_unchanged: True
elapsed_seconds: 2.387
```

This closes the observed harness-startup failure while retaining direct evidence that the actual
descendant is terminated and the source artifact is preserved.

### Prospective provenance and mandatory delivery gate

Independent in-memory regeneration and
`uv run --frozen python -m tools.regenerate_provenance --project-root . --print-mapping-only`
both returned prospective mapping
`4b1750343aec47aeddadefacc75cfb6391a092de16b9c663a973f56e2710f021`. Runtime allowlist parity
passes at 284 Python and 9 Node paths; SBOM parity passes at 24 components and 22 dependency
records. The checked-in `modules.json` and audit report are still bound to round-7 mapping
`4e3a1719780b16f50cecb14629c0e4553d7628c29a6991d8fb829bdf5437c985`. Immediately before this
self-referential report edit, a fresh `run_audits(root)` failed only with
`Module hash drift: tests/test_consumer_validation.py`. After the report edit, the round-7
attestation necessarily also contains the old report SHA-256, so a fresh audit stops at
`Review report hash does not match canonical bytes` until regeneration. This is the expected
pre-rebind state, not a passing bound-audit receipt. The LEAD must regenerate and bind the
round-8 provenance artifacts, then obtain a new passing full `npm test` result for that delivery
snapshot. Focused round-8 evidence does not waive or substitute for that gate.

## External limitations retained from rounds 1, 7, and 8

- `pdftoppm`, `tesseract`, and `qpdf` remain unavailable locally. No local native render, OCR,
  or qpdf receipt is claimed; the optional visual mutation gate reported unavailable rather
  than passing.
- No current-revision remote Windows/macOS/Linux CI receipt was available to this review process.
- No deployment CPU, memory, disk, process-sandbox, or resource-quota receipt was available for
  native Poppler/Tesseract execution.
- No live host-consumer synchronization/fleet-pin receipt was observed.
- No independent Rasen target-line authority beyond the supplied PDF completion task was
  observed.
- The round-4 reused C-drive Python environment did not include Ruff; no fresh round-4 Ruff
  receipt is claimed, and no dependency installation was attempted in the low-space E-drive
  worktree.

These are external release/operations receipts, not unresolved defects in the six-item fixer
delta. They remain explicit limitations and must not be silently represented as locally
verified.

## Approval statement

`approval_claimed: true`; `status: clean`. The six round-1 Blocker/Major findings remain
non-author-confirmed closed, the round-2 fixer delta is clean, rounds 3-4 establish generated-
artifact and final-delta consistency, and round 5 closes the four surfaced full-suite failures
with focused evidence. Round 7 independently reproduced and closed the page-identity-replacement
then watermark Blocker and found no remaining release-significant issue in the frozen delta.
Round 8 independently verifies that the 2.0-second Windows harness timeout exercises the same
bounded process-tree cleanup contract and finds no release-significant issue in that one-line
test delta. The failed round-7-snapshot full run is not passing evidence; release still requires
fresh regenerated provenance and a new passing full `npm test` run. Subject to that unwaived
delivery gate, the approved mapping identity for the current provisional snapshot is
`4b1750343aec47aeddadefacc75cfb6391a092de16b9c663a973f56e2710f021`.
This approval is issued by the composite native Codex non-author review process described above:
the child reviewer owns the round-1 findings, its parent owns the round-2 closure and round-3
generated-artifact checks, `/root/pdf_final_independent_review` owns rounds 4-6, and the fresh
Codex non-author reviewers own rounds 7 and 8. Historical digests `810403...`, `c0f210...`,
`d2bba3...`, `369627...`, `03359057...`, and `4e3a17...` are not valid for the round-8 binding.
Rounds 7 and 8 each modify only this canonical report and do not modify production source/tests,
generated provenance, stage, commit, archive, or ship. Round 8 makes only the narrower local
claims enumerated above and explicitly requires a new full npm-suite delivery receipt.

## Round 9 — monotonic `0.5.5` release-version and generated-artifact delta

A fresh native non-author reviewer `/root/pdf_seeder_version_audit` independently reviewed only
the release-version and generated provenance/SBOM delta layered on producer commit
`efcbe0c527dda3b5a657c7ee3916f46cc163184f`. The reviewer did not author the version change,
production implementation, generated artifacts, or canonical report.

### Why the version bump is required

Host source inspection confirms that `ManagedRuntimeRootSeeder` skips a present managed tree when
the bundled version is not strictly greater. Its shared gate is exactly
`compareVersions(bundled, present) > 0`. Therefore bundled `0.5.4` against installed `0.5.4`
returns `skipped-up-to-date`, while `0.5.5` against installed `0.5.4` enters the publish path.
The focused host Seeder suite independently passed all 34 tests.

### Release-version consistency

The producer release identities are consistently `0.5.5` in root `package.json`, both root
`package-lock.json` release-version positions, `plugin/elftia-plugin.json`,
`plugin/.claude-plugin/plugin.json`, and the CycloneDX application component. The internal
Python/Node runtime package family remains independently versioned at `0.1.0`;
`plugin/pyproject.toml`, plugin `package.json`, and both plugin lockfile positions are unchanged.

The tracked delta contains exactly the two root release-version files, the two plugin manifests,
the pending provenance mapping, and the SBOM. `git diff --check` passes. Every modified file
strictly decodes as UTF-8, has no UTF-8 BOM, and contains no replacement character.

### Generated-artifact consistency

Independent generator comparison found `plugin/sbom.cdx.json` byte-identical to fresh
`build_sbom` output: 10,913 bytes, SHA-256
`477eb8d13f7ec594a4e31d595b07e917e6d05e0b4e585043e25a53e033c5a4f8`,
24 components, and 22 dependency records.

Pending `plugin/provenance/modules.json` is byte-identical to fresh regeneration:
436 module records, 107 data classifications, three exact metadata exclusions, zero executable
exclusions, zero adopted sources, and zero review attestations. All 546 release paths are
classified. No release path was added or removed by the version delta; only
`.claude-plugin/plugin.json`, `elftia-plugin.json`, and `sbom.cdx.json` changed classified data
hashes. Every pending record names `PENDING independent review`.

Both in-memory regeneration and

`uv run --frozen python -m tools.regenerate_provenance --project-root . --print-mapping-only`

returned prospective mapping
`2eeb82304358c92999a74521e601629bc69b2c80621c645274202896f0bfab22`.

A live machine audit passed clean-room, commands, execution-boundary, fixtures, inventory,
manifests, public-skills, and SBOM checks. Its sole failure was the expected pre-binding error
`Independent review attestation is missing`; inventory was 546 files with 436 risky records.
The checked-in prior audit receipt is not claimed as current evidence and must be regenerated
after this Round-9 attestation is bound.

Three focused manifest/SBOM consistency tests passed. The pre-existing `dist/document-skills`
still represents the old `0.5.4` build and is explicitly not approved as `0.5.5` delivery
evidence. A fresh build, dist validation, full `npm run verify`, release archive, reproducibility
check, and host fleet synchronization remain mandatory after binding.

### Round-9 verdict

**Clean for the scoped release-version and generated-artifact delta; approval claimed for
prospective mapping
`2eeb82304358c92999a74521e601629bc69b2c80621c645274202896f0bfab22`.**

Attestation identity:
`codex-reviewer/document-skills-core-pdf/native-pdf-independent-review-0.5.5-2026-08-26`;
`status: clean`.

This review does not independently re-review the historical PDF implementation covered by
rounds 1–8 and does not claim remote CI, native Poppler/Tesseract/qpdf, native-viewer,
OS resource-quota, final dist/archive reproducibility, or live host-fleet evidence.

## Round 10 — bounded pipe worker boundary and identity-bound private workspace

### Scope and role separation

Round 10 reviews the public supervisor/worker failure boundary added after Round 9. The original
file protocol wrote `command.json`, `result.tmp`, and `result.json` under a random invocation
directory. Bounded replace/cleanup retries could not make that design safe under permanent
Windows locks without adding an unauthenticated marker queue, recursive cleanup, and a detached
reaper. Three bounded strategy attempts therefore replaced the design rather than extending it.

The authors and verifiers were distinct native Codex subagents:

- `/root/pdf_pipe_protocol_fixer` authored the bounded stdin/stdout pipe strategy;
- `/root/pdf_posix_identity_fixer` authored the POSIX held-fd and module-boundary correction;
- `/root/pdf_static_worker_fixer` authored the closed static-worker capability and cancellation
  ownership correction;
- `/root/pdf_worker_retry_review` independently reviewed strategy attempts 1 and 2; and
- fresh non-author `/root/pdf_attempt3_fresh_review` independently reviewed attempt 3 and issued
  the final `CLEAN` verdict.

No fixer self-certified its own delta. The canonical review-cycle history is
`tmp/pdf-worker-retry-review/evidence/review-report.md` (SHA-256
`8e24dbdfb67f1ca9a2d4d38a63f55256b0c495626692f2cfe9756f0681b12369`). The final fixer report is
`tmp/pdf-worker-retry-review/evidence/fix-strategy-3-report.md` (SHA-256
`ee6fcb7feafe22765f435560c025bf87e89219b427eb47559d7d4d1c7572bb6e`). Those worktree-local
reports are review evidence, not release inventory inputs.

### Final protocol and containment boundary

The public command is encoded once and sent through bounded stdin. The one-shot worker flushes
provider streams and emits one canonical ASCII terminal frame on private stdout. The supervisor
searches only for the final frame, rejects a missing, malformed, non-canonical, unbound,
oversized, or trailing-data frame, validates its schema, and remains the sole public stdout and
cancellation owner. Provider stdout/stderr noise is bounded by `ProcessRunner` and never appears
in public stdout, stderr, or result details. There are no command/result files, cleanup markers,
sibling scans, recursive deletes, background reapers, detached `Popen` objects, dynamic `-c`,
shell dispatch, or secret argv/environment fields.

`.document-skills-tmp` and each random invocation child are created through no-follow,
identity-bound directory anchors. Windows holds base/root handles without delete sharing and
deletes the same identity through a handle-bound disposition with fixed WinError 5/32 retries.
POSIX launches only the exact canonical `public-command-worker` script through a dedicated
closed process capability: generic `ProcessRunner.run()` cannot inherit fds, while the worker
inherits exactly one held directory fd, verifies type/device/inode, `fchdir`s, verifies `.` and
current project containment, closes its child fd, and only then reads or dispatches the command.
The final reviewer independently rejected `-c`, `-m`, misplaced/extra/duplicate bootstrap args,
other provider ids, and other allowlisted scripts.

POSIX has no portable object-bound `rmdir`; a separate identity check followed by name-based
deletion can remove a substituted directory. Production therefore makes the conservative choice
to leave its own empty random invocation directory rather than perform a raceable delete. On
Windows, a permanent external directory lock that exceeds the fixed retry budget may likewise
leave only the current empty random directory. Neither case retains command bytes, result bytes,
provider output, credentials, or recursively discovered content. This is an honest empty-residue
boundary, not a claim of unconditional final deletion.

The final source review closed original S1 and S5–S10 plus A1–A4 and B1–B2. One accepted-known
Minor remains: if static project-root resolution itself fails before the inherited-fd `finally`,
dispatch is prevented and one-shot process exit closes the fd, but an imported direct call does
not explicitly close it first. It is not an authorization, containment, data-residue, or provider
execution bypass. No Blocker or Major remains in the Round-10 source/test delta.

### Independent and LEAD verification receipts

| Command or check | Result |
| --- | --- |
| Final independent `test_private_workspace_identity.py` | PASS — 17 passed, 3 POSIX-only skips on Windows |
| Final independent pipe/redirect + complete PDF public worker-failure selection | PASS — 55 passed |
| Final independent four-format public, frozen no-dev/offline, and exact fixture selection | PASS — 6 passed |
| Final independent `PYTHONWARNINGS=default` noise/hang/transient/permanent selection | PASS — 5 passed; public stderr stayed empty |
| Final independent execution-boundary audit | PASS — 9/9 affected runtime files |
| Final independent Ruff check/format, strict UTF-8/no-BOM/U+FFFD, line buckets, fixture hashes/cache scan, and `git diff --check` | PASS |
| LEAD exact task-book P0 command on the frozen source/test snapshot | PASS — 166 passed |
| LEAD combined identity/transaction/pipe/failure/no-dev gate before provenance rebind | 187 passed, 5 skipped; sole failure was the expected stale runtime-source allowlist S4 gate |

The three POSIX process/rename integration tests exist but were skipped on this Windows host; no
Linux/macOS execution receipt is invented. The exact P0 command was:

`uv run --project plugin --frozen pytest plugin/tests/test_pdf_contracts.py plugin/tests/test_pdf_operations.py plugin/tests/test_pdf_public.py -p no:cacheprovider`

### Explicit scope decisions

- Embedded files remain inert inventory only. Add/remove mutation is explicitly deferred to a
  separate safety slice covering attachment size/type policy, names-tree and `/AF` relationships,
  action isolation, atomic mutation, preservation, and adversarial fixtures. No public add/remove
  primitive is registered or claimed in this release.
- PDF/A conversion and compliance validation are evaluated and deferred. A future slice must
  select conformance levels, color-profile/XMP policy, an authoritative validator such as
  veraPDF, provider licensing/distribution, and reproducible fixtures before advertising support.
- PDF/UA conversion and compliance validation are evaluated and deferred. Current image alt
  metadata does not establish tagged logical structure, reading order, semantic roles, or
  accessibility conformance; a future slice requires a dedicated tagged-PDF model and external
  validation authority.
- Digital signatures remain inert inventory/validation only; creation still requires a separate
  key custody and trust model. Linearization, portfolio, 3D/multimedia, JavaScript authoring, and
  PDF-to-DOCX remain outside this session exactly as specified.

### External and delivery limitations

Local `pdftoppm`/Poppler and Tesseract remain unavailable, so `pdf.render` and `pdf.ocr` truthfully
report unavailable. No current remote Windows/macOS/Linux CI, native Poppler/Tesseract/qpdf,
Acrobat/Chrome PDFium/Preview/Poppler viewer, OS-native provider quota/sandbox, upstream PR, or
live Host fleet receipt is claimed. Core/pypdf operations are not used to fabricate those missing
provider/viewer results. Final full-suite, bound audit, build, dist, reproducibility, release ZIP,
Producer commit, and Host consumer receipts remain separate mandatory LEAD delivery gates.

### Round-10 approval

`approval_claimed: true`; `status: clean`. The composite review now covers rounds 1–10. Round 10
supersedes the provisional Round-9 binding for the public worker/anchor delta. Subject to the
explicit unwaived delivery gates above, the approved prospective mapping for the frozen
source/test snapshot is
`d30ea94b167475c1367754d5baf3c9443b2e3067ef3ddb4cf3aa52d3710b67b7`.

## Round 11 — generated runtime-source allowlist and final mapping re-review

### Scope and role separation

Round 11 is a fresh non-author review of the generated delta created when the Round-10 source
snapshot was materialized into `provenance/runtime-source-allowlist.json`. This reviewer authored
none of the source, tests, runtime allowlist generator, or first-pass generated provenance. The
review is deliberately limited to proving that the generated allowlist delta is exact, that it
refers only to source already covered by Round 10, and that the resulting all-file mapping is
stable. No implementation, test, allowlist, modules, audit, SBOM, manifest, release, or Host file
was modified by this review.

### Generated-delta evidence

- Relative to `HEAD`, the Python runtime-source allowlist has exactly two additions, zero
  removals, and no Node-list change:
  `src/document_skills_core/core/io/bound_child_directory.py` and
  `src/document_skills_core/worker/private_workspace.py`.
- Both files are part of the identity-bound workspace implementation reviewed and accepted in
  Round 10. Their current SHA-256 values exactly match their first-pass `modules.json` records:
  `bound_child_directory.py` =
  `7367371585fe33f76c8b8dd66915075db2e6f0f0733878d08bf6d09516b7175f` and
  `private_workspace.py` =
  `adb63599848ea527f10bdd239bee8bf8ef6a53a25d524e778d4b2ebcda7ee2a7`.
- The materialized runtime allowlist SHA-256 is
  `55a9c4e4ea9585d2de78f67c596b2de9e3b7382603e24c0ae04a7dbae3f73b35`.
  The first-pass modules record still names the pre-materialization hash
  `60255e3b68fe6efd72221345b7251213e0b4aa7db5ac0b14a549618799664f1a`.
- Two consecutive read-only
  `uv run --frozen python -m tools.regenerate_provenance --project-root . --print-mapping-only`
  executions returned the same mapping:
  `5c5a3b80d975699891b9725218d0b7bd6c662d15e7e572e99d9e8cb67d785768`.
- The live machine audit passes execution-boundary, clean-room, commands, fixtures, inventory,
  manifests, public skills, and SBOM. Its sole failure is the expected first-pass stale data
  record: `Classified data hash drift: provenance/runtime-source-allowlist.json`. The current
  generated manifest otherwise has 439 module records, 107 data records, three metadata
  exclusions, and exactly one review attestation.

The mapping approved in Round 10,
`d30ea94b167475c1367754d5baf3c9443b2e3067ef3ddb4cf3aa52d3710b67b7`, was correctly computed
before the runtime-source allowlist was written. Because that allowlist is itself a classified
release-inventory input, materializing its two reviewed entries changed its bytes and therefore
changed the all-file mapping. Round 11 explicitly supersedes the provisional `d30ea94b...`
approval; approval is not inferred or copied across the mapping change.

### Round-11 approval and remaining gates

`approval_claimed: true`; `status: clean`. No Blocker or Major was found in the generated delta.
The accepted-known Minor and platform limitations recorded in Round 10 remain unchanged. The
exact approved prospective mapping for the frozen release-input snapshot is:

`5c5a3b80d975699891b9725218d0b7bd6c662d15e7e572e99d9e8cb67d785768`.

This approval authorizes only the mechanical second-pass provenance rebind to that exact mapping:
update the existing single composite review attestation (do not add another), bind it to the
current hash of this canonical report, regenerate `modules.json` against the already-materialized
allowlist, and rerun the live audit before writing the final audit receipt. Any change to source,
tests, fixtures, manifests, SBOM, runtime allowlist, or other non-metadata release bytes after this
review invalidates the approved mapping and requires a new review.

No remote Windows/macOS/Linux CI, native Poppler/Tesseract/qpdf, Acrobat/Chrome
PDFium/Preview/Poppler viewer, OS-native provider quota/sandbox, upstream PR, or live Host fleet
receipt is claimed. Final full-suite, build, dist, reproducibility, release ZIP, Producer commit,
and Host consumer gates remain mandatory and unwaived.

## Round 12 — volatile runtime-root test-copy isolation re-review

### Scope and role separation

Round 12 is a fresh non-author review of the generated/test-isolation delta made after Round 11.
The reviewer authored none of the source, tests, allowlists, audit implementation, generated
provenance, or earlier review rounds. The reviewed delta is exactly one added
`shutil.ignore_patterns` entry in `plugin/tests/test_supply_chain.py`:
`.document-skills-tmp`. No module, allowlist, audit source, production source, or other test was
modified by this review; this Round-12 block is its sole persistent write.

### Isolation and release-boundary evidence

- The one-line ignore is minimal and changes only `_copy_audit_project`, the test helper that
  creates isolated audit fixtures with `shutil.copytree`. It prevents those fixture copies from
  entering the volatile `.document-skills-tmp` tree and therefore from copying private runtime
  session data whose files may disappear while a copy is in progress.
- The helper contains no delete, move, rename, or source mutation. A synthetic external-temporary
  gate copied an ordinary file, omitted a `.document-skills-tmp/session` sentinel subtree,
  confirmed the original sentinel bytes were unchanged, and confined cleanup to that temporary
  directory. No source or user data was deleted.
- The test-only ignore does not suppress the authoritative release inventory or its audit path.
  Production `plugin/tools/release_inventory.py` independently names
  `.document-skills-tmp` in `_LOCAL_GENERATED_ROOTS`, and `_is_worktree_only` excludes that exact
  first path component. `release_inventory()` and `release_artifacts()` do not call the test-copy
  helper, so release classification remains governed by the production inventory policy.

### Independent verification receipts

| Command or check | Result |
| --- | --- |
| Exact `git diff -- plugin/tests/test_supply_chain.py` | PASS — one added ignore entry and no other hunk |
| Two consecutive `uv run --frozen python -m tools.regenerate_provenance --project-root . --print-mapping-only` runs | PASS — both returned `9e9938864e7495387a1fadbdd2fb23b357d6aeb4c4d828dd887e2638adc7f349` |
| External-temporary `_copy_audit_project` sentinel gate with `PYTHONDONTWRITEBYTECODE=1` | PASS — runtime root omitted, ordinary file copied, source sentinel unchanged, scoped cleanup complete |
| Four representative helper-calling supply-chain tests with `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider` | PASS — 4 passed in 44.22s |

An initial aggregate selection of all 11 helper-calling test functions exceeded its 120-second
harness bound without a result; no pass or failure is claimed for that interrupted aggregate.
It is not substituted for the still-mandatory final full-suite gate.

### Round-12 approval and remaining gates

`approval_claimed: true`; `status: clean`. No Blocker or Major was found in this generated/test
isolation delta. Round 12 supersedes the Round-11 prospective mapping because the test file is a
release input. The exact approved prospective mapping is:

`9e9938864e7495387a1fadbdd2fb23b357d6aeb4c4d828dd887e2638adc7f349`.

This approval is limited to the reviewed one-line test-helper delta and the existing frozen
release-input snapshot. Any later change to source, tests, fixtures, manifests, SBOM, runtime
allowlist, audit policy, or other non-metadata release bytes invalidates this mapping and requires
a new review.

No remote Windows/macOS/Linux CI, native Poppler/Tesseract/qpdf, Acrobat/Chrome
PDFium/Preview/Poppler viewer, OS-native provider quota/sandbox, upstream PR, or live Host fleet
receipt is claimed. External integration, final full-suite, build, dist, reproducibility, release
ZIP, Producer commit, and Host consumer gates remain mandatory and unwaived.

## Round 13 — public worker protocol documentation truth delta

### Scope and role separation

Round 13 is a fresh non-author review of exactly two author-owned files changed after the
Round-12 release rebind: `README.md` and `tests/test_structure.py`. The reviewer authored neither
delta and made no change to implementation, tests, dist, release, locks, manifests, SBOM, runtime
allowlist, or other release inputs. This round checks only that the public containment
documentation now matches the already-reviewed worker protocol and that its regression test is
strong enough to prevent the specific stale file-channel claim from returning. It does not
re-review or expand the historical implementation findings from rounds 1–12.

### Documentation and implementation evidence

- `README.md` now describes the actual public boundary: one bounded ASCII command envelope is
  sent through worker stdin; the supervisor accepts one bounded, canonical ASCII terminal frame
  at the end of worker stdout; and the public protocol creates no command or result files. The
  former claim that a nonce-bound atomic result file was the only worker channel is absent.
- The implementation independently proves those statements. `ProcessRunner` serializes the
  command envelope with JSON escaping and writes it to stdin; the static worker reads at most
  `MAX_COMMAND_BYTES + 1`, decodes strict ASCII, and rejects empty or oversized input. The
  supervisor parses only the final `DOCUMENT_SKILLS_WORKER_FRAME_V1` frame, requires strict ASCII,
  the byte ceiling, canonical serialization, and no trailing data, and remains the sole public
  stdout owner. The private workspace is launch/lifecycle state, not a result channel.
- The README keeps the HTML capture boundary separate and truthful. That provider-internal path
  still creates private scene/assets, binds its scene status to its own command nonce, and applies
  independent time and byte ceilings. The public worker documentation does not erase or conflate
  that distinct private-file protocol.
- The new structure test scopes itself to the `Public protocol containment` section, asserts all
  three positive stdin/stdout/fileless statements plus the identity-bound workspace statement,
  rejects the exact obsolete result-file sentence, and separately requires the HTML nonce-bound
  scene/assets wording. It therefore cannot pass merely because the stale sentence was deleted.

### Independent verification receipts

| Command or check | Result |
| --- | --- |
| Exact `git diff -- README.md tests/test_structure.py` and implementation read-through | PASS — only the reviewed documentation and regression-test delta; statements match `public_cli/protocol.py`, `public_cli/supervisor.py`, `worker/main.py`, `worker/private_workspace.py`, `core/process/runner.py`, and PPTX HTML capture code |
| Strict UTF-8/no-BOM/U+FFFD plus focused `git diff --check` | PASS for both author files |
| README stale-sentence and HTML-boundary scan | PASS — zero obsolete sentence occurrences in README; one intentional negative-test literal; one explicit `HTML capture is separate` boundary |
| `PYTHONDONTWRITEBYTECODE=1 uv run --frozen pytest tests/test_structure.py::test_readme_documents_fileless_bounded_public_worker_protocol tests/test_pdf_public_worker_failures.py tests/test_private_workspace_identity.py -p no:cacheprovider` | PASS — 32 passed, 3 POSIX-only skips on Windows in 43.22s |
| Two consecutive `uv run --frozen python -m tools.regenerate_provenance --project-root . --print-mapping-only` runs before this metadata-only report edit | PASS — both returned `74545f37a839595ede7086f80bdaecc8ed8388f31e930e23e3e375204680bdb4` |
| Pre-rebind read-only `uv run --frozen python -m tools.audit --project-root .` | Expected FAIL — the first reported stale record was `Module hash drift: tests/test_structure.py`; this is the exact author delta requiring the mechanical rebind below, not an implementation failure |

### Round-13 approval and remaining gates

`approval_claimed: true`; `status: clean`. No Blocker, Major, or accepted-known Minor was found in
the README/test delta. Round 13 supersedes the Round-12 prospective mapping because both reviewed
files are release inputs. The exact approved prospective mapping is:

`74545f37a839595ede7086f80bdaecc8ed8388f31e930e23e3e375204680bdb4`.

Attestation identity:
`codex-reviewer/document-skills-core-pdf/native-pdf-independent-review-rounds-1-13-0.5.5-2026-08-26`.

This approval authorizes only the official two-stage provenance regeneration and reuse-review
rebind for that exact mapping, with the single composite attestation updated from rounds 1–12 to
rounds 1–13 and bound to this canonical report. It does not independently re-review historical
source, reopen earlier accepted limitations, or approve any later non-metadata release-byte
change.

No remote Windows/macOS/Linux CI, native Poppler/Tesseract/qpdf, Acrobat/Chrome
PDFium/Preview/Poppler viewer, OS-native provider quota/sandbox, upstream PR, dist/build/release,
new Producer commit, or live Host fleet/consumer receipt is claimed. The checked-in dist remains
outside this round and must be rebuilt from the approved source only after the provenance rebind.
All external, full-suite, build, dist, reproducibility, release ZIP, Producer commit, and Host
consumer gates remain mandatory and unwaived.

## Round 14 — PDF read honesty and pypdf mutation safety hardening

### Scope and role separation

Round 14 is a fresh native subagent review of the source/test delta against Producer baseline
`28f3fdce26e7d45513fb9023d89eff006177e256`. The reviewer inspected exactly these release inputs:

- `src/document_skills_core/formats/pdf/content_streams.py`
- `src/document_skills_core/formats/pdf/read.py`
- `src/document_skills_core/providers/pypdf/operations.py`
- `src/document_skills_core/providers/pypdf/safety.py`
- `tests/test_pdf_operations.py`
- `tests/test_pdf_public.py`

The reviewer did not author or edit source, tests, generated artifacts, provenance, or this report.
The review was limited to the new PDF read truthfulness, pypdf mutation-safety gates, and shared
facade regression; it did not independently re-review the historical implementation.

### Findings and closure

- Unmapped Type0/CID bytes are no longer projected as Latin-1 text. Only text carrying proven
  `/ActualText` semantics survives for that unsupported font path; an affected page reports
  `text_extraction_unavailable` when no readable block remains and emits the schema-valid
  `DS_PDF_TEXT_EXTRACTION_UNAVAILABLE` warning.
- Caller-selected block limits now emit `DS_PDF_READ_TRUNCATED`. Independent review found and the
  producer closed three successive Majors: the original silent 5,000-block slice; a raw sentinel
  that could discard later readable Type1/ActualText after 5,001 unmapped CID blocks; and the
  aggregate-memory regression in the first full-operator fix. The final implementation processes
  one page at a time, filters unsupported semantic text before applying the caller projection,
  compacts each page before aggregation, and combines omission/truncation evidence across pages.
- `pdf.encrypt` and `pdf.compress` now Core-parse unencrypted sources before pypdf mutation;
  `pdf.decrypt` Core-parses the private decrypted candidate before validation or promotion.
  JavaScript, external actions, and executable embedded content therefore fail closed with
  `DS_ARCHIVE_UNSAFE`, preserving both the source and any existing destination.
- A direct public regression proves that the `document-pdf` wrapper dispatches a registered
  `docx.read` request through the shared registry to `core-python`; the PDF provider does not
  claim or process the foreign operation.

The conservative Type0 path does not yet decode ToUnicode-only CID text when `/ActualText` is
absent. This is an explicit under-extraction capability limit, not fabricated output: affected
bytes are omitted and the limitation is surfaced. It is not treated as a release finding in this
round.

### Independent verification receipts

| Command or check | Result |
| --- | --- |
| Final focused PDF read, CJK/RTL, pypdf malicious/happy-path, wrong-password atomicity, and wrapper dispatch suite | PASS — 28 passed |
| Independent two-page omission/truncation aggregation probe | PASS — one combined warning per kind; readable Type1 text survived semantic filtering |
| Ruff over the six source/test delta files | PASS — all checks passed |
| Strict UTF-8, BOM, U+FFFD/mojibake scan over the six delta files | PASS |
| `git diff --check HEAD` | PASS |
| Materialized runtime-source allowlist | PASS — includes the new `providers/pypdf/safety.py` runtime source |
| Two consecutive prospective mapping calculations | PASS — both returned `b81cfd16d52d1a4e868ab98655560cd348bec6d3c2353ea60a3895241803e674` |
| Regenerated CycloneDX SBOM comparison | PASS — unchanged SHA-256 `477eb8d13f7ec594a4e31d595b07e917e6d05e0b4e585043e25a53e033c5a4f8` |

### Round-14 approval and remaining delivery gates

`approval_claimed: true`; `status: clean`. Final independent verdict:
`CLEAN — Blocker:0 Major:0 Minor:0 Trivial:0`. Round 14 supersedes the Round-13 prospective
mapping because the six reviewed source/test files and materialized runtime-source allowlist are
release inputs. The exact approved prospective mapping is:

`b81cfd16d52d1a4e868ab98655560cd348bec6d3c2353ea60a3895241803e674`.

Attestation identity:
`codex-reviewer/document-skills-core-pdf/native-pdf-independent-review-rounds-1-14-0.5.5-2026-08-27`.

This approval authorizes only the official reuse-review provenance rebind and generated audit
receipt for this exact frozen source/test snapshot. No remote CI, native Poppler/Tesseract/qpdf
or viewer execution, final dist/release reproducibility, Producer commit, or live Host consumer
receipt is claimed here; those remain LEAD delivery gates.

## Round 15 — Windows lock-fixture full-suite startup budget

### Scope, evidence, and role separation

The first full `npm run verify` on Producer commit
`cf2ea23c27feaeff72105070dedca41b8b0e7586` completed with 1,614 passed and seven
platform skips, but one existing `workspace-lock-transient` harness process exceeded its outer
15-second `subprocess.run` deadline under full-suite load. The failure occurred outside any PDF
operation assertion: the process did not return before the test could read its trace. Three
immediate isolated reruns passed in approximately 4.2 seconds each.

The producer changed exactly one release input, `tests/test_pdf_public_worker_failures.py`.
Windows `workspace-lock-transient` and `workspace-lock-permanent` fixture processes now receive a
30-second outer harness deadline; every non-lock case retains 15 seconds. This deadline includes
fresh `uv` startup, imports, and copying `src`/`schemas` into a temporary sandbox before the
supervisor is measured. The product contract remains separately and unchanged enforced by
`trace["supervisor_elapsed_seconds"] < 5.0`, along with exact cleanup-attempt counts, lock release,
identity-replacement blocking, residual-entry, and fixture-cleanup assertions. No production
source, supervisor/worker timeout, or cleanup policy changed.

The fresh native non-author reviewer authored no code, test, provenance, or report change. Its
read-only review returned `CLEAN — Blocker:0 Major:0 Minor:0 Trivial:0` after both Windows lock
cases passed in focused execution and their `<5.0s` product trace assertions remained active.
Strict UTF-8/no-BOM checks and `git diff --check` also passed.

### Round-15 approval

The regenerated SBOM remains byte-identical at SHA-256
`477eb8d13f7ec594a4e31d595b07e917e6d05e0b4e585043e25a53e033c5a4f8`. Two consecutive
prospective mapping calculations returned:

`8a8b0f188b56fe74dd4f248e69366c7447733b2dbe06a7c16cf35c8ef71e449a`.

`approval_claimed: true`; `status: clean`. Round 15 supersedes the Round-14 prospective mapping
only because the reviewed test file is a release input. Attestation identity:
`codex-reviewer/document-skills-core-pdf/native-pdf-independent-review-rounds-1-15-0.5.5-2026-08-27`.
This approval authorizes the single-attestation provenance rebind for the exact frozen snapshot;
a fresh complete verify/build/release run remains mandatory delivery evidence.

## Round 16 — Merged-main integration review

### Scope and role separation

Round 16 is a fresh native non-author review of the local merge that combines Producer PDF HEAD
`af15dbafbe0f993248364ea5b744cac27f10e08a` with main integration commit
`3bf90cbc7cbeea4afaa4fdba99dddca5b42aa374`. The reviewer inspected the conflict-resolved
workflow, shared CLI/process/supervisor boundaries, provenance and SBOM generators, fixture
manifest, DOCX public-test support, and supply-chain tests. The reviewer authored no production
source, test, workflow, provenance, generated artifact, stage, or commit change; all three
integration fixes below were made by the merge producer and then independently re-reviewed.

### Findings and closure

- **Blocker — invalid workflow mapping indentation:** the optional DOCX evidence upload step had
  `path` and `if-no-files-found` indented one column beyond the sibling `name` field. The producer
  aligned the fields and the reviewer confirmed the corrected workflow delta.
- **Blocker — missing `Path` import after cross-hunk auto-merge:** `tests/test_strategy2.py`
  retained PDF-parent `Path` annotations while main removed the import in a separate hunk. The
  producer restored `from pathlib import Path`; Ruff passed and pytest collection found all 108
  tests in the file.
- **Minor — lost SBOM identity regression:** the merged supply-chain implementation retained the
  dual-manifest `_plugin_identity()` check, but the PDF-parent test proving that the SBOM matches
  both plugin manifests was absent. The producer restored the exact regression; it and the
  deterministic lock/SBOM test passed, and Ruff passed for the edited test file.

The reviewer found no remaining Blocker, Major, Minor, or Trivial integration issue after these
closures. The combined runner retains the atomic executable lease, private workspace identity,
fixed environment, and bounded process semantics. The combined supervisor retains fileless
framed IPC, the canonical worker boundary, per-format timeouts, and output ceilings. CLI path
rebasing, the PDF provider surface, DOCX/PPTX/XLSX additions, exact provenance classification,
fixture hashes, and NuGet-aware SBOM generation remain composed rather than selecting one parent.

### Independent verification receipts

| Command or check | Result |
| --- | --- |
| Conflict-focused source/workflow/test review and post-fix rereview | PASS — all three integration findings closed |
| Ruff over conflict-related Python and both producer-edited test files | PASS; main's intentional star-import thin-test structure was separately exercised by pytest and was not treated as a merge regression |
| `pytest --collect-only tests/test_strategy2.py -q` | PASS — 108 tests collected |
| Focused provenance/SBOM regression set | PASS — 11 passed; fixture audit count 101; checked-in SBOM audit passed |
| Combined `test_strategy2.py` plus `test_supply_chain.py` attempt | INCONCLUSIVE — exceeded the 10-minute reviewer command ceiling with no failure output; the exact residual process was cleaned up and the run is not claimed as pass or fail |
| Strict UTF-8/no-BOM/U+FFFD scan and `git diff --check` | PASS |
| Regenerated CycloneDX SBOM | PASS — SHA-256 `197d8ef753b665b8d22810a476fd07de1bca9039476933b05206fd8465472b08` |
| Two consecutive prospective mapping calculations over the frozen non-metadata release bytes | PASS — both returned `88efbf5ef9fd1bc51b708180d7808daf81ecc192ab728bc6c44d5c67fde4ca5a` |

### Round-16 approval and remaining delivery gates

`approval_claimed: true`; `status: clean`. Final independent merge-integration verdict:
`CLEAN — Blocker:0 Major:0 Minor:0 Trivial:0`. Round 16 extends the composite review only to the
conflict-resolved main-to-PDF integration and the three closure edits above. The exact approved
prospective mapping is:

`88efbf5ef9fd1bc51b708180d7808daf81ecc192ab728bc6c44d5c67fde4ca5a`.

Attestation identity:
`codex-reviewer/document-skills-core-pdf/native-pdf-independent-review-rounds-1-16-merged-main-integration-0.5.5-2026-08-28`.

This approval authorizes the official two-stage reuse-review provenance rebind and generated audit
receipt for this exact frozen integration snapshot. It does not claim that the reviewer reran the
complete test suite. A fresh complete verify/build/release and reproducibility run, remote CI,
native optional-provider/viewer coverage, Producer delivery, and live Host consumer receipt remain
mandatory and unwaived delivery gates.
