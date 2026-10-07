# Document Skills 0.5.9 PPTX notes repair rebaseline

- Date: 2026-09-05
- Repository: `elftia-plugin-document-skills`
- Base: `e88b17273bbb3829060ec4abe49a4e228c197c04` (0.5.8)
- Author: Claude implementation session (NOT an independent reviewer)
- Scope: `all-release-artifacts` for the prospective 0.5.9 rebuild
- Status: `rebaseline — independent exact-byte review PENDING`
- Prospective mapping SHA-256: `609f8ecf1bac7c2567c87bc53c52a28f2f735554ad80bf1bf6e8c52d065187da`

## Defect and root cause

PPTX files containing speaker notes passed the Core deep package gate and
OpenXML SDK 3.0.0 validation, but PowerPoint required repair before opening.
The generated notes master and slide master both referenced the same theme
part. PowerPoint repair created a distinct notes-master theme and rebound the
relationship.

A four-case reproduction (`single/full deck × notes/no notes`) isolated the
failure to notes-bearing output. Nine XML variants then isolated the required
consumer invariant: a notes master must use a theme part distinct from every
slide-master theme. Copying the existing custom theme bytes to a separate part
was sufficient; replacing the user's theme was unnecessary.

## Implemented repair

- typed create emits a distinct notes-master theme when notes are present;
- slide add, notes update, and template-as-base creation allocate and copy an
  existing theme when introducing the first notes master;
- the Core graph gate rejects a theme shared by slide and notes masters;
- deterministic note-bearing fixtures and their hashes are regenerated;
- an opt-in PowerPoint test uses normal `Presentations.Open`, never
  `OpenAndRepair`, and confirms generated notes are readable;
- release identity is advanced to 0.5.9 so managed-runtime seeding cannot keep
  serving the old 0.5.8 bytes.

## Local evidence before independent review

- focused PPTX create/edit/design/deep-validation tests: passed;
- deterministic B/C fixture regeneration and `--check`: passed;
- real PowerPoint notes consumer test: passed;
- original 12-slide public request regenerated through `scripts/run.py`: passed
  Core and OpenXML gates;
- regenerated 12-slide deck opened normally in PowerPoint with repair disabled,
  retaining notes on all 12 slides.

## Review boundary

This note records implementation and rebaseline facts only. It does not claim
independent approval. The regenerated provenance mapping must remain
`PENDING independent review` until a different reviewer examines the final
0.5.9 bytes, records findings, and binds the exact mapping digest. The automated
official release may proceed without claiming that this independent review has
occurred; its inventory, byte-hash, and runtime checks still apply.
