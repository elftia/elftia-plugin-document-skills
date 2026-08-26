"""Untargeted OPC part-preservation validation."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .package import PreservationManifest

def _assert_preservation(manifest: PreservationManifest) -> dict[str, Any]:
    if manifest.removed:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "A DOCX mutation removed package parts.",
            details={"removed_parts": list(manifest.removed)},
        )
    mismatched = [
        name
        for name in manifest.preserved
        if manifest.input_hashes[name] != manifest.output_hashes[name]
    ]
    if mismatched:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "A preserved DOCX part changed.",
            details={"parts": mismatched},
        )
    return {
        "changed_parts": list(manifest.changed),
        "added_parts": list(manifest.added),
        "removed_parts": list(manifest.removed),
        "preserved_parts": len(manifest.preserved),
    }
