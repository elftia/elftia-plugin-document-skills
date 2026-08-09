# Anthropic clean-room policy

1. A requirements reviewer may record a capability identifier and observable acceptance outcome.
2. An implementer receives only that requirement plus public format specifications and eligible
   library documentation.
3. Tests and fixtures are independently generated or explicitly licensed.
4. An identified reviewer examines the exact module bytes, requirement sources,
   source/license history, generated fixture recipes, and independent tests before release. The
   evidence names the actual report and records its SHA-256; a workflow label or policy file
   alone is insufficient.
5. `provenance/modules.json` records an exact module path, SHA-256, source class,
   `clean_room: true`, reviewer identity, process evidence, and artifact tests.
6. Automation derives one all-file inventory and rejects inventory/hash/classification drift,
   unreviewed scripts, binary magics, opaque bytes, extensionless artifacts, and missing report
   evidence. Every release file is mapped; the only hashless cases are the exact reviewed
   self-referential audit-metadata allowlist.
7. Distributable runtime Python rejects dynamic import, execution, and reflection mechanisms as
   mechanisms, rather than trying to recognize every MCP spelling. Audit and test tooling are
   analyzed outside that runtime scope so the policy implementation cannot weaken its target.
   Automation explicitly does not claim expression-level copying detection; that judgment
   remains an independent human review.

Policy prose may name the excluded source class. Such explanatory text is not an implementation
artifact and must not be confused with one by automated audits.
