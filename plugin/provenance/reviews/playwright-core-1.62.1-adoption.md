# playwright-core 1.62.1 adoption gate

Date: 2026-08-02  
Decision: **ADOPT**, only under the containment conditions below.

This gate admits the published `playwright-core` browser-control API. It does not admit the
`playwright` browser-download package, upstream wrappers, browser binaries, MCP transports,
manifest commands, or third-party capture/emitter source. The checked-in capture adapter and
all Python contracts, scene handling, OOXML emission, validation, and promotion are original
Elftia code.

## Exact production graph

```text
playwright-core@1.62.1
└── (no production dependencies)
```

| Package | Integrity from accepted lock | License |
| --- | --- | --- |
| `playwright-core` 1.62.1 | `sha512-wPYSwEBJY9GHraISXqyqtx0na0LpO3XEX7jNDhntbex7tzUS7kLnZsOlFruFJB4Hi/rhDMjXGqHewDZ68nYZVw==` | Apache-2.0 |

The accepted lock contains no lifecycle-script marker for this package. Installation was run
with `--ignore-scripts`; managed runtime preparation continues to use
`npm ci --omit=dev --ignore-scripts`.

## Gate evidence

The candidate review used Node 24.14.0 and npm 11.9.0 and observed:

- `npm ls --omit=dev --all`: one exact, zero-transitive `playwright-core@1.62.1` graph;
- `npm audit --omit=dev --json`: zero info/low/moderate/high/critical findings;
- `npm audit signatures`: six packages with verified registry signatures and one verified
  attestation across the complete locked Node graph;
- `npm view playwright-core@1.62.1`: Apache-2.0 and the integrity pinned above, with no
  published dependency or lifecycle-script record;
- five provider-state tests covering success, missing Node/library/browser, invalid executable
  evidence, invalid version evidence, launch failure, timeout, exact envelope validation, and
  private-profile cleanup;
- a real contained DOM launch probe against local Chrome 150.0.7871.187 using the checked-in
  `runtime/node/html_capture.mjs`, with sandbox retained, JavaScript/service workers disabled,
  extensions/background networking disabled, and the temporary profile removed afterward.

Registry audit and signature results are point-in-time evidence, not a proof of future absence
of vulnerabilities.

## Mandatory containment

1. The public surface remains frozen uv/Python; Node stays private behind `ProcessRunner`.
2. Only exact `playwright-core@1.62.1` may be imported, and only from the checked-in capture
   adapter listed by the runtime-source allowlist.
3. No browser is downloaded, installed, bundled, or selected by caller/manifest command.
4. Browser selection is from a closed platform-specific Chrome/Chromium/Edge path list and is
   accepted only after canonical-path, version, launch, and DOM-health evidence succeeds.
5. The browser sandbox is retained; fresh profiles, JavaScript/service-worker denial, request
   blocking, time/output ceilings, and full descendant cleanup remain mandatory.
6. Scene and raster payloads use nonce-bound private files. Node stdout remains a small exact
   status envelope, and Python retains path, schema, package, validation, and promotion authority.
7. Any version, integrity, graph, import, browser-launch posture, or lock change requires a new
   adoption review.

## Reproduction commands

```text
npm ci --omit=dev --ignore-scripts
npm ls --omit=dev --all
npm audit --omit=dev --json
npm audit signatures
uv run --frozen pytest -q tests/test_html_browser_provider.py
```
