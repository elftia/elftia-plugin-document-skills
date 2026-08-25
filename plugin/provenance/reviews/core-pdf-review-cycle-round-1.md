---
status: clean
approval_claimed: true
identity: codex-reviewer/document-skills-core-pdf/native-pdf-independent-review-2026-08-25
reviewer: "Codex native non-author review team/process: PDF completion 2026-08-25"
scope: all-release-artifacts
identity_assurance: self-asserted
identity_limitations: >-
  Self-asserted composite native Codex non-author review-process identity on
  local Windows; it cannot cryptographically prove the service principal or
  claim that one individual reviewer executed all rounds.
  The nested reviewer `/root/pdf_independent_review/pdf_independent_review`
  executed round 1; its non-author parent `/root/pdf_independent_review`
  executed rounds 2 and 3. The fresh non-author reviewer
  `/root/pdf_final_independent_review` executed rounds 4 through 6. Round 2
  re-reviewed only the fixer delta against the six round-1 findings; rounds 3-6
  reviewed the generated artifacts and final deltas described below. The review
  process could not execute remote CI, a live host consumer, Poppler, Tesseract,
  or qpdf, and does not claim OS-level resource-quota or current host-fleet
  evidence.
reviewed_mapping_sha256: 03359057d7502b9921d844ace98fa95c226fe3ced4b50746680b22041a490965
report_evidence: provenance/reviews/core-pdf-review-cycle-round-1.md
baseline: cbdb7523f13e2290ba377c7c62e18df24f3a7afd
review_round: 6
review_mode: post-commit-whitespace-provenance-rebind
---

# PDF completion independent review - rounds 1-6

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
`rewrite_fonts.py` and rebinds provenance to the resulting file identity. None of the delta
reviews restarted or generalized the review over the full historical implementation diff. No
reviewer authored the production fixes or generated artifacts. This canonical report and the
round-6 provenance metadata are the only files written by the round-6 reviewer.

**Verdict: clean; approval claimed.** All four round-1 Blockers and both round-1 Majors are
closed by source inspection, independent public supervisor/worker reproductions, exact object
and byte-preservation checks, and focused regression runs. No new Blocker or Major was found in
the fixer delta, final PDF delta, or scoped generated-artifact deltas. The final mapping digest
above is approved for this reviewed snapshot. Round 6 rebinds `plugin/provenance/modules.json`
to one exact attestation whose report hash is derived from these canonical bytes.

## Review-cycle history and disposition

| Round | Native non-author executor | Responsibility |
| --- | --- | --- |
| 1 | `/root/pdf_independent_review/pdf_independent_review` | Full initial review; recorded four Blockers and two Majors. |
| 2 | `/root/pdf_independent_review` | Fixer-delta re-review; independently reproduced closure evidence for the six findings. |
| 3 | `/root/pdf_independent_review` | Generated-artifact delta review; verified allowlist, SBOM, provisional mapping, and final prospective digest. |
| 4 | `/root/pdf_final_independent_review` | Fresh final-delta and generated-artifact review; closed B5/B9/B10, revalidated final walker bytes, and approved the current mapping. |
| 5 | `/root/pdf_final_independent_review` | Reopened review after four full-suite failures; verified the three exact fixes, focused 19-test closure, and regenerated artifacts. |
| 6 | `/root/pdf_final_independent_review` | Narrow review of one removed terminal LF; provenance report/modules/runtime/audit rebinding to the resulting exact mapping. |

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

## External limitations retained from round 1

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
with focused evidence. The approved mapping identity for the current provisional snapshot is
`03359057d7502b9921d844ace98fa95c226fe3ced4b50746680b22041a490965`.
This approval is issued by the composite native Codex non-author review process described above:
the child reviewer owns the round-1 findings, its parent owns the round-2 closure and round-3
generated-artifact checks, and `/root/pdf_final_independent_review` owns rounds 4-6. Historical
digests `810403...`, `c0f210...`, `d2bba3...`, and `369627...` are not valid for binding. Round 6
does not modify production source/tests, stage, commit, archive, or ship. The post-fix full
npm-suite delivery gate remains satisfied by the round-5 receipt; round 6 separately proves the
subsequent source delta is one terminal LF only.
