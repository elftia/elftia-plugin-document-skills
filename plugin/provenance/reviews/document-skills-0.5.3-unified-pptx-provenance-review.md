# CLEAN — Document Skills 0.5.3 PPTX Ecosystem B/C B1 Provenance Review

Date: 2026-08-25

## Verdict

Status: `clean`

Approval claimed: `true`, limited to the exact all-release-artifact mapping, source and data
classifications, review-evidence binding, and supply-chain claims in this report. This is not a
general implementation-fidelity, remote-platform, legal-license, or maintainer release approval.

Canonical findings after review: **0 Blocker, 0 Major, 0 Minor, 0 Trivial**.

The approved mapping contains **429 release files**: **327** risky module records, **99**
exact-hash data classifications, **0** executable exclusions, and exactly **3** self-referential
metadata exclusions. Its SHA-256 is:

`21a9173ccedc69bd6daf4c49fdac0b4e67b849d57c4398fa11ba24a03315ce85`

## Reviewer

- Reviewer: `OpenAI Codex independent provenance reviewer: pptx-ecosystem-phase-bc-b1/2026-08-25`
- Identity: `codex-reviewer/pptx-ecosystem-phase-bc-b1/gpt-5-2026-08-25`
- Runtime: `codex`
- Role: `reviewer`
- Scope: `all-release-artifacts`
- Identity assurance: `self-asserted`
- Identity limitations: This self-asserted reviewer cannot cryptographically prove the backing
  model, service principal, or human operator and does not establish remote-platform execution,
  professional penetration testing, legal-license review, or final maintainer approval.
- Attestation id: `document-skills-0.5.3-pptx-ecosystem-phase-bc-b1-review`

No pre-generated candidate, previous attestation, historical clean verdict, author description,
or existing hash was treated as current approval evidence. Historical review reports were used
only as exact-hashed release data. The canonical report path is reused because the generator and
validator intentionally allow exactly that current-review location; its prior identity, date,
mapping, findings, and conclusions are not reused.

## Review scope and delta

This review covers the release bytes visible on branch
`feat/pptx-ecosystem-phase-bc-implementation` at `14db457` plus the current B1 staged and unstaged
working-tree bytes. It also binds PPTX ecosystem B/C artifacts that had already entered the tree
after the previous review but were not represented by its 411-file mapping.

Compared with that previous mapping, the reviewed candidate adds eight risky artifacts: the
presentation-contract adapter, the sanitizer and its inventory helper, the B/C fixture generator
and support module, and three focused test modules. It adds ten exact-hash data artifacts: the
sanitizer Skill reference, the B/C contract-pin pair, the B/C README, and three generated PPTX
fixtures with their adjacent manifests. Eight existing risky files and three existing data files
have new hashes. No previously mapped artifact is removed.

## Independent inventory and classification review

- The shared release inventory and independent candidate agree on 429 unique regular-file paths:
  327 risky artifacts, 99 hash-bound data artifacts, and the three exact self-referential metadata
  paths. There are no executable exclusions, symlinks, duplicate paths, classification overlaps,
  or unclassified release files.
- The risky set is 306 Python files, 17 Node `.mjs` files, one C# source file, one `.csproj`, one
  execution-bearing `.gitignore`, and one extensionless execution-bearing file. The static
  execution-boundary audit identifies 323 Python/Node source files.
- The runtime-source allowlist was regenerated from exact current files and adds only
  `presentation_contracts.py`, `template_sanitize.py`, and
  `template_sanitize_inventory.py`. A second generator run reproduced the checked-in allowlist
  byte-for-byte with SHA-256
  `f245b42867e2b2fd610e84b08f8339425284b33d31387d6fb10d9e4fb3f1afea`.
- The fixture inventory contains 35 globally registered fixtures. The three new sanitizer PPTX
  archives pass ZIP CRC inspection, and every adjacent manifest and global-manifest SHA-256 agrees
  with the checked-in payload.

## Source, license, and execution-surface review

- The new sanitizer source performs bounded archive inspection, rejects active or signed packages
  closed, removes external and OLE relationships, literalizes chart caches, purges unreachable
  parts, and reopens the written package for postflight and deep validation. The review found no
  path that turns the sanitizer into a general archive extractor or native execution surface.
- Searches of the new runtime sources found no copied-source copyright or SPDX header, upstream
  repository attribution, MiniMax, Anthropic, claude-office, or MCP implementation reference; no
  dynamic import, `eval`, `exec`, network client, or runtime subprocess surface was introduced.
  The only subprocess in the reviewed B1 delta is test-side and uses an argument vector with
  `shell=False`.
- All 327 risky records remain classified `original`, `clean_room: true`, `GPL-3.0`, with empty
  `third_party_files`. This is a provenance classification backed by source review, not a legal
  opinion about every interface, format specification, or host-provided dependency.
- The deterministic CycloneDX SBOM still matches the frozen dependency policy and has SHA-256
  `a8d871e521169509b6a109bf4ee342e961b985d282589e4d3d3964a58757fa2d`.

## Fixture and test evidence before binding

The owner-contract fixture check completed successfully against
`packages/presentation-contracts`: three B-TPL consumer fixtures, four owner fixtures, seven
artifacts, manifest SHA-256
`78989d9891c80a3f89ad25d7d31e4a431737131226df4494fc14dee1bfe3215a`, and deck-content SHA-256
`abdb56ca2e0d47c2ba6115e10f52c0bbab5ba155a19c096b892c2d45948fd5a1`.

Focused PPTX sanitizer/ecosystem/contracts tests passed **40/40**. DOCX fixture tests passed
**12/12**. The Node reproducibility suite passed **3/3** and explicitly asserted 21 reviewed binary
payloads. Before rebinding, the 40-case supply-chain suite passed 39 cases and failed only the
machine-readable-report equality case because the checked-in audit still described the prior
mapping. The 95-case Strategy2 suite passed 94 cases and failed only its rebound-baseline case
because the checked-in runtime-source allowlist still omitted the three newly discovered Python
files. After the allowlist regeneration, the machine audit passed fixtures, inventory, execution
boundary, commands, manifests, public Skills, clean-room, and SBOM checks; its only remaining error
was the intentionally stale all-file mapping that this review binds.

The exact commands were:

```text
uv run --frozen python tests/fixtures/pptx/ecosystem_bc/generate.py <presentation-contracts-root> --check
uv run --frozen python -m pytest -q tests/test_pptx_template_sanitize.py tests/test_pptx_ecosystem_fixtures.py tests/test_pptx_presentation_contracts.py tests/test_pptx_contracts.py
uv run --frozen python -m pytest -q tests/test_docx_fixtures.py
uv run --frozen python -m pytest -q tests/test_supply_chain.py
uv run --frozen python -m pytest -q tests/test_strategy2.py
node --test scripts/__tests__/reproducibility.test.mjs
python -m tools.audit --project-root . --output <temporary-audit-report>
```

## Post-binding verification

The final checked-in machine audit completed with `status: pass`, zero errors, 429 inventory files,
327 risky records, 323 Python/Node source files, 35 fixtures, one review attestation, and the SBOM
hash stated above. The post-binding supply-chain suite then passed **40/40**, including exact
machine-report equality, review-report hash binding, inventory completeness, and forged-attestation
rejection. The post-binding Strategy2 suite passed **95/95**, including the complete rebound audit
baseline. A clean machine audit remains required for this approval to be usable; the report text
alone is not sufficient evidence.

## Evidence boundary

The automated gates prove current path coverage, exact hashes, declared classifications, static
source policy, fixture registration, owner-contract fixture determinism, binary-payload
reproducibility, and SBOM parity. The source review is high-confidence but cannot prove the
self-asserted reviewer identity, detect every possible expression-level derivation, establish the
behavior of a compromised Python/Node runtime or native host dependency, substitute for remote
Windows/macOS/Linux/LibreOffice/.NET execution, or replace a professional security or legal audit.
No broader claim is made.
