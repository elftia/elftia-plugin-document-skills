"""Transactional provider-backed layered reconstruction service."""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import make_error_result
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_source_preserved,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import parse_pptx_request
from .reconstruction_models import (
    parse_reconstruction_observations,
    screen_reconstruction_raster,
)
from .reconstruction_scene import project_reconstruction_scene
from .reconstruction_transaction import (
    audit_artifact_record,
    audit_asset_path,
    promote_reconstruction_candidate,
)
from .reconstruction_validation import with_reconstruction_gate
from .scene_emitter import emit_scene_pptx
from .schema_validation import validate_schema_gate, with_schema_gate
from .transaction import write_candidate_result
from .validation import validate_scene_created


class PptxReconstructionService:
    def __init__(
        self,
        project_root: Path,
        adapter: Any,
        *,
        dotnet: Any = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.adapter = adapter
        self.dotnet = dotnet
        self.schemas = SchemaCatalog(self.project_root)

    def execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._execute(operation, request)
        except DocumentSkillsError as error:
            options = request.get("options", {})
            requested_fidelity = (
                options.get("fidelity", "core") if type(options) is dict else "unknown"
            )
            return make_error_result(
                operation,
                error,
                requested_fidelity=requested_fidelity,
            )

    def _execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_pptx_request(request)
        if operation != parsed.operation or operation != "pptx.reconstruct.from-image":
            raise DocumentSkillsError(
                code=ErrorCode.REQUEST_INVALID,
                message="OCR/vision provider binding does not match the request operation.",
                status="invalid_request",
            )
        assert parsed.input_path is not None
        assert parsed.output_path is not None
        raster = screen_reconstruction_raster(parsed.input_path)
        source = file_record(parsed.input_path, "input")
        if source.sha256 != raster.sha256 or source.bytes != raster.byte_count:
            raise DocumentSkillsError(
                code=ErrorCode.REQUEST_INVALID,
                message="Reconstruction source changed after screening.",
                status="invalid_request",
            )
        destination = destination_snapshot(parsed.output_path)
        retain_audit = parsed.arguments["audit_asset_policy"] == "retain"
        audit_path = (
            audit_asset_path(parsed.output_path, parsed.input_path, raster)
            if retain_audit
            else None
        )
        audit_destination = destination_snapshot(audit_path) if audit_path is not None else None
        audit_record = (
            audit_artifact_record(audit_path, raster) if audit_path is not None else None
        )
        base = self.project_root / ".document-skills-tmp" / "document-skills-operations"
        try:
            with OperationTempRoot(base=base) as private_root:
                extension = "png" if raster.media_type == "image/png" else "jpg"
                private_source = private_root / f"screened-source.{extension}"
                private_source.write_bytes(raster.bytes_value)
                observed = self.adapter.observe(private_source)
                observations = parse_reconstruction_observations(observed, raster)
                scene, receipt = project_reconstruction_scene(
                    observations,
                    raster,
                    private_root,
                    parsed.arguments["confidence_threshold"],
                )
                staged = private_root / "reconstructed.pptx"
                emission = emit_scene_pptx(staged, scene, parsed.arguments["metadata"])
                validation = validate_scene_created(staged, scene, emission)
                validation = with_schema_gate(
                    validation,
                    validate_schema_gate(staged, self.dotnet),
                )
                validation = with_reconstruction_gate(
                    validation,
                    staged,
                    scene,
                    emission,
                    receipt,
                )
                rasterized = sum(
                    item["outcome"] == "rasterized" for item in receipt["elements"]
                )
                audit_result = {
                    "policy": parsed.arguments["audit_asset_policy"],
                    "retained": audit_record is not None,
                }
                if audit_record is not None:
                    audit_result.update({
                        "bytes": audit_record.bytes,
                        "media_type": raster.media_type,
                        "path": audit_record.path,
                        "sha256": audit_record.sha256,
                    })
                operation_result = {
                    "audit_asset": audit_result,
                    "emission": {
                        key: value for key, value in emission.items() if key != "items"
                    },
                    "provider_policy": parsed.arguments["provider_policy"],
                    "reconstruction": receipt,
                    "source": {
                        "bytes": raster.byte_count,
                        "height": raster.height,
                        "media_type": raster.media_type,
                        "sha256": raster.sha256,
                        "width": raster.width,
                    },
                }
                degradations = (
                    [{
                        "code": "PPTX_RECONSTRUCTION_ELEMENT_RASTER_FALLBACK",
                        "semantic_difference": "Low-confidence elements are represented by explicit source-region raster crops.",
                        "missing_capabilities": [],
                        "recommended_providers": [],
                    }]
                    if rasterized
                    else []
                )
                result = write_candidate_result(
                    self.schemas,
                    parsed,
                    staged,
                    validation,
                    operation_result,
                    warnings=[],
                    source=source,
                    additional_artifacts=(
                        [audit_record] if audit_record is not None else []
                    ),
                    status="degraded" if rasterized else "success",
                    degraded=bool(rasterized),
                    degradations=degradations,
                )
                assert_source_preserved(source.path, source.sha256)
                return promote_reconstruction_candidate(
                    parsed,
                    staged,
                    private_source,
                    result,
                    source=source,
                    destination=destination,
                    audit_record=audit_record,
                    audit_destination=audit_destination,
                )
        except Exception as error:
            merge_source_preservation_failure(error, source.path, source.sha256)
            raise


def build_reconstruction_service(
    project_root: Path,
    adapter: Any,
    *,
    dotnet: Any = None,
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    return PptxReconstructionService(
        project_root,
        adapter,
        dotnet=dotnet,
    ).execute

__all__ = ["PptxReconstructionService", "build_reconstruction_service"]
