"""Race-aware loading for caller-hash-bound local PDF sources."""

from pathlib import Path

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import sha256_file

from .byte_preflight import preflight_pdf
from .object_model import PdfObjectModel, parse_pdf


def load_hash_bound_pdf(
    source: Path,
    expected_sha256: str,
    *,
    capability: str,
    field: str,
) -> tuple[PdfObjectModel, str]:
    """Preflight and parse one PDF while enforcing a stable expected digest."""
    if not source.is_file():
        raise DocumentSkillsError(
            ErrorCode.INPUT_NOT_FOUND,
            "The hash-bound PDF source does not exist.",
            status="invalid_request",
            details={"field": field},
        )
    actual_sha256 = sha256_file(source)
    if actual_sha256 != expected_sha256:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "The PDF source does not match source_sha256.",
            status="invalid_request",
            details={"field": field, "capability": capability},
        )
    preflight_pdf(source)
    model = parse_pdf(source)
    if model.sha256 != actual_sha256 or sha256_file(source) != actual_sha256:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "The PDF source changed while it was being read.",
            status="invalid_request",
            details={"field": field, "capability": capability},
        )
    return model, actual_sha256
