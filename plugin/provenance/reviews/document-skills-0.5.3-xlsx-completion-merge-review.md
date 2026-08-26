# CLEAN — Document Skills 0.5.3 XLSX Fresh NuGet Restore Review

Date: 2026-08-26

## Verdict

Status: `clean`

Approval claimed: `true`.

Canonical findings: **0 Blocker, 0 Major, 0 Minor**.

This is a fresh, independent review of the canonical unbound candidate that
adds an explicit official NuGet source for the locked OpenXML restore. The
candidate and mapping below are approved only within the stated evidence
boundary; no previous report verdict was reused as approval evidence.

## Reviewer identity

- Reviewer: `Codex collaboration subagent /root/review_xlsx_dist_e2e`
- Identity:
  `codex-reviewer/document-skills-0.5.3-xlsx-fresh-restore/canonical-review-2026-08-26`
- Runtime: `codex`
- Role: `reviewer`
- Review branch: `fix/xlsx-openxml-fresh-restore`
- Review worktree: `elftia-plugin-document-skills-wt-xlsx-e2e`
- Scope: `all-release-artifacts`
- Identity assurance: `self-asserted`
- Identity limitations: This reviewer cannot cryptographically prove the
  backing model, service principal, or human operator. This local review does
  not establish remote CI, a pull-request state, a merge, a live NuGet
  download, live .NET/OpenXML execution, LibreOffice, Microsoft Excel, or
  behavior outside the commands explicitly recorded below.
- Report id: `document-skills-0.5.3-xlsx-completion-merge-review`

The reviewer did not author either candidate commit, the NuGet source change,
the regression test, the regenerated provenance manifest, or the audit report.

## Reviewed target

- Base: `origin/main@e30cb59f6882130cacdc260f41541251c18294fe`
- Candidate commit: `88ffd7cffaccaaa47b1253dd11a1397e7de48852`
- Candidate tree: `10b35a4d49731acc52da2b0909b62c7d01ffc052`
- Commits above base: 2
- Actual diff: 4 paths, 1,522 insertions and 1,509 deletions
- Functional/test diff: 2 paths, 33 insertions
- Independently regenerated unbound provenance mapping SHA-256:
  `0e1389be0583cd197dd5bc9997822e89b2de176cfbf7c781383ab0f2ad8b1814`
- Unbound inventory: 569 module records, 167 data classifications,
  0 executable exclusions, 3 metadata exclusions, 0 review attestations

The worktree started clean at the exact candidate. During this review, the
only tracked path changed was this required canonical report.

## Scope check

Scope Check: **PASS**

Intent: make a fresh, isolated, locked restore of
`DocumentFormat.OpenXml 3.0.0` able to reach one controlled package source,
while preventing fallback to user-configured or additional sources.

Delivered:

- `NuGet.Config` clears inherited package sources and adds exactly one source:
  `https://api.nuget.org/v3/index.json` with protocol version `3`;
- the helper remains locked to the exact direct dependency request and
  resolution `[3.0.0, 3.0.0]` / `3.0.0`;
- the new regression test requires the exact `clear` then `add` structure,
  exact source attributes, and exact direct lock values; and
- canonical provenance now binds both changed files and is deliberately left
  unbound for this independent report.

No scope drift or missing requirement remains in the reviewed change.

## Fresh restore and supply-chain review

The source configuration is co-located with `OpenXmlHelper.csproj`. The
detector continues to invoke restore for that exact project using
`--locked-mode --use-lock-file`, then builds with `--no-restore`; provider
operations use both `--no-restore` and `--no-build`. Managed subprocesses keep
`DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=0` and isolate the NuGet package cache and
Windows application-data roots.

The checked lock graph remains exact and reachable:

1. `DocumentFormat.OpenXml 3.0.0` (direct)
2. `DocumentFormat.OpenXml.Framework 3.0.0` (transitive)
3. `System.IO.Packaging 8.0.0` (transitive)

The supply-chain model retains SHA-512 content hashes, MIT license records,
the two transitive dependency edges, and the application-to-direct-dependency
edge. Focused tests reject a missing lock, dependency-version drift, and
content-hash drift.

## Provenance review

Independent in-memory regeneration was semantically equal to the checked
`provenance/modules.json` and returned the reviewed mapping above. Independent
SHA-256 recomputation found zero drift across all 569 module records and all
167 data classifications.

After excluding the intentionally reset `reviewer` and `review_evidence`
fields, the provenance delta from the base contains exactly two semantic
changes: the SHA-256 values for `NuGet.Config` and
`tests/test_dotnet_provider.py`. All release-path sets are unchanged. The
three and only three metadata exclusions remain:

1. `provenance/audit-report.json`
2. `provenance/modules.json`
3. this current XLSX review report

The checked unbound audit reports exactly one error:
`Independent review attestation is missing`. Inventory, clean-room, commands,
execution boundary, fixtures, manifests, public skills, and SBOM checks pass.
This is the expected pre-binding state, not a candidate finding.

## Findings

No canonical finding remains.

- Standards: 0 Blocker, 0 Major, 0 Minor
- Spec and coverage: 0 Blocker, 0 Major, 0 Minor

## Coverage summary

```text
FRESH NUGET RESTORE
===================
[+] project-local NuGet source policy
    +-- [*** TESTED] inherited sources cleared
    +-- [*** TESTED] sole official v3 source exact
    +-- [*** TESTED] direct requested/resolved version exact
    `-- [*** TESTED] restore/build/runtime argv remain fail-closed

SUPPLY CHAIN AND PROVENANCE
===========================
[+] exact three-package NuGet graph
    +-- [*** TESTED] versions, edges, licenses, and content hashes
    +-- [*** TESTED] missing/drifted lock rejection
    +-- [*** TESTED] content-hash drift rejection
    `-- [*** VERIFIED] 569 module + 167 data hashes, zero drift

REAL PROVIDER
=============
[+] tests/test_dotnet_xlsx_schema_real.py
    `-- [COLLECTED, NOT RUN] 3 conditional real-provider cases
```

## Independent verification evidence

- `python -B -m tools.regenerate_provenance --project-root . --print-mapping-only`
  returned
  `0e1389be0583cd197dd5bc9997822e89b2de176cfbf7c781383ab0f2ad8b1814`.
- Independent manifest comparison was semantically equal; all 736 hashed
  module/data records matched their current bytes.
- The unbound audit exited `2` with status `fail` and exactly the expected
  missing-attestation error; every other audit check passed.
- The complete mock/static `tests/test_dotnet_provider.py` suite plus six
  focused supply-chain cases produced **73 passed**. No real dotnet executable
  or provider was invoked.
- The conditional real-provider file collected **3 cases** and was not run.
- The changed Python passed Ruff and AST parsing; changed JSON and XML parsed;
  all changed text decoded as strict UTF-8 without BOM or replacement
  characters; `git diff --check` passed.
- Test processes explicitly set `DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=0`,
  `DOCUMENT_SKILLS_XLSX_CORE_ONLY=1`, and
  `PYTHONDONTWRITEBYTECODE=1`.
- The process PATH SHA-256 was
  `d8c7bcd8200b9360dc0f8942b40715342914fd0913aac25cee8798ef74ce29c9`
  before testing and remained unchanged afterward.

## Evidence boundary

No remote CI status was queried, awaited, investigated, or used. No real
dotnet/OpenXML provider, NuGet restore/download, LibreOffice, or Microsoft
Excel process was run. The real-provider cases were collected only. No claim
is made about network availability, remote source uptime, or behavior outside
the static, mock, supply-chain, provenance, and audit evidence recorded here.

## Attestation

I independently approve candidate
`88ffd7cffaccaaa47b1253dd11a1397e7de48852` and unbound mapping
`0e1389be0583cd197dd5bc9997822e89b2de176cfbf7c781383ab0f2ad8b1814`.
Within the evidence boundary above, the candidate is **CLEAN with 0 Blocker /
0 Major / 0 Minor**.
