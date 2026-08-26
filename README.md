# Elftia Document Skills Producer

This repository is the canonical standalone producer for the `document-skills` runtime-managed
Agent Skills bundle. The reviewed plugin project lives under `plugin/`; host consumers read only
the deterministic artifact emitted at `dist/document-skills/`.

## XLSX implementation map

The XLSX Skill entrypoint and guidance live at
`plugin/skills/document-xlsx/{SKILL.md,scripts/,references/}`. Its Python implementation is in
`plugin/src/document_skills_core/formats/xlsx/`; optional execution adapters are isolated under
`plugin/src/document_skills_core/providers/{libreoffice,dotnet}/`.

The four foundation Core operations are `xlsx.read`, `xlsx.inspect.structure`, `xlsx.create`,
and `xlsx.edit`. The completed Core surface also provides `xlsx.recalculate`, `xlsx.convert`,
`xlsx.template.instantiate`, `xlsx.summary.aggregate`, and `xlsx.pivot.create`. Two additional
operations are provider-only: `xlsx.validate.schema` requires the callable .NET/OpenXML provider,
and `xlsx.render` requires callable LibreOffice. Core conversion remains available without
LibreOffice except for the explicit legacy `.xls` to `.xlsx` branch; formula-bearing explicit
recalculation likewise requires LibreOffice, while a workbook with no formulas reports
`not_applicable` without invoking it.

Formula results use the closed states `recalculated`, `stale`, `never_calculated`, and
`recalculation_required`. Cached values are not described as current, and `recalculated` is used
only after an accepted provider result. Read/create/edit can therefore return a validated Core
artifact with an honest degradation when optional recalculation is unavailable.

Optional-provider source belongs to separately scoped enhancement Changes and is not established
by this Core XLSX delivery. Source presence alone does not make LibreOffice callable: execution
fails closed unless executable identity, private storage, and a validated aggregate hard-quota
backend are all available; the default backend reports unavailable. Full schema validation
similarly does not fall back to a package reopen when .NET 8, the locked helper, or its exact
OpenXML dependency is unavailable. These are producer capability boundaries only: the source
paths do not establish host seeding, live optional-provider execution, or a remote-CI result.

## Verification

```text
npm ci --ignore-scripts
npm run verify
npm run verify:repro
```

`npm run verify` installs the plugin's exact production Node graph with lifecycle scripts
disabled, creates its frozen uv environment, runs the complete Python/Node/provenance suite, and
emits and validates the artifact. The build never discovers or writes an Elftia checkout.

The artifact is consumed by the host's pinned plugin fleet. Producer commands never synchronize
host resources, create remotes, push, publish packages, or mutate user data.
