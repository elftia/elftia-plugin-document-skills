"""Transactional constrained-SVG creation through the shared scene emitter."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_source_preserved,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedPptxRequest
from .scene_emitter import emit_scene_pptx
from .schema_validation import validate_schema_gate, with_schema_gate
from .svg_parser import compile_svg_scene
from .transaction import promote_candidate, write_candidate_result
from .validation import validate_scene_created
from .visual_validation import validate_scene_visuals, with_visual_gate


def create_from_svg(
    request: ParsedPptxRequest,
    *,
    schemas: SchemaCatalog,
    libreoffice: Any,
    dotnet: Any,
) -> dict[str, Any]:
    assert request.input_path is not None
    assert request.output_path is not None
    source = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    try:
        with OperationTempRoot() as private_root:
            scene = compile_svg_scene(
                request.input_path,
                fallback_policy=request.arguments["fallback_policy"],
            )
            staged = private_root / "created-from-svg.pptx"
            emission = emit_scene_pptx(
                staged,
                scene,
                request.arguments["metadata"],
            )
            validation = validate_scene_created(staged, scene, emission)
            validation = with_schema_gate(
                validation,
                validate_schema_gate(staged, dotnet),
            )
            visual_gate = validate_scene_visuals(
                staged,
                scene,
                libreoffice,
                private_root,
            )
            validation = with_visual_gate(validation, visual_gate)
            outcomes = scene.diagnostics["outcomes"]
            fidelity_degraded = (
                outcomes.get("approximated", 0) > 0
                or outcomes.get("rasterized", 0) > 0
            )
            visual_degraded = visual_gate["outcome"] != "pass"
            degraded = fidelity_degraded or visual_degraded
            operation_result = {
                "conversion": scene.diagnostics,
                "coverage": _coverage(scene),
                "emission": {
                    key: value for key, value in emission.items() if key != "items"
                },
                "mapping": [
                    {
                        "asset_sha256": item["asset_sha256"],
                        "geometry": item["geometry"],
                        "kind": item["kind"],
                        "outcome": item["outcome"],
                        "parent_source_id": item["parent_source_id"],
                        "shape_id": item["shape_id"],
                        "source_id": item["source_id"],
                    }
                    for item in emission["items"][:256]
                ],
                "mapping_truncated": max(0, len(emission["items"]) - 256),
                "policy": {
                    "fallback": request.arguments["fallback_policy"],
                    "whole_slide_raster": "forbidden",
                },
            }
            degradations = []
            if fidelity_degraded:
                degradations.append({
                    "code": "SVG_ELEMENT_FALLBACK",
                    "semantic_difference": "Some SVG nodes were approximated or replaced by explicit element-level raster assets.",
                    "missing_capabilities": [],
                    "recommended_providers": [],
                })
            if visual_degraded:
                degradations.append({
                    "code": "SVG_VISUAL_PARITY_UNESTABLISHED",
                    "semantic_difference": "Optional visual parity was unavailable or outside the declared thresholds.",
                    "missing_capabilities": (
                        ["libreoffice.render-image"]
                        if visual_gate["outcome"] == "unavailable"
                        else []
                    ),
                    "recommended_providers": (
                        ["libreoffice"]
                        if visual_gate["outcome"] == "unavailable"
                        else []
                    ),
                })
            result = write_candidate_result(
                schemas,
                request,
                staged,
                validation,
                operation_result,
                warnings=[],
                source=source,
                status="degraded" if degraded else "success",
                degraded=degraded,
                degradations=degradations,
            )
            assert_source_preserved(source.path, source.sha256)
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


def _coverage(scene: Any) -> dict[str, Any]:
    slide_area = 1920 * 1080 * len(scene.slides)
    fidelity = scene.diagnostics["fidelity"]
    native_area = fidelity["native"]["area"]
    approximated_area = fidelity["approximated"]["area"]
    rasterized_area = fidelity["rasterized"]["area"]
    return {
        "approximated_area": approximated_area,
        "native_area": native_area,
        "native_ratio": min(1.0, native_area / slide_area),
        "rasterized_area": rasterized_area,
        "rasterized_ratio": min(1.0, rasterized_area / slide_area),
        "slide_area": slide_area,
        "whole_slide_raster": False,
    }


__all__ = ["create_from_svg"]
