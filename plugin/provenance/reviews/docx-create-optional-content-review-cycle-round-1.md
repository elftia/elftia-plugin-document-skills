# docx.create optional-content — independent review cycle

- Reviewer identity: `codex-reviewer/docx-create-optional-content/toctou-oracle-closed`
- Runtime: codex (OpenAI Codex CLI 0.146.0)
- Identity assurance: self-asserted
- Scope: all-release-artifacts (see Limitations for what was actually examined)
- Reviewed mapping digest: `295c3fecdb2646ff5389a52f0d33e3bb818de39ee23bf0a128922f441b055442`
- Status: `clean`
- Approval claimed: yes, at round 4

## Why this record exists

The change was authored by a Claude session. That session did not review its own work:
an independent reviewer on a different vendor, model and runtime was dispatched
read-only, given the sources and the unified diff, and told explicitly not to be
agreeable. It ran four rounds. The first three returned findings; the fourth returned
`VERDICT: CLEAN` with no findings. This record supersedes the authoring-session
self-review that briefly held this slot and claimed no approval.

The reviewer's first attempt could not bootstrap its Windows sandbox and therefore could
not read any file. It reported the failure and explicitly refused to emit a verdict
rather than fabricate one. Subsequent rounds inlined the sources into the prompt so no
shell access was required.

## Change under review

`docx.create` previously rejected any request that did not also supply a table, a local
image, non-empty header and footer text, and at least two sections. Agents were
fabricating a 1x1 placeholder PNG and inventing tables to get past the contract, and
those fabrications were written into delivered documents. Every one of those members is
now opt-in; `report.blocks` is the only required member. A new `image` block type renders
a figure where the caller placed it, and heading levels went from 1-2 to 1-6.

## Findings and dispositions

**Round 1 — five Major.**

1. `pic:cNvPr@id` was hard-coded to `"0"` for every picture, so multiple images did not
   get distinct non-visual drawing ids. ACCEPTED. Now `str(position - 1)` — zero-based so
   the first image keeps the id earlier versions emitted and single-image packages stay
   byte-identical.
2. The required gate did not validate image payload, dimensions, width, relationship ids,
   target uniqueness or placement. PARTIALLY ACCEPTED. Payload/width depth was
   pre-existing looseness, not something this change weakened — the gate checked the same
   three properties before, for exactly one image. Placement, however, is a new degree of
   freedom this change introduced, so `_body_layout`/`_expected_layout` now compare the
   body's direct-child sequence against the sequence the report describes, plus an
   `image-target-uniqueness` check. The reviewer maintained the payload half in round 2;
   see R2-1.
3. Heading style validation only checked that referenced ids existed. ACCEPTED in part:
   the subset check became an exact set comparison against
   `{Normal, TableGrid} + Heading1..HeadingN`. Run-property depth (size, bold) predates
   this change and the reviewer accepted that scoping in round 2.
4. Unreferenced story parts were invisible to `document_stories`. ACCEPTED.
5. `creation["image"]` was replaced by `creation["images"]`, breaking callers. ACCEPTED;
   `image` is back alongside `images`.

**Round 2 — two Major.**

1. The gate could not prove which requested image occupied each position: swapping two
   `r:embed` values passed everything. ACCEPTED; per-position payload identity is now
   checked.
2. The story-part inventory went by name prefix, which OPC does not constrain — a
   `word/ghost.xml` declared as a header evaded it. ACCEPTED, and closed more broadly
   than proposed: creation authors every byte of the package, so the gate now asserts the
   exact part set derived from the report. Any part the report did not ask for, under any
   name and any declared content type, fails as `package-parts`.

Round 2 also confirmed `_body_layout` produces no false failure for tables, a final
image, the trailing `report.image`, one section, or multiple-section boundary paragraphs.

**Round 3 — one Major, and it was caused by the round-2 fix.**

The new byte comparison called `load_image` again, re-reading the caller's mutable source
path. A source replaced between creation and validation would have failed a correctly
built package — a false failure that blocks promotion, which is worse than the hole it
closed. ACCEPTED. `create_docx` now captures an immutable oracle (alt text, content type,
extension, byte length, payload sha256, pixel dimensions) and `validate_created` takes
it; `load_image` is gone from the validation module entirely. An `image-oracle` guard
fails if the snapshot disagrees with the number of images the report requested.

Round 3 also confirmed the exact part-set assertion is correct for every report shape the
contract admits — no images, inline only, trailing only, both, header only, footer only,
neither — and that mixed formats produce `image1.png` / `image2.gif` in inline-then-
trailing order.

**Round 4 — no findings. `VERDICT: CLEAN`.**

## Preservation and security posture

Unchanged. Creation still requires an explicit output path, refuses an input path, and
promotes atomically. Every image — inline block or trailing report image — goes through
the same bounded local-file loader: no remote schemes, no UNC paths, PNG/JPEG/GIF
magic-byte checks, per-image 16 MiB and 100,000-pixel ceilings, plus a 32-image count
ceiling and a 64 MiB aggregate byte budget. Only the `Normal` paragraph style and the
`TableGrid` table style are accepted. Aggregate node, text-byte and table-cell budgets
are enforced before any file is opened.

The required create-semantics gate is strictly stronger than before this change: it now
asserts the exact package part set, the exact heading style set, per-position image
payload identity, image target uniqueness, and block layout — none of which it checked
previously.

## Verification performed by the author

- Full project pytest suite: pass.
- DOCX fixture determinism: pass — a fully populated request still produces
  byte-identical packages, so the relaxation and the deeper heading range are additive.
- New coverage: `tests/test_docx_create_gate.py` doctors packages that `create_docx`
  produced and asserts the gate refuses each one — image moved out of position, orphan
  story part, story part hidden behind an innocent name, extra heading style, missing
  heading style, swapped image payloads — plus the TOCTOU case, where the source is
  overwritten and then deleted after creation and the gate must still pass.

## Limitations

This reviewer is self-asserted: it cannot cryptographically prove its backing service
principal. Its examination covered the DOCX creation contract, emitter, validation gate
and Skill guidance, together with the unified diff of the change — not every one of the
release artifacts the `scope` field names, which the attestation schema does not let this
record narrow. It did not execute the test suite, and it does not validate rendering in
Microsoft Word, LibreOffice or WPS, remote CI, packaged-application behaviour, or
operating systems other than the one the author's suite ran on.
