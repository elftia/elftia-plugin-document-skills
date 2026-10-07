# Provenance

All foundation and Core DOCX implementation modules are original Elftia project code, written
from the Rasen requirements and public Python/Node/file-format APIs. One shared inventory hashes and classifies
every prospective release file. It treats source modules, shell/PowerShell scripts, executable
locations and modes, shebangs, extensionless files, PE, ELF, OLE/CFB, Mach-O 32/64/fat/FAT64,
WASM, Java, NUL-bearing, and low-text opaque bytes as executable or risky without relying on a
friendly suffix. Opaque fixture data is exempt only when its exact hash and redistribution
permission are backed by `tests/fixtures/manifest.json`.

`provenance/modules.json` gives every risky artifact an exact module record or
hash-pinned data exclusion. Every remaining release file has an exact data
classification. The manifest, generated audit report, and current review report use a
three-path bounded self-reference classification because raw hashes for files that contain
their own digest would be circular. No other hashless classification is accepted. Broad globs,
overlap, omissions, and classification drift are invalid.

When an independent review is supplied, reviewer labels resolve to a runtime/role/identity
attestation and the hash of actual canonical checked-in report bytes under
`provenance/reviews/`; policy documents, an echoed digest, a
self-reference, and placeholder evidence are not review evidence. Each report binds the exact
all-file mapping digest it reviewed. Runtime identity is explicitly self-asserted unless a
future signature-backed verifier is implemented: the repository can prove report-byte and
mapping integrity, but cannot cryptographically prove the service or human principal behind the
asserted reviewer identity or turn a findings report into release approval.
Every data classification and risky-data exclusion additionally requires review evidence,
classification, and a concrete reason; all non-circular records require an exact SHA-256.

## Clean-room boundary

Anthropic material may identify desired capability names only. Restricted Anthropic prompts,
Skill text, scripts, schemas, templates, fixtures, reference text, and implementation expression
must not enter this project. Parity implementations must use public file-format specifications,
eligible open-source APIs, or original Elftia design and independent artifact tests.
The automated audit proves inventory, hashes, and declarations, and validates review evidence
when an attestation is supplied. It does not claim that a keyword scan can detect copied
implementation expression; the pending review label is not an approval claim.

## DOCX dependency adoption

Core DOCX behavior is original Elftia code. The narrow scalar template backend adopts only the
published `docxtemplater` 3.69.3 and `pizzip` 3.2.0 APIs with their exact transitive graph
`@xmldom/xmldom` 0.9.10 and `pako` 2.2.0. The implementation-time gate records license,
integrity, registry-signature, vulnerability, deterministic-output, escaping, split-run, and
preservation evidence. Python remains authoritative for grammar, archive security, paths,
preservation, validation, result schema, and promotion. No third-party wrapper or source module
was copied. The exact decision and mandatory containment are recorded in
`provenance/reviews/docxtemplater-3.69.3-adoption.md`.

## Adoption boundary

MiniMax or claude-office-skills code is eligible only after module-level license, security,
fidelity, and artifact review. Useful pure file-processing logic remains reviewable even when its
original file was stored below an MCP directory, but server registration, handler envelopes,
tool schemas, transport, lifecycle, and state glue are never adopted. See
`provenance/adoption-review-template.md`.

## Fixture boundary

Every binary fixture must be listed in `tests/fixtures/manifest.json`, have a deterministic
recipe or eligible public source, explicit redistribution permission, and a verified SHA-256.

## Static release-policy limits

`provenance/dependency-allowlist.json` binds the exact frozen production package versions and
permitted runtime import roots. `provenance/runtime-source-allowlist.json` binds the exact Python
and Node files that receive the strict value-flow policy. Python uses bounded AST scope/value
flow; Node uses the locked Acorn parser. Dangerous loader, reflection, dynamic-code, child
execution, and MCP-registration identities are rejected when acquired or propagated, before a
call is required.

This deterministic gate is not a privilege sandbox or a complete semantic proof. It cannot
establish the behavior of native code, import-time side effects inside an allowed dependency, a
compromised Python/Node runtime, future code that interprets data as executable content, an AST
parser vulnerability, OS compromise, or a bespoke hidden protocol deliberately misrepresented
during review. Exact locks, hashes, process containment, and independent review reduce those
risks without erasing them.
