"""Transactional provider service for Poppler render and Tesseract OCR."""

from pathlib import Path
from typing import Any

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

from .archive import validate_archive
from .detector import PdfToolDetector
from .ocr import ocr_pdf
from .render import render_pdf
from .runner import PdfToolRunner


class PdfToolService:
    def __init__(
        self,
        project_root: Path,
        *,
        operation: str,
        detector: PdfToolDetector,
    ) -> None:
        self.project_root = project_root.resolve()
        self.operation = operation
        self.detector = detector
        self.runner = PdfToolRunner(self.project_root)
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
        evidence = self.detector.detect()
        if not evidence.available:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "The required PDF external provider is not callable.",
                status="unavailable",
            )
        self.runner.configure(self.detector.accepted_paths())
        parsed = parse_pdf_request(request)
        assert parsed.input_path is not None
        assert parsed.output_path is not None
        assert_distinct_paths(parsed.input_path, parsed.output_path, in_place=False)
        source = file_record(parsed.input_path, "input")
        destination = destination_snapshot(parsed.output_path)
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
                    )
                else:
                    operation_result, manifest, records = ocr_pdf(
                        parsed.input_path,
                        staged,
                        parsed.arguments,
                        private_root=private_root,
                        runner=self.runner,
                    )
                validation = validate_archive(
                    staged,
                    payload_records=records,
                    manifest=manifest,
                    source=parsed.input_path,
                    source_sha256=source.sha256,
                )
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
