# Agent-core builtin integration handoff

Date: 2026-07-27

## Scope

Implemented the agent-core half of the `document-skills-builtin-integration`
change. No Rasen run-state, task list, platform seed/bootstrap code, or
document-skills runtime/source code was changed by this work.

The scoped diff contains only:

- the shared first-manifest-identity-wins selector and its TinyElf plus SDK/CLI
  consumers;
- canonical contribution-path merge logic;
- the session-local legacy document-skill projection;
- direct tests for those behaviors.

The final agent-core boundary check found no unexpected changed paths.
`git diff --check` passed (only Git's existing LF-to-CRLF checkout notices were
printed).

## Behavior delivered

- Ordered candidates from `discoverPlugins` are folded by manifest identity,
  with user Elftia, workspace Claude, then user Claude precedence inherited
  from discovery. A disabled higher-precedence winner still shadows a lower
  enabled candidate.
- TinyElf and the shared SDK/CLI plugin-path resolver consume the same effective
  bundle set. The existing `pluginsEnabled === true` gate remains unchanged.
- Dual native/Claude manifest contribution roots are canonicalized through
  `realpath`, deduplicated first-seen-wins, case-folded on Windows, and guarded
  against symlink escape or missing paths with bounded non-fatal errors.
- While the enabled managed `document-skills` root is present in the current
  session, only exact `document` and `elftia-document` names from `plugin`,
  `claude-compat`, or `builtin` sources are projected out. Workspace, project,
  and personal overrides remain visible. Removing the gated replacement path
  restores legacy entries. No source file is mutated.

## File-size check

- `resolvePluginPaths.ts`: 49 physical lines
- `assemblePluginContributions.ts`: 249
- `assembleUnifiedAgentContributions.ts`: 271
- `selectEffectivePlugins.ts`: 45
- `canonicalContributionPaths.ts`: 148
- `SkillsLoader.ts`: 697
- `legacyDocumentSkillProjection.ts`: 119

The larger policy and canonicalization blocks were extracted into focused
modules; `SkillsLoader.ts` remains below the 700-line module cap.

## Verification

- Focused regression: **17 files, 169 tests passed**.
- `npm run typecheck:desktop`: **passed**.
- Scoped ESLint over every touched/new agent-core TypeScript file: **passed**.
- Wider TinyElf run: **81 files / 939 tests passed**. Another **12 suites**
  failed during collection before executing tests because the existing
  `packages/desktop/app/main/services/capabilities/tools/skill-toolkit/toolkits/chrome-use/reference/functions.md`
  is imported into Vite's JavaScript import analysis and contains Markdown
  syntax. This shared `functions.md` collection blocker is outside this scoped
  diff.

## Residual note

The wider-suite collection issue prevents claiming a completely green
all-TinyElf run, but all tests that exercise plugin selection, contribution
assembly, path canonicalization, SkillsLoader behavior, and SDK/CLI path
resolution are green.
