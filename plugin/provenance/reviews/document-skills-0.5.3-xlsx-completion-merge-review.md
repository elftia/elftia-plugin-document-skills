# CLEAN — Document Skills 0.5.3 XLSX Completion Merge Review

Date: 2026-08-25

## Verdict

Status: `clean`

Approval claimed: `true`, limited to the exact all-release-artifacts provenance
mapping, classifications, hashes, requirement-source attribution, and review evidence
described here. This is not remote-CI, pull-request, merge, live-LibreOffice, or general
maintainer release approval.

Canonical findings after remediation: **0 Blocker, 0 Major, 0 Minor**.

The approved prospective mapping contains **531 release files**: **420** risky module
records, **108** exact-hash data classifications, **0** adopted sources, **0** executable
exclusions, and exactly **3** self-referential metadata exclusions. Its SHA-256 is:

`c6cdb88218cd8d808103ec27e597f34c3c43b803489f3ba6ad7826ca629aadb6`

## Reviewer identity

- Reviewer: `Codex collaboration subagent /root/final_merge_provenance_review`
- Identity: `codex-reviewer/document-skills-0.5.3-xlsx-completion-merge/fresh-non-author-2026-08-25`
- Runtime: `codex`
- Role: `reviewer`
- Scope: `all-release-artifacts`
- Identity assurance: `self-asserted`
- Identity limitations: This self-asserted reviewer cannot cryptographically prove the
  backing model, service principal, or human operator; it does not replace maintainer
  approval and does not establish remote CI, pull-request, merge, live LibreOffice, or
  unobserved operating-system behavior.
- Attestation id: `document-skills-0.5.3-xlsx-completion-merge-review`

No previous attestation, historical clean verdict, or pre-generated mapping digest was
treated as approval evidence. This reviewer did not author the implementation, tests,
planning artifacts, provenance generator, or manifest under review.

## Reviewed target and exact mapping

- Branch: `feat/xlsx-completion`
- Base: `origin/main` at `14db457d6a50768ad3f8b4e518e45f3225a092cd`
- Reviewed HEAD: `d74baac596de4fab738df083946857f4a565cb6d`
- Reviewed scope: 189 tracked plugin paths changed from the base plus the final
  prospective working-tree bytes, including this self-referential review tail.
- Pending manifest SHA-256 before attestation binding:
  `a3bf474cabed610b33d15f3e3b7f5b33e4ed8e0346c26a9e6e273a7a472d961a`
- Runtime source allowlist SHA-256:
  `9e42de16d328a9fff168e1b666fb1e6797a30cc3209fad91f7c597a0d36b3920`
- Pending audit-report SHA-256:
  `676c0178f52f0af22f12be69702d6da7d1129e330b1559f6e3215f0b8eb23211`

Two consecutive command-line regenerations and a separate temporary-copy regeneration
reproduced the approved mapping digest. The runtime allowlist matched canonical generated
bytes exactly. A temporary copy with the pending manifest and runtime allowlist materialized
had exactly one audit error, `Independent review attestation is missing`; every other audit
section passed.

At signing time, the worktree `provenance/modules.json` and `audit-report.json` still contain
the previous binding. They are not evidence for this verdict and must be regenerated from
this report before delivery.

## Planning authorization reviewed

The completion and advanced-authoring sibling Changes were read in full and both passed
strict Rasen validation. Their exact planning hashes were:

| Change | Artifact | SHA-256 |
| --- | --- | --- |
| `document-skills-xlsx-completion` | `proposal.md` | `9636b281b27be29e9d4cb3f7c69caba10906dfdcb7ca52efe24be2b8d30dfe6b` |
| `document-skills-xlsx-completion` | `design.md` | `88b2bb7e6fbded0639b6e65badfcac3053e8b1d29335e50a8123348eeddb6240` |
| `document-skills-xlsx-completion` | `specs/document-xlsx-completion-operations/spec.md` | `942ad7d9400c3f82208f5955ec5df3ca31648a6395ea6cd90a83ae3bd3744370` |
| `document-skills-xlsx-completion` | `tasks.md` | `7af8da007fdbc09bc3aa2ebf7ec882a4a5836ec546b007abd8df8e43051ad6b6` |
| `document-skills-xlsx-advanced-authoring` | `proposal.md` | `efb7bb34e510d7ad0034feb43c24a13734917f755b218d8da34189701b80b290` |
| `document-skills-xlsx-advanced-authoring` | `design.md` | `120f1382d9eceb082ebe4f9900fd5f802324f147ffa5711b9a5f2cc9a13590a5` |
| `document-skills-xlsx-advanced-authoring` | `specs/document-xlsx-advanced-authoring/spec.md` | `8ffa3711abd6c1cffa84073f4db8370936664540e241234b957fdd5f1f496ff4` |
| `document-skills-xlsx-advanced-authoring` | `tasks.md` | `6b5d5c65e3bbf69fccdef71aee59a6e8a47c57acb9549a2c9e02e896dbbcfe05` |

The completion Change owns the seven additional operation identifiers. The advanced
Change owns richer behavior only within the original `xlsx.read`,
`xlsx.inspect.structure`, `xlsx.create`, and `xlsx.edit` operations and explicitly does
not own LibreOffice or .NET provider mechanisms.

## Findings remediated before binding

1. Runtime tests no longer infer that hiding `dotnet` from `PATH` proves the runtime is
   absent; platform discovery and the real production provider path are tested honestly.
2. The seven completion operations and advanced behavior of the original four operations
   have explicit, strict-valid planning authorization.
3. NuGet restore/build evidence uses a project-private temporary cache and configuration;
   notice and project-file descriptions match that production behavior.
4. Formula-analysis guidance matches the actual stable diagnostic shape.
5. Fail-closed sheet-copy/delete, special-formula structural edit, and pivot structural
   edit regressions assert destination preservation and unchanged source SHA-256.
6. Exact XLSX provenance is partitioned into mutually exclusive, complete profiles for all
   112 XLSX modules and 15 Skill data artifacts. Shared provider/process/data artifacts are
   composed only from applicable requirement sources.
7. Recalculation ownership was corrected across Core, Completion, Advanced where static
   analysis applies, and LibreOffice; Advanced no longer claims LibreOffice mechanisms.
8. Recursive fixture registration now covers nested release fixtures exactly while private
   `.document-skills-tmp` state remains outside copied audit projects.
9. Native PPTX schema repairs preserve required gradient stops, shape child order,
   `p:graphicFrame/p:xfrm`, and group-transform order; mutation workers receive the bounded
   45-second supervisor budget required by their operation layer.
10. The new Core-PPTX changes, their direct tests, the shared HTML paths, and shared XLSX
    paths now compose explicit Core-PPTX/HTML/XLSX requirement sources, modification text,
    and direct test evidence. They no longer fall through to the unrelated Foundation text.
11. README data attribution uses the complete XLSX profile, and both HTML and Strategy-3
    provenance regressions derive shared-owner expectations from the same explicit profiles.
12. Cross-format capability reporting now requires an available callable provider registered
    for the matching format's public schema or visual operation. Its implementation and direct
    Strategy-2 regression evidence compose exact Foundation, Core DOCX/PDF/PPTX/XLSX, Completion,
    and, where already applicable, Advanced XLSX provenance instead of unrelated fallback text.
13. The deterministic native HTML-to-PPTX oracle was regenerated after the schema repairs. Its
    ZIP inventory is unchanged; only both slide group-transform child orders and the theme's two
    required gradient-stop lists changed. The fixture manifest and prospective provenance carry
    the exact new artifact SHA-256
    `0e6aa02162c4005c9cc72de0d0ffa4367098f9ba3c47110987585ebdbefbd41f` and checked-in
    recipe/test evidence.
14. Public PPTX schema tests no longer compare provider snapshots from independent workers.
    Each result is assessed from its own response: successful explicit schema validation checks
    the provider chain and passing schema gate; create checks the schema validator and evidence;
    unavailable branches require a bounded reason. The test artifact now composes exact Foundation,
    Core-PPTX, and OpenXML/.NET provenance with itself as the sole direct test evidence.

## Independent verification evidence

- Strict Rasen validation passed for both sibling Changes.
- Earlier implementation-focused groups passed the fail-closed XLSX, recalculation,
  original-operation, public XLSX, provider, runtime, process-safety, and completion tests
  recorded during this review. The real production .NET/OpenXML schema path passed its
  dedicated test; environment-dependent skips were not treated as passes for absent hosts.
- After the final provenance fixes, a fresh 32-node focused group passed. It covered the
  Core-PPTX profiles, full owner composition, README data composition, PPTX gradient/shape/
  graphic-frame/group-transform schema repairs, mutation budgets, recursive fixtures,
  mapping-v2 semantics, historical/current review boundaries, all XLSX profiles, formula
  diagnostics, and fail-closed sheet/structural edits.
- After the final cross-format capability and provenance remediation, 24 independently selected
  cases passed and one optional environment-dependent XLSX provider case skipped. The passing
  cases covered the new format/callability matrix, default-provider detection, public DOCX/PDF/
  XLSX/PPTX capability reports, provider gating, exact cross-format attribution, all current XLSX
  provenance profiles, shared-owner composition, and release-inventory coverage.
- After the deterministic fixture regeneration, 19 independently selected checks passed: all
  seven HTML/PPTX fixture tests, the supply-chain fixture/manifest audit, and 11 capability,
  Core-PPTX schema, operation-budget, and provenance regressions. Two recipe generations matched
  each other and every checked-in fixture byte exactly; all 15 XML/relationship members in the
  PPTX parsed successfully.
- After the public PPTX operation-time gating repair, nine independently selected cases passed:
  both affected public schema/create nodes and seven exact-attribution regressions. The new test
  record was inspected directly in the prospective manifest and matched the composed Foundation,
  Core-PPTX, and OpenXML/.NET owners, modification descriptions, and direct-test list exactly.
- All four HTML/Core-PPTX provenance tests passed against a temporary materialization of the
  pending manifest, including the complete HTML release-record scan.
- The 10 explicit Core-PPTX profile records and README were inspected directly in the
  prospective manifest; every requirement, modification description, and ordered direct-test
  list matched the intended composed owners. Every referenced `artifact_tests` path exists.
- Final XLSX profile sets were pairwise disjoint and covered all 112 XLSX modules; all 15
  `skills/document-xlsx/` data artifacts had an explicit profile. Requirement strings had no
  duplicate or unknown component.
- Focused Ruff, strict UTF-8 decoding, JSON parsing, project XML parsing, conflict-marker
  scanning, and `git diff --check` passed. No replacement character, mojibake marker,
  unexpected BOM, missing test-evidence path, or unrelated encoding rewrite was found.

Repository-wide verify attempts exposed the stale deterministic fixture and then the cross-worker
provider-snapshot assertion corrected above. Their remaining setup errors were independently
traced to a concurrent pytest run in another worktree contending for the shared operation-temp
root, not to these release bytes. The repository-wide workflow was not rerun alone after the final
public-test repair; that absence is explicit and is not replaced by the focused evidence above.

## Evidence boundary

This review establishes the current local prospective release bytes, their exact inventory,
hashes, classifications, requirement-source attribution, and the listed local test evidence.
It does not claim that remote Windows, macOS, or Linux CI completed; it did not exercise a
live LibreOffice installation; and it did not observe a pull request or merge. The real .NET
schema evidence was obtained through the production private provider environment; no direct
user NuGet state or uncontained restore command was used. Optional host executables and their
dynamic dependency closures are not represented as redistributed components.

## Attestation

I attest that the Codex collaboration subagent identified above independently reviewed the
complete prospective plugin release with scope `all-release-artifacts`, returned status
`clean`, and found no remaining Blocker, Major, or Minor issue within the stated provenance
scope. I approve binding this report to mapping digest
`c6cdb88218cd8d808103ec27e597f34c3c43b803489f3ba6ad7826ca629aadb6`
and to no other mapping.
