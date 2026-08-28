"""Transactional pypdf provider service."""

from pathlib import Path
from typing import Any, Callable

from pypdf import PdfReader

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import make_error_result
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot
from document_skills_core.formats.pdf.contracts import parse_pdf_request
from document_skills_core.formats.pdf.transaction import (
    promote_candidate,
    write_candidate_result,
)

from .operations import compress_pdf, decrypt_pdf, encrypt_pdf
from .validation import validate_compressed, validate_decrypted, validate_encrypted

PYPDF_OPERATIONS = frozenset({"pdf.encrypt", "pdf.decrypt", "pdf.compress"})


class PypdfService:
    def __init__(self, project_root: Path) -> None:
        self.schemas = SchemaCatalog(project_root.resolve())

    def execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._execute(operation, request)
        except DocumentSkillsError as error:
            options = request.get("options", {})
            fidelity = options.get("fidelity", "core") if type(options) is dict else "unknown"
            return make_error_result(
                operation,
                error,
                requested_fidelity=fidelity,
            )

    def _execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        if operation not in PYPDF_OPERATIONS:
            raise DocumentSkillsError(
                ErrorCode.OPERATION_UNKNOWN,
                "The pypdf provider does not implement this operation.",
                status="invalid_request",
            )
        parsed = parse_pdf_request(request)
        if parsed.operation != operation:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "pypdf provider binding does not match the request operation.",
                status="invalid_request",
            )
        assert parsed.input_path is not None
        assert parsed.output_path is not None
        assert_distinct_paths(parsed.input_path, parsed.output_path, in_place=False)
        source = file_record(parsed.input_path, "input")
        destination = destination_snapshot(parsed.output_path)
        try:
            with OperationTempRoot() as private_root:
                staged = private_root / "candidate.pdf"
                if operation == "pdf.encrypt":
                    operation_result = encrypt_pdf(
                        parsed.input_path,
                        staged,
                        parsed.arguments,
                    )
                    validation = validate_encrypted(
                        parsed.input_path,
                        staged,
                        parsed.arguments,
                    )
                    operation_result["encryption"]["verified"] = True
                elif operation == "pdf.decrypt":
                    operation_result, password_type = decrypt_pdf(
                        parsed.input_path,
                        staged,
                        parsed.arguments,
                    )
                    unlocked_source = PdfReader(parsed.input_path, strict=True)
                    if unlocked_source.decrypt(parsed.arguments["password"]) != password_type:
                        raise DocumentSkillsError(
                            ErrorCode.VALIDATION_FAILED,
                            "Encrypted source could not be reopened consistently.",
                        )
                    validation = validate_decrypted(unlocked_source, staged)
                    operation_result["decryption"]["verified"] = True
                else:
                    operation_result = compress_pdf(
                        parsed.input_path,
                        staged,
                        parsed.arguments,
                    )
                    validation = validate_compressed(
                        parsed.input_path,
                        staged,
                        parsed.arguments,
                        operation_result,
                    )
                    operation_result["compression"]["verified"] = True
                result = write_candidate_result(
                    self.schemas,
                    parsed,
                    staged,
                    validation,
                    operation_result,
                    warnings=[],
                    source=source,
                    achieved_fidelity="enhanced",
                )
                return promote_candidate(
                    parsed,
                    staged,
                    result,
                    source=source,
                    destination=destination,
                )
        except Exception as error:
            merge_source_preservation_failure(error, source.path, source.sha256)
            raise


def build_pypdf_service(project_root: Path) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    return PypdfService(project_root).execute
