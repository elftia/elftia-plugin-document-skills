# Document Skills 0.5.3 Packaging Hygiene Review

## Reviewer identity

- Runtime: OpenAI Codex CLI 0.148.0
- Model: gpt-5.6-sol
- Session: `01a022f8-2a15-71c3-921a-d4bf624106d1`
- Attested identity: `codex-reviewer/document-skills-0.5.3-packaging-hygiene/gpt-5.6-sol-2026-08-21`
- Identity assurance: self-asserted; this report cannot cryptographically prove
  the backing model identity and does not replace final maintainer approval.
- Review mode: read-only; the reviewer made no file changes.

## Scope

Removal of producer-only CI metadata from release inventory, rejection of
non-runtime developer directories, package version/dependency updates, and the
associated regression/provenance changes. Generated provenance JSON was not
opened by the reviewer; the exact mapping digest was supplied explicitly.

## Round 1

Reviewed mapping: `54614c2e5eff44d7085bf71a6906203f84234718e634fce0563a56a117f84c03`

Finding:

- `[P2]` `release_inventory.py` filtered every path component, including the
  terminal filename. A legitimate regular file named `.github`, `.idea`,
  `.vscode`, or `.computer-use` would therefore have been silently omitted.

Verdict: **FAIL**. The mapping was not fit to bind as all-release-artifacts
evidence.

## Remediation

The filter now compares only directory components (`relative.parts[:-1]`). Four
negative controls pin that identically named regular leaf files stay in the
release inventory. The focused regression command passed all eight cases.

## Round 2

Reviewed mapping: `5b98b67c3f85ee61cc894545719efcf6970eec171d76138fb7af8f94841e6c5a`

Reviewer output:

> Scope
>
> Fix delta in `release_inventory.py` and `test_structure.py` only. No tests run;
> no generated JSON opened.
>
> Evidence
>
> - Filtering now case-folds only `relative.parts[:-1]`.
> - Four negative controls confirm identically named leaf files remain inventoried.
>
> Findings
>
> No findings.
>
> GATE PASS
>
> The exact mapping digest
> `5b98b67c3f85ee61cc894545719efcf6970eec171d76138fb7af8f94841e6c5a`
> is fit to bind as all-release-artifacts evidence.

Final status: **clean**. Approval is limited to the reviewed packaging-hygiene
scope and exact mapping digest above.
