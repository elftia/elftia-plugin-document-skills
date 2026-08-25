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
uv run --project plugin python plugin/tests/fixtures/pptx/ecosystem_bc/generate.py <presentation-contract-root> --check
~~~

The same generator owns the synthetic B-TPL-04 through B-TPL-06 sanitizer
fixtures under `templates/`: external/OLE removal, active/signature rejection,
and orphan/dangling/duplicate relationship rejection. No third-party template,
preview, logo, photo, or evaluation artifact is present.

Use --write only when an intentionally upgraded owner-package pin has already
been reviewed in the operation-name/contract ADR.
