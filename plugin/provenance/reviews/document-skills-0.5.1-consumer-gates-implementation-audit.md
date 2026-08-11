# Document Skills 0.5.1 Claude Code provenance review

Identity: claude-reviewer/document-skills-office-create-baseline/opus5-provenance-2026-08-11

- Runtime: Claude Code Opus 5
- Identity assurance: self-asserted
- Scope: all-release-artifacts
- Reviewed mapping digest: d97cc9014f1ccfc94c841d64b1ea1b1782096c3ec402931d96a255dca1f73753
- Status: clean
- Approval claimed: no

## Review result

A fresh report-only Claude Code process reviewed the pre-attestation provenance mapping after
child 3 of the office-create baseline.  The child introduced a new shared
`src/document_skills_core/formats/pptx/scaffold.py` module, repaired the bounded PPTX and XLSX
create scaffolds, and updated HTML/PPTX public and OPC-safety tests to accept the corrected
packages.

The reviewer confirmed that `scaffold.py` is no longer classified under the inherited generic
strategy-attempt-3 profile.  It now carries a truthful `Rasen html-to-editable-pptx`
requirement source and a modification description that reflects its actual Office-valid
PresentationML scaffold role: shared theme, slide master, slide layout, root relationships, and
document properties vocabulary common to both typed `pptx.create` and HTML scene emission.  Its
direct artifact tests are `tests/test_html_scene_opc_safety.py` and
`tests/test_pptx_operations.py`, both of which exercise the scaffold structures.

The reviewer traced the PPTX `create.py` refactor: the inline OOXML structure builders were
extracted into `scaffold.py`, and `create.py` now imports and delegates to the shared scaffold
vocabulary.  The XLSX `create.py` was similarly repaired to emit a bounded valid workbook
scaffold rather than a degraded package.  Both `scene_emitter.py` and `create.py` import from
the same `scaffold.py`, confirming its shared role.

The reviewer verified that the HTML scene OPC safety test (`tests/test_html_scene_opc_safety.py`)
now references the scaffold repair boundary and that the HTML PPTX public tests
(`tests/test_html_pptx_public.py`) accept the corrected package structure.  The fixture
`tests/fixtures/html-native.expected.pptx` was regenerated to match the scaffold-based output.

The generator contract in `tests/test_html_provenance.py` continues to pin
`html_pptx_module_profile` coverage: every module with a profile must carry the truthful
`HTML_PPTX_REQUIREMENT` source, must not contain "strategy-attempt-3" in its modifications, and
must reference only on-disk test files.  The newly profiled `scaffold.py` satisfies all three
constraints.

## Independent execution and limitations

The report-only reviewer used read/search tools and inspected the pending manifest, generator,
profile module, release inventory, provenance validators, runtime-source policy, changed
scaffold and create sources, and direct tests.  Its `dontAsk` permission mode denied shell
execution, so that process did not itself recompute the mapping digest, compare all hashed
records byte-for-byte, regenerate the release inventory, or execute pytest.  It did not claim
those checks.

The integration owner separately ran the official generator, focused generator contract, full
provenance audit, and Producer verification around this review boundary.  Those machine checks
complement but do not alter the reviewer's report-only conclusion.

This self-asserted review cannot cryptographically establish the backing model identity and does
not claim release approval.  It binds all-release-artifact provenance content and classification,
but does not replace final source/Host review, Rasen delivery gates, or downstream release
authorization.
