"""Transactional provider service for Poppler render and Tesseract OCR."""

from collections.abc import Callable
from pathlib import Path
import time
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import make_error_result
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    ArtifactRecord,
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

from .archive import validate_archive
from .deadline import OperationDeadline
from .detector import PdfToolDetector
from .ocr import ocr_pdf
from .ocr_semantics import validate_ocr_archive
from .render import render_pdf
from .runner import PdfToolRunner

_RENDER_OPERATION_TIMEOUT_SECONDS = 120.0
_OCR_OPERATION_TIMEOUT_SECONDS = 300.0


class PdfToolService:
    def __init__(
        self,
        project_root: Path,
        *,
        operation: str,
        detector: PdfToolDetector,
        runner: PdfToolRunner | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.project_root = project_root.resolve()
        self.operation = operation
        self.detector = detector
        self.runner = runner or PdfToolRunner(self.project_root)
        self.clock = clock
        self.schemas = SchemaCatalog(self.project_root)

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
        if operation != self.operation:
            raise DocumentSkillsError(
                ErrorCode.OPERATION_UNKNOWN,
                "Optional PDF provider binding does not match the operation.",
                status="invalid_request",
            )
        deadline = OperationDeadline(
            _timeout_for_operation(operation),
            clock=self.clock,
        )
        evidence = self.detector.detect()
        deadline.check()
        if not evidence.available:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "The required PDF external provider is not callable.",
                status="unavailable",
            )
        self.runner.configure(
            self.detector.accepted_paths(),
            languages=self.detector.accepted_languages(),
        )
        parsed = parse_pdf_request(request)
        if operation == "pdf.ocr":
            self.runner.require_languages(parsed.arguments["languages"])
        deadline.check()
        assert parsed.input_path is not None
        assert parsed.output_path is not None
        assert_distinct_paths(parsed.input_path, parsed.output_path, in_place=False)
        source = file_record(parsed.input_path, "input")
        destination = destination_snapshot(parsed.output_path)
        reference = None
        if operation == "pdf.render" and parsed.arguments["compare_to"] is not None:
            reference = file_record(parsed.arguments["compare_to"], "reference")
            if reference.sha256 != parsed.arguments["reference_sha256"]:
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "Render reference does not match reference_sha256.",
                    details={
                        "role": "reference",
                        "expected_sha256": parsed.arguments["reference_sha256"],
                        "actual_sha256": reference.sha256,
                    },
                )
        try:
            with OperationTempRoot() as private_root:
                staged = private_root / "sidecar.zip"
                if operation == "pdf.render":
                    operation_result, manifest, records = render_pdf(
                        parsed.input_path,
                        staged,
                        parsed.arguments,
                        private_root=private_root,
                        runner=self.runner,
                        deadline=deadline,
                        reference=Path(reference.path) if reference is not None else None,
                    )
                else:
                    operation_result, manifest, records = ocr_pdf(
                        parsed.input_path,
                        staged,
                        parsed.arguments,
                        private_root=private_root,
                        runner=self.runner,
                        deadline=deadline,
                    )
                validation = validate_archive(
                    staged,
                    payload_records=records,
                    manifest=manifest,
                    source=parsed.input_path,
                    source_sha256=source.sha256,
                    reference=(
                        Path(reference.path) if reference is not None else None
                    ),
                    reference_sha256=(
                        reference.sha256 if reference is not None else None
                    ),
                    render_comparison=manifest.get("comparison"),
                    render_arguments=(
                        parsed.arguments if operation == "pdf.render" else None
                    ),
                )
                if operation == "pdf.ocr":
                    ocr_validation = validate_ocr_archive(
                        staged,
                        parsed.input_path,
                        manifest,
                        parsed.arguments,
                    )
                    validation["gates"].extend(ocr_validation["gates"])
                    if ocr_validation["status"] != "pass":
                        validation["status"] = "fail"
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
                    preserved_inputs=(
                        [reference] if reference is not None else None
                    ),
                )
        except Exception as error:
            merge_source_preservation_failure(error, source.path, source.sha256)
            if reference is not None:
                _merge_reference_preservation_failure(error, reference)
            raise


def _timeout_for_operation(operation: str) -> float:
    if operation == "pdf.render":
        return _RENDER_OPERATION_TIMEOUT_SECONDS
    return _OCR_OPERATION_TIMEOUT_SECONDS


def _merge_reference_preservation_failure(
    error: BaseException,
    reference: ArtifactRecord,
) -> None:
    try:
        from document_skills_core.core.io.paths import assert_source_preserved

        assert_source_preserved(reference.path, reference.sha256)
    except Exception as check_error:
        if isinstance(error, DocumentSkillsError):
            reference_error = (
                check_error
                if isinstance(check_error, DocumentSkillsError)
                else DocumentSkillsError(
                    ErrorCode.INTERNAL_ERROR,
                    "Reference preservation could not be checked after failure.",
                    details={"reason": type(check_error).__name__},
                )
            )
            error.details["reference_preservation"] = {
                "status": "fail",
                "error": reference_error.record(),
            }
        else:
            error.add_note("Render reference preservation also failed.")
