# DOCX preservation, security, and validation

## Copy-through preservation

Template and replacement operations index every input package part and its payload SHA-256.
Only explicitly planned Word story parts may change. No original part may be removed. Unknown
safe parts, media, custom XML, relationships, headers/footers, and section definitions remain
byte-identical at the part-payload level unless they are a declared target.

The output ZIP hash normally differs from the input ZIP hash. Preservation claims refer to
untargeted part payloads, not whole-container byte identity.

## Fail-closed package policy

Normal read and every mutation reject:

- absolute, traversal, drive-qualified, duplicate, normalized-alias, or symlink ZIP members;
- CRC, entry, uncompressed-size, expansion-ratio, or XML-size violations;
- malformed XML, DTDs, and entities;
- escaping or missing internal relationship targets;
- VBA/macros, DDE, remote templates, external relationships, executable parts, OLE, and ActiveX.

Structural inspection can inventory bounded active/external content without following or
executing it, but the underlying ZIP/XML container must still be safe.

## Protected Word structures

Replacement and template matching do not cross hyperlinks or structural barriers. A request that
would modify field instructions, tracked revisions, deleted text, or comment bodies returns
`enhancement_required` with the optional `.NET/OpenXML` recommendation. Presence detection alone
does not run or enable that enhancement.

## Transaction

Each write validates explicit/distinct paths, hashes the source, writes under a private operation
root, executes required gates on the staged DOCX, validates the canonical candidate result,
stages in the destination filesystem, atomically promotes, rechecks final bytes, and verifies the
source digest. Failure before promotion leaves the destination unpublished.
