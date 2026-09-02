# DOCX template packs and reference import — final independent review

- Date: 2026-09-02
- Repository: `elftia-plugin-document-skills`
- Branch: `change/main/01714f3c-ecc2-4a64-a79d-154c1ddb75f6/docx-template-packs-and-reference-import`
- Base: `1a46440c4a966130620b95fbae633f4b87b3f9da` (`origin/main`)
- HEAD: `37e9da174ad70eaf3c81c14b0a6db2955019faf5` (tree `4733a49577053190f224d374a72939e818c74977`)
- Implementation commit: `b8cca8ca18341aefac19140628be46e38961a48c` (merged with base at `8271dac`)
- Reviewer: Claude independent final reviewer
- Reviewer identity: `claude-reviewer/elftia-plugin-document-skills/docx-template-packs-final`
- Runtime / role: `claude` / `reviewer`
- Identity assurance: `self-asserted`
- Scope: `all-release-artifacts`
- Status: `clean`
- Approval claimed: `true`
- Reviewed mapping SHA-256: `a1c9d28fbcec6472ca9170bb51e850a06f220b27cbd3071609de083f715115e1`

## Verdict

**CLEAN** — **0 Blocker, 0 Major, 0 Minor** on the final release candidate at
HEAD `37e9da174ad70eaf3c81c14b0a6db2955019faf5`. All three findings left open by
the 2026-09-01 final independent verifier (two Office data-loss Blockers and
one concurrent .NET authorization Major) are resolved on the current tree, by
this reviewer's own code inspection and by focused regressions this reviewer
selected and ran. The delta since the last reviewed candidate (commits
`21adbf5`, `c1ce904`, `763a5c9`, `37e9da1`, and merge `8271dac` against
`origin/main@1a46440`) contains no new Blocker or Major: its only product-code
change tightens the LibreOffice forbidden-token match to argv-argument
boundaries and fails closed for unknown token shapes. Every identity,
mapping, audit, package, and retained-test evidence check reproduced exactly.

This reviewer performed no product/test implementation, no tasks.md or
run-state write, no commit or push, no provenance binding, and no release
output generation. Writes were limited to this report, the change evidence
append, and the reviewer DONE marker.

## Findings resolution

### 1. [Blocker] PID/HWND reuse after the sole creation-time check — RESOLVED

Required remediation was to bind the target to an opened process object,
validate creation time and image against that held object, and terminate and
await that exact object while preserving tree cleanup. On the current tree,
`_cleanup_owned_office_process` (`consumer_validation/office.py:759`) passes
all of its integer-observation gates (start FILETIME, HWND owner, image,
tri-state visibility, pretermination snapshot), then opens the target with
`_open_held_office_process` (`office.py:603`) using
`PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE | PROCESS_TERMINATE`. The
returned `_HeldWindowsProcess` (`office.py:58`) reads its creation FILETIME and
image name through that handle, and inside the `with target:` block the code
revalidates `creation_filetime` and `image_name` on the held object
(`office.py:842-849`) before any destructive act. Termination goes through
`_terminate_tree(pid, target=target)` (`office.py:851`) into
`_terminate_held_tree` (`office.py:1161`), which re-checks the held object is
running, takes two full process snapshots and requires the descendant set and
every descendant record to be identical across both, opens a held object for
each descendant with image validation, and only then calls
`target.terminate()` — `TerminateProcess` on the held handle — followed by
`target.wait()` on the same handle. The kernel object reference is the
capability; a recycled PID integer can no longer substitute a different
process at the destructive boundary.

The required deterministic regression exists and passed in this reviewer's
run: `test_office_cleanup_rejects_process_object_swap_after_initial_identity_check`
swaps the process object to FILETIME 456 after every integer check on the
reported FILETIME 123 has passed and asserts `_terminate_tree` is unreachable
and the held object is closed. Supporting nodes also passed:
`test_office_cleanup_terminates_fully_bound_fresh_process` (positive
invisible owned case terminates exactly the held object),
`test_office_cleanup_accepts_target_exit_before_exact_handle_termination`,
`test_bound_office_tree_terminates_parent_before_held_descendants`, and
`test_bound_office_tree_closes_every_open_handle_before_failed_validation`.

### 2. [Blocker] EnumWindows failure read as invisibility — RESOLVED

Required remediation was an explicit three-state result with unknown
rejecting termination. `_has_visible_window` (`office.py:986`) now returns
`bool | None`: it clears the Win32 last-error state, captures the
`EnumWindows` boolean, records `observation_failed` when the callback's owner
lookup fails, and returns `None` for observation failure, for enumeration
failure (zero return without a callback stop), and for any exception. Only a
complete enumeration with no visible owned window returns `False`
(`office.py:1018-1024`). The consumer requires exactly that authoritative
negative: `if visible is not False: return False` (`office.py:824`), so both
`True` and unknown reject termination — fail closed at the destructive
boundary.

The required regressions exist and passed in this reviewer's run:
`test_office_cleanup_rejects_failed_visible_window_enumeration` supplies an
`EnumWindows` that returns zero without delivering the callback (last error 5)
and asserts `_terminate_tree` is never called, while the positive
invisible-owned case is retained in the fully-bound termination test above;
`test_visible_window_observation_is_explicitly_tristate` pins the tri-state
contract parametrically; `test_owned_office_cleanup_never_terminates_preexisting_or_visible_process`
and the ambiguous/inconsistent identity matrix
`test_office_cleanup_rejects_incomplete_ambiguous_or_inconsistent_identity`
also passed.

### 3. [Major] Concurrent leases through one mutable runner executable — RESOLVED

Required remediation was an immutable, context-local executable launch
binding carried in the operation lease and used by every helper invocation,
retaining the per-launch identity recheck. On the current tree,
`DotnetOpenXmlRunner` no longer holds a shared mutable `_executable` as
command authority: `set_executable` (`providers/dotnet/runner.py:129`) returns
an immutable frozen `ExecutableBinding` without mutating state;
`_authorization_for_operation` (`providers/dotnet/service.py:105`) feeds the
detector's `detect_and_authorize` a bind callback that must produce exactly
one `bind_authorized_executable` record (otherwise the evidence fails closed
as unavailable), and projects it with `launch_runner = self.runner.bind(bindings[0])`
(`service.py:143`) into a `DotnetOpenXmlLaunch` façade (`runner.py:62`) that
carries that one binding into every run. The `_OperationAuthorization`
(`service.py:35`) stored in the `ContextVar` lease holds both the evidence
and this launch runner, and every public callable passes
`authorization.runner` to its helpers. `DotnetOpenXmlRunner.run` accepts the
binding explicitly (`runner.py:152-166`) and `ProcessPolicy.acquire_executable`
re-validates the binding's identity against the approved identity at every
launch, so the per-launch recheck is retained.

The required barrier-based regression exists and passed in this reviewer's
run: `test_dotnet_operation_lease_keeps_distinct_launch_bindings_per_command`
runs two concurrent commands that authorize two distinct executable paths
(`dotnet-A.exe` / `dotnet-B.exe`) behind a barrier that forces detection
interleaving, then asserts each command's evidence path and every launched
binding remain per-command aligned; the fake runner deliberately retains a
shared-field fallback and the assertion proves it is never consulted.
Supporting nodes also passed:
`test_dotnet_operation_lease_isolates_concurrent_commands`,
`test_dotnet_operation_lease_resets_after_nested_and_exceptional_commands`,
`test_registry_resets_entered_leases_when_later_hook_entry_fails`, the three
single-detection public-command tests (pptx schema, docx revisions, docx
comments), and the executable-identity suite including same-path replacement
rejection, final-launch-window object execution, Windows hardlink-alias
blocking, and post-probe replacement rejection.

## Identity and mapping evidence

All checks below were recomputed by this reviewer on the execution worktree,
not read from the fixer's artifacts.

- `git rev-parse HEAD HEAD^{tree}` returned exactly
  `37e9da174ad70eaf3c81c14b0a6db2955019faf5` and
  `4733a49577053190f224d374a72939e818c74977`; `git status --porcelain`
  shows only `?? .rasen/`; `git ls-files --others --exclude-standard -- .
  ':(exclude).rasen/**'` is empty; the branch name matches the change branch.
- `uv run --frozen python -m tools.regenerate_provenance --project-root .
  --print-mapping-only` printed exactly
  `a1c9d28fbcec6472ca9170bb51e850a06f220b27cbd3071609de083f715115e1`,
  equal to the frozen candidate identity's `pending_mapping_sha256`.
- `uv run --frozen python -m tools.audit --project-root .` exited 2 with
  status `fail` carrying exactly one error — `Independent review attestation
  is missing` under check `provenance` — while clean_room (826 module
  records), inventory (1093 classified = 1093 files, 826 risky),
  execution_boundary, commands (21), fixtures (109), manifests, public_skills
  (4), and sbom all pass. This is the correct pre-binding state.
- Candidate ZIP `candidate-release/0.5.6/document-skills.epkg` hashes to
  `32d1796a4fba96dc93e86daaf21b113c0e5e96e6738fedf8f16e38bba15025cc` over
  2,812,639 bytes, matching the frozen identity byte-for-byte.
- Both round 8 tier verdicts cross-check against their JUnit XMLs by this
  reviewer's independent parse: fast 2601 total / 2592 passed / 9 skipped /
  0 failed / 0 errors, terminal summary identical, launcher exit 0; slow 108
  total / 100 passed / 8 skipped / 0 failed / 0 errors with 2601 deselected,
  terminal summary identical, launcher exit 0. Both after-files record
  `drift.ok = true` with unchanged HEAD, committed tree, and index tree.
- `producer-chain/chain-results.txt` records `CHAIN_OK=1` with all ten
  stages at `REAL_EXIT_CODE=0` at the same HEAD and tree, ending
  2026-09-02T04:57:26Z.
- The self-referential metadata seam is correctly configured for this change:
  the merge resolution at `8271dac` sets `CURRENT_REVIEW_ARTIFACT` in
  `plugin/tools/provenance_records.py` to this report's path, so writing
  these bytes cannot move the reviewed mapping digest.

## Verification evidence

- Focused regressions run by this reviewer, serially, with the round 8
  environment (`DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=0`, `PYTHONUTF8=1`,
  `PYTHONIOENCODING=utf-8:strict`): 22 Office termination-authority nodes,
  16 .NET lease / executable-identity nodes, and 14 LibreOffice
  forbidden-token nodes — **52/52 passed, 0 failed, 0 skipped**.
- Delta review of `21adbf5` (bounded pytest workers, slow-tier markers,
  LibreOffice argv-boundary token matching), `c1ce904` (product cold-start
  budget for non-hang supervisor fixture modes), `763a5c9` (protocol test
  moved to the slow tier), `37e9da1` (docx dist e2e restores the staged
  artifact by removing the `node_modules` its `npm ci` created), and merge
  `8271dac` versus `origin/main@1a46440`. The merge's only hand-resolution
  beyond taking one side is `CURRENT_REVIEW_ARTIFACT` in
  `provenance_records.py`; the provenance manifest resolutions are proven
  coherent by the exact digest and single-error audit reproduced above.
  No new Blocker or Major.
- Slow-tier rerun diagnostics for the one transient round 8 failure
  (`test_core_only_profile_runs_real_public_smokes` 60-second budget under
  machine load, pre-existing budget, manual reproduction green) were read and
  accepted as environmental; the retained slow-tier rerun at this HEAD is the
  evidence of record.

## Limitations

This reviewer identity is self-asserted by the Claude runtime; the repository
cannot cryptographically prove which service or human principal operated this
review session, and this review does not cover compromised runtimes,
operating systems, native code, or future code outside the reviewed
inventory. Real Office processes were not launched by this reviewer; the
termination authority was verified by code inspection plus the deterministic
seam regressions the prior verifier's findings demanded. The tier JUnit,
drift, and producer-chain evidence was cross-checked as retained artifacts
rather than re-executed end to end, except for the focused regression subset
and the read-only digest/audit recomputations listed above.

The attestation seed below records `report_sha256` as the SHA-256 of this
report with that one field zeroed (64 `0` characters), because a file cannot
contain its own final hash; the binding tool overwrites `report_sha256` from
the final report bytes on disk, and the change DONE marker records the final
on-disk hash for tamper evidence.

## Durable findings

- Destructive ownership is now object-bound end to end in the Office seam:
  the held handle is the capability, integer observations are only gates.
  Future destructive cleanup should copy this pattern rather than re-derive
  PID-based authority.
- The argv-boundary forbidden-token match in the LibreOffice runner keeps a
  conservative substring rule for unknown token shapes; any new
  `FORBIDDEN_TOKENS` entry without an explicit boundary rule silently
  inherits the substring behavior and should get a boundary rule plus a
  regression at introduction time.
- `scripts/run-xlsx-dist-e2e.mjs` still leaves `node_modules` inside its
  artifact root after `npm ci`, the exact pattern `37e9da1` fixed for the
  docx e2e; it predates this change (from main `f8c7669`) and is not
  exercised by this change's producer chain, but the next chain that
  validates after an xlsx e2e will fail until it gets the same finally-block
  restore.

## Ready-to-bind attestation seed

The LEAD binds mechanically from this seed; this reviewer did not run any
binding. The `report_sha256` convention is documented under Limitations.

```json
{"review_attestations": [{"id": "docx-template-packs-final-claude-2026-09-02", "reviewer": "Claude independent final reviewer", "identity": "claude-reviewer/elftia-plugin-document-skills/docx-template-packs-final", "identity_assurance": "self-asserted", "identity_limitations": "Self-asserted Claude reviewer identity; the repository cannot cryptographically prove which principal operated this session, and this review does not extend beyond the reviewed inventory to compromised runtimes or future code.", "runtime": "claude", "role": "reviewer", "approval_claimed": true, "report_evidence": "provenance/reviews/docx-template-packs-and-reference-import-review.md", "report_name": "docx-template-packs-and-reference-import-review.md", "report_sha256": "ef6a88ec0e0d53ae12127636bed9796653fa27bfa7f173fe96ea8a423a287ea3", "reviewed_mapping_sha256": "a1c9d28fbcec6472ca9170bb51e850a06f220b27cbd3071609de083f715115e1", "scope": "all-release-artifacts", "status": "clean"}]}
```
