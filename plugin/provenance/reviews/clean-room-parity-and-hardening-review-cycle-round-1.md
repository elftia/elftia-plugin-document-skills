---
status: clean
approval_claimed: true
identity: claude-reviewer/fresh-non-author-round-1-delta (claude-opus-5[1m])
identity_limitations: "cannot execute live Electron dogfood or remote macOS/Linux CI; does not attest to Anthropic restricted material absence beyond the clean-room audit's exact-inventory method"
reviewed_mapping_sha256: b4c9d571b5d54501eb0cfef7cc610b3a5b66d349de42d46d4f1084510f3287f5
---

## Summary

Round-1 re-review of the fix delta for Major-1 (core-node docx-template
crash-isolation test). The fixer added `test_core_node_template_crash_isolation`
to `tests/test_provider_crash_isolation.py`, parametrized over PROVIDER_FAILED
(crash) and PROCESS_TIMEOUT (timeout). The test exercises the real
`docx.template.apply` dispatch via `execute_request`, monkeypatches
`apply_template_with_node` at the module-level seam in `service.py`, and
asserts source SHA unchanged + no partial output promoted + host survives +
correct error code in the result.

The seam is genuine: `service.py` imports `apply_template_with_node` at module
level (line 31) and calls it as a bare name at line 221, so the monkeypatch
intercepts the real dispatch path. The `finally` block (line 259) enforces the
primary per-part SHA preservation gate. Staged output lives inside
`OperationTempRoot` and `promote_candidate` is never reached on failure.

Two fresh adversarial probes independently confirmed containment: (1) partial
bytes written to staging before crash — real output never promoted; (2) delayed
hang then timeout — identical containment. Both probes were deleted after
execution.

The fix is purely additive (test file only, zero `src/` changes). The primary
per-part SHA preservation gate and the docx template transaction are unchanged.
Full suite 772/772 green. Zero new Blocker/Major.

## Verdict

APPROVED — Major-1 resolved, zero new findings.
