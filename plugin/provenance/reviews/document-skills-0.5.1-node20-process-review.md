# Document Skills 0.5.1 Node 20 process review

- Reviewer identity: `codex-reviewer/document-skills-node20-process/lexical-launch-canonical-identity`
- Runtime: Codex
- Identity assurance: self-asserted
- Scope: `all-release-artifacts`
- Reviewed mapping digest: `5db458aab6c973c632b719a45623944960bddb0bca8507fd5b79721b4d57fc06`
- Status: `clean`
- Approval claimed: no

## Review scope and result

The review checked the complete regenerated release inventory and focused its semantic
analysis on the version change, process-policy diff, POSIX regression tests, provenance
classification changes, and the absence of dependency or lock drift. No blocking
finding remained in that local scope.

The process policy now records an approved absolute lexical launch path separately from
its canonical executable identity. `ProcessRunner` re-resolves and compares the identity
immediately before launch, rejects a symlink retarget, and passes the approved lexical
path as argv[0]. This preserves POSIX virtualenv selection without adding `NODE_PATH`,
changing the locked dependency graph, enabling lifecycle scripts, or broadening an
executable allowlist.

## Evidence examined

- The new POSIX launch-path test failed against the old implementation because the child
  observed `/usr/bin/python3.12`, then passed after the repair with the approved symlink.
- A second POSIX regression proves that retargeting the approved symlink is rejected
  before process launch.
- The original public five-operation DOCX boundary passed on WSL with Node 20.20.2 and
  the frozen Python environment after the repair.
- Focused public/process suites passed on Windows with Node 20.0.0, Node 20.20.2, and
  Node 24.15.0; the complete runtime test module passed on Node 24.15.0.
- The producer workflow matrix covers Node 20 and Node 24 on Ubuntu, macOS, and Windows.

## Limitations

This is a same-session, self-asserted local review and cannot provide independent
author/verifier separation or cryptographically prove its backing service identity. It
does not claim release approval, did not execute remote GitHub Actions, and cannot
substitute local WSL evidence for native macOS CI. The all-release-artifacts scope binds
the regenerated inventory and classifications; deeper semantic examination concentrated
on the files changed for the Node 20 repair.
