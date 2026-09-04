# Document Skills 0.5.8 merge rebaseline note

- Date: 2026-09-04
- Repository: `elftia-plugin-document-skills`
- Branch: `main` (merge commit; see git log for the exact pair)
- Bases: `f4454c7` (0.5.7 EPKG v2 sidecar re-cut) + `origin/main` `d087f5e`
  (PR #25 docx-template-packs-and-reference-import, review bound at `2bcbac8`)
- Author: Claude lead session (merge author; NOT an independent reviewer)
- Scope: `all-release-artifacts` for the merged 0.5.8 rebuild
- Status: `rebaseline — independent exact-byte review PENDING`

## What this is

The docx line cut 0.5.6/0.5.7 on two diverged lineages that never met: local
main carried the 0.5.7 version bump + EPKG v2 sidecar re-cut; origin main
carried the full reviewed docx-template-packs-and-reference-import feature
(193 files) bound to its own review. This merge unions both and rebaselines
the release at 0.5.8 so the boot seed refreshes profiles already sitting on
the interim 0.5.7 build (tables/tblGrid present, template packs absent).

## Prior reviews carried by the union

- `provenance/reviews/docx-template-packs-and-reference-import-review.md`
  (PR #25 lineage, bound at `2bcbac8`)
- `provenance/reviews/ds-0.5.7-version-bump-2026-09-03.md`
  (0.5.7 re-cut lineage, Codex exact-byte reviewer)

## Regenerated provenance

`plugin/provenance/modules.json` + `audit-report.json` are regenerated from
the final 0.5.8 release bytes with reviewer `PENDING independent review`.
The mapping digest is recorded in `audit-report.json`. Binding an independent
review against that digest is the designated reviewer role's follow-up per
the frozen attestation regime — no approval is claimed here.
