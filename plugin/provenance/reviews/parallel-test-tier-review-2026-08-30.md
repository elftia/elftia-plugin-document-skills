# Review — parallel test tier (pytest-xdist) and gate restructure

Date: 2026-08-30
Scope: all release artifacts at this mapping.
Change under review: the pytest layer of `npm run verify` was fully serial
(~2h47m measured on the packaging machine, paid in full by every fleet
re-pin after content moves). This change runs it in two phases — everything
except the `slow` mark in parallel (`-n auto --dist loadscope`), then the
`slow` tier (real external providers: dotnet helper, LibreOffice, PDF
rendering) serially, because the dotnet helper is a shared on-disk build
target that deadlocks under parallel workers (measured). Gate strength is
unchanged: the full set, including slow, still runs. `DS_PYTEST_SERIAL=1`
restores the exact previous single-process behavior.

Source surface: `plugin/pyproject.toml` (+pytest-xdist 3.7.0 dev dep,
`slow` marker), `plugin/tests/conftest.py` (UV_NO_SYNC=1 for spawned
`uv run` children — the gate syncs the environment up front; parallel
children re-validating it fight over uv's lock), four test modules marked
`slow`, `scripts/run-plugin-checks.mjs` (two-phase), root `package.json`
(`test:fast`), README, `provenance/dependency-allowlist.json` (execnet
2.1.2 + pytest-xdist 3.7.0 registered), `provenance/dependency-licenses.json`
and `THIRD_PARTY_NOTICES.md` (both MIT), regenerated `sbom.cdx.json`,
`provenance/modules.json`, `provenance/audit-report.json`.

Measured evidence:
- Serial baseline (before): 2550 passed / 11 failed / 2 errors in 2:47:22 —
  the failures were environmental (dotnet build residue, LibreOffice
  provider availability), reproduced and classified independently.
- Slow tier serial (after): 22 passed in 14:28.
- Fast tier parallel (after, under full packaging-chain load): the
  previously-failing uv-spawn family re-verified green at `-n 4` with
  UV_NO_SYNC=1; the supply-chain family green after allowlist/SBOM/notices
  registration.
- xdist smoke: `-m "not slow"` deselects exactly the three marked
  real-LibreOffice tests (79 → 76); the remaining 76 pass parallel.

Independent reviewer verdict (codex, read-only sandbox):

- identity: codex-reviewer/elftia-plugin-document-skills/aug30-infra-supplychain
- mapping digest: 893e523c948e06d67ac567e4b325af06790df1efb1b5df7fbee338dee84b0f45
- status: clean
