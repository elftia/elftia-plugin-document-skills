# PPTX ecosystem phase B/C fixtures

This tree contains only Elftia-authored or deterministically generated fixtures.
Every fixture has an adjacent hash-bound manifest recording its origin, license,
recipe, expected operation and consumers, resource limit, security classification,
and invariants.

The common writer rejects absolute/traversal/backslash paths, NFKC or case-fold
collisions, non-redistributable bytes, missing invariants, and payloads over the
declared limit. Future B1-C6 recipes must reuse it instead of inventing a second
fixture metadata format.

The B0 contract snapshot is checked against the owner package without copying its
schemas:

~~~powershell
uv run --project plugin --frozen python plugin/tests/fixtures/pptx/ecosystem_bc/generate.py <presentation-contract-root> --check
~~~

The same generator owns B-TPL-01 through B-TPL-06 under `templates/`:
semantic inspect/fill, dependency purge, CJK/content lint, external/OLE removal,
active/signature rejection, and orphan/dangling/duplicate relationship rejection.
No third-party template, preview, logo, photo, or evaluation artifact is present.

It also owns B-SVG-01 through B-SVG-04 under `svg/` and
`expected/{scene,visual}/`: native primitives/groups/text/transforms, an approved gradient
plus local image, bounded hostile/unsupported SVG cases, and a deterministic
native text/shape/table/chart/image/group round-trip deck. These fixtures prohibit
whole-slide fallback and keep PowerPoint/LibreOffice visual execution states
separate from structural or semantic success. The PowerPoint evidence records only
hashes, object readback, and comparison metrics; temporary render and round-trip
bytes are not release fixtures. LibreOffice remains `unavailable/not_run` where it
is absent.

B-TPL-03 deliberately contains a long Chinese title, a body/title type-scale
inversion, Chinese table text, a placeholder, a standalone ellipsis, and a
speaker-only notes marker. Its expected public operation set is
`pptx.template.inspect,pptx.create.from-template`; content lint is part of those
existing contracts, not a standalone public operation.

Use --write only when an intentionally upgraded owner-package pin has already
been reviewed in the operation-name/contract ADR.
