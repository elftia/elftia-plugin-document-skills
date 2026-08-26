"""Bounded, transactional LibreOffice conversion from legacy PPT to PPTX."""

from pathlib import Path
import shutil
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import (
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
    sha256_file,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot
from document_skills_core.core.validation import validate_artifact

from .constants import MAX_PPTX_BYTES
from .contracts import ParsedPptxRequest
from .deep_validation import validate_deep_package
from .render_validation import bounded_file
from .transaction import promote_candidate, write_candidate_result
from .validation import reopen_pptx

MAX_LEGACY_PPT_BYTES = 128 * 1024 * 1024
LEGACY_CONVERSION_SECONDS = 30.0
_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def convert_legacy_ppt(
    request: ParsedPptxRequest,
    runner: Any,
    *,
    project_root: Path,
    version: str | None,
) -> dict[str, Any]:
    """Convert one preflighted CFB `.ppt` into a validated `.pptx`."""

    assert request.input_path is not None and request.output_path is not None
    source = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    cfb = preflight_legacy_ppt(request.input_path)
    try:
        with OperationTempRoot() as private_root:
            staged_input = _stage_source(
                request.input_path,
                source.sha256,
                private_root,
            )
            output_dir = private_root / "legacy-output"
            output_dir.mkdir()
            staged = runner.convert(
                staged_input,
                "pptx",
                output_dir,
                timeout_seconds=LEGACY_CONVERSION_SECONDS,
            )
            bounded_file(staged, MAX_PPTX_BYTES, "Converted PPTX")
            deep = validate_deep_package(staged)
            validation = validate_artifact(
                staged,
                expected_format="pptx",
                source_path=source.path,
                source_sha256=source.sha256,
                reopen=reopen_pptx,
                assertions=[
                    ("legacy-cfb-preflight", lambda _path: cfb),
                    ("legacy-pptx-deep-validation", lambda _path: deep),
                ],
            )
            if validation["status"] != "pass":
                _validation_failure(validation)
            result = write_candidate_result(
                request=request,
                schemas=_schema_catalog(project_root),
                staged=staged,
                validation=validation,
                operation_result={
                    "conversion": {
                        "provider": "libreoffice",
                        "provider_version": version,
                        "semantic_conversion": True,
                        "source_format": "ppt",
                        "source_visual_preservation_claimed": False,
                        "target_format": "pptx",
                        "slides": deep["inventory"]["slides"],
                    }
                },
                warnings=[
                    {
                        "code": "PPT_LEGACY_SEMANTIC_CONVERSION",
                        "message": (
                            "Legacy PPT was semantically converted; exact source "
                            "visual fidelity is not claimed."
                        ),
                    }
                ],
                source=source,
                status="degraded",
                degraded=True,
                degradations=[
                    {
                        "code": "PPT_LEGACY_SEMANTIC_CONVERSION",
                        "semantic_difference": (
                            "LibreOffice reconstructed legacy binary presentation "
                            "semantics into OOXML."
                        ),
                        "missing_capabilities": [],
                        "recommended_providers": [],
                    }
                ],
                achieved_fidelity="enhanced",
            )
            return promote_candidate(
                request,
                staged,
                result,
                source=source,
                destination=destination,
            )
    except Exception as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise


def preflight_legacy_ppt(path: Path) -> dict[str, Any]:
    """Validate the bounded Compound File Binary envelope without parsing macros."""

    if not path.is_file():
        raise DocumentSkillsError(
            ErrorCode.INPUT_NOT_FOUND,
            "Legacy PPT input does not exist.",
            details={"path": str(path)},
        )
    size = path.stat().st_size
    if size < 512 or size > MAX_LEGACY_PPT_BYTES:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Legacy PPT is empty, truncated, or exceeds the byte limit.",
            status="invalid_request",
            details={"bytes": size, "ceiling": MAX_LEGACY_PPT_BYTES},
        )
    with path.open("rb") as handle:
        header = handle.read(512)
    if not header.startswith(_CFB_MAGIC):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Legacy PPT does not have Compound File Binary magic bytes.",
            status="invalid_request",
        )
    major_version = int.from_bytes(header[26:28], "little")
    byte_order = header[28:30]
    sector_shift = int.from_bytes(header[30:32], "little")
    mini_sector_shift = int.from_bytes(header[32:34], "little")
    if (
        (major_version, sector_shift) not in {(3, 9), (4, 12)}
        or byte_order != b"\xfe\xff"
        or mini_sector_shift != 6
    ):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "Legacy PPT has an invalid Compound File Binary header.",
            status="invalid_request",
        )
    return {
        "bytes": size,
        "container": "cfb",
        "major_version": major_version,
        "sector_size": 1 << sector_shift,
    }


def _stage_source(source: Path, expected_sha256: str, private_root: Path) -> Path:
    staged = private_root / "input.ppt"
    shutil.copyfile(source, staged)
    if sha256_file(staged) != expected_sha256:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Legacy PPT source changed while it was staged for LibreOffice.",
            details={"source_changed_during_staging": True},
        )
    return staged


def _validation_failure(validation: dict[str, Any]) -> None:
    failed = [
        gate["id"]
        for gate in validation["gates"]
        if gate["required"] and gate["outcome"] != "pass"
    ]
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "LibreOffice legacy PPT conversion failed validation.",
        details={"failed_gates": failed},
        validation=validation,
    )


def _schema_catalog(project_root: Path) -> Any:
    from document_skills_core.core.contracts.schemas import SchemaCatalog

    return SchemaCatalog(project_root)
