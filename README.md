# Elftia Document Skills Producer

This repository is the canonical standalone producer for the `document-skills` runtime-managed
Agent Skills bundle. The reviewed plugin project lives under `plugin/`; host consumers read only
the deterministic artifact emitted at `dist/document-skills/`.

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

