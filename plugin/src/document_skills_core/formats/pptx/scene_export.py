"""Transactional PPTX to A-Contract Deck IR and constrained-SVG bundle export."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import (
    apply_committed_promotion,
    gate_record,
)
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.core_properties import project_core_properties
from document_skills_core.core.io.directory_promotion import atomic_publish_directory
from document_skills_core.core.io.paths import (
    ArtifactRecord,
    assert_source_preserved,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .constants import NS
from .contracts import ParsedPptxRequest
from .package import OpcPackage
from .presentation_contracts import (
    PresentationContractConsumer,
    PresentationContractConsumerError,
)
from .results import success_result
from .scene_export_objects import project_scene_objects

_P = NS["p"]


def export_scene_bundle(
    request: ParsedPptxRequest,
    *,
    schemas: SchemaCatalog,
) -> dict[str, Any]:
    assert request.input_path is not None
    assert request.output_path is not None
    source = file_record(request.input_path, "input")
    try:
        consumer = _contract_consumer(request.arguments["contract"]["root"])
        package = OpcPackage.open(request.input_path)
        slide_cx, slide_cy = _slide_size(package)
        identity = request.arguments["identity"]
        deck_id = consumer.stable_deck_id(
            namespace=identity["namespace"],
            source_template_id=identity["source_template_id"],
            source_template_version=identity["source_template_version"],
        )
        projection = project_scene_objects(
            package,
            consumer,
            deck_id=deck_id,
            source_template_id=identity["source_template_id"],
            mode=request.arguments["mode"],
            slide_cx=slide_cx,
            slide_cy=slide_cy,
        )
        deck_ir = _deck_ir(
            package,
            consumer,
            deck_id,
            projection.slides,
            slide_cx,
            slide_cy,
            projection.unsupported,
        )
        consumer.validate("deck-ir", deck_ir)
        with OperationTempRoot() as private_root:
            stage = private_root / "scene-bundle"
            stage.mkdir(mode=0o700)
            _write_json(stage / "deck-ir.json", deck_ir)
            for relative, payload in sorted(projection.svg_members.items()):
                (stage / relative).write_bytes(payload)
            for relative, payload in sorted(projection.asset_members.items()):
                destination = stage / Path(relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
            manifest = _manifest(
                stage,
                request,
                source,
                deck_id,
                projection.source_mapping,
                projection.unsupported,
            )
            _write_json(stage / "manifest.json", manifest)
            manifest_record = file_record(stage / "manifest.json", "output")
            _validate_manifest(stage, manifest)
            validation = _validation(
                deck_ir,
                manifest,
                projection.unsupported,
                request.arguments["mode"],
            )
            degraded = bool(projection.unsupported)
            status = "degraded" if degraded else "success"
            final_manifest = ArtifactRecord(
                "output",
                str(request.output_path / "manifest.json"),
                manifest_record.sha256,
                manifest_record.bytes,
            )
            operation_result = {
                "bundle": {
                    "deck_ir": "deck-ir.json",
                    "manifest_sha256": manifest_record.sha256,
                    "members": len(manifest["members"]) + 1,
                    "output_directory": str(request.output_path),
                    "svg_slides": len(projection.svg_members),
                },
                "contract": consumer.summary(),
                "deck": {
                    "content_hash": deck_ir["contentHash"],
                    "deck_id": deck_id,
                    "objects": sum(len(slide["objects"]) for slide in projection.slides),
                    "slides": len(projection.slides),
                },
                "mode": request.arguments["mode"],
                "source_mapping": projection.source_mapping[:256],
                "source_mapping_truncated": max(0, len(projection.source_mapping) - 256),
                "unsupported": projection.unsupported[:128],
                "unsupported_truncated": max(0, len(projection.unsupported) - 128),
            }
            degradations = []
            if degraded:
                degradations.append({
                    "code": "SCENE_EXPORT_OPAQUE_OBJECTS",
                    "semantic_difference": "Tolerant export retained unsupported PPTX objects as opaque inventory rather than claiming round-trip editability.",
                    "missing_capabilities": [],
                    "recommended_providers": [],
                })
            result = success_result(
                request,
                artifacts=[source.as_dict(), final_manifest.as_dict()],
                operation_result=operation_result,
                warnings=[],
                validation=validation,
                status=status,
                degraded=degraded,
                degradations=degradations,
            )
            schemas.validate("operation-result", result)
            assert_source_preserved(source.path, source.sha256)
            promoted = atomic_publish_directory(
                stage,
                request.output_path,
                expected_manifest_sha256=manifest_record.sha256,
            )
            source_error = None
            try:
                assert_source_preserved(source.path, source.sha256)
            except DocumentSkillsError as error:
                source_error = error
            return apply_committed_promotion(
                result,
                promoted,
                source_error=source_error,
            )
    except Exception as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise


def _contract_consumer(root: Path) -> PresentationContractConsumer:
    try:
        return PresentationContractConsumer.open(root)
    except PresentationContractConsumerError as error:
        raise DocumentSkillsError(
            ErrorCode.STALE_PRECONDITION,
            "Scene export A-Contract binding is invalid or stale.",
            status="invalid_request",
            details={"contract_code": error.code, "issues": list(error.issues)},
        ) from error


def _slide_size(package: OpcPackage) -> tuple[int, int]:
    presentation = package.xml("ppt/presentation.xml")
    size = presentation.find(f"{{{_P}}}sldSz")
    try:
        cx = int(size.attrib["cx"]) if size is not None else 0
        cy = int(size.attrib["cy"]) if size is not None else 0
    except (KeyError, ValueError):
        cx, cy = 0, 0
    if cx <= 0 or cy <= 0:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Scene export source has no valid slide canvas.",
        )
    return cx, cy


def _deck_ir(
    package: OpcPackage,
    consumer: PresentationContractConsumer,
    deck_id: str,
    slides: list[dict[str, Any]],
    slide_cx: int,
    slide_cy: int,
    unsupported: list[dict[str, Any]],
) -> dict[str, Any]:
    metadata = project_core_properties(package.parts)
    unsupported_features = sorted({item["reason"] for item in unsupported})
    deck: dict[str, Any] = {
        "schemaVersion": consumer.pin.deck_ir_schema_version,
        "contractVersion": consumer.pin.package_version,
        "featureFlags": ["scene-export"],
        "migration": {"minimumReaderVersion": "1.0.0", "policy": "explicit-only"},
        "deckId": deck_id,
        "canvasProfiles": [{
            "height": slide_cy,
            "id": "source-canvas",
            "unit": "emu",
            "width": slide_cx,
        }],
        "refs": {"licenseStatus": "not_evaluated"},
        "editability": "partial" if unsupported else "native",
        "nativeTarget": "both",
        "degradationBudget": {
            "allowedFallbacks": ["opaque-inventory"] if unsupported else [],
            "maximum": "drop" if unsupported else "none",
        },
        "slides": slides,
        "materializationDiagnostics": [],
        "unsupportedFeatures": unsupported_features,
        "generatedBy": {
            "contractVersion": consumer.pin.package_version,
            "producer": "document-skills",
        },
    }
    if metadata.get("title"):
        deck["title"] = metadata["title"]
    deck["contentHash"] = consumer.deck_content_hash(deck)
    return deck


def _manifest(
    stage: Path,
    request: ParsedPptxRequest,
    source: ArtifactRecord,
    deck_id: str,
    source_mapping: list[dict[str, Any]],
    unsupported: list[dict[str, Any]],
) -> dict[str, Any]:
    members = []
    for path in sorted(item for item in stage.rglob("*") if item.is_file()):
        relative = path.relative_to(stage).as_posix()
        payload = path.read_bytes()
        members.append({
            "bytes": len(payload),
            "path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    return {
        "schema_version": "1.0",
        "operation": request.operation,
        "mode": request.arguments["mode"],
        "deck_id": deck_id,
        "source": {
            "bytes": source.bytes,
            "path": source.path,
            "sha256": source.sha256,
        },
        "contract": {
            "manifest_sha256": request.arguments["contract"]["manifest_sha256"],
            "package": "@elftia/presentation-contracts",
            "version": "1.0.0",
        },
        "members": members,
        "source_mapping": source_mapping,
        "unsupported": unsupported,
    }


def _validate_manifest(stage: Path, manifest: dict[str, Any]) -> None:
    observed = []
    for record in manifest["members"]:
        path = stage / Path(record["path"])
        payload = path.read_bytes()
        observed.append({
            "bytes": len(payload),
            "path": record["path"],
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    if observed != manifest["members"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Scene bundle member hash validation failed.",
        )


def _validation(
    deck_ir: dict[str, Any],
    manifest: dict[str, Any],
    unsupported: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    gates = [
        gate_record(
            "pptx.package-security",
            "pass",
            evidence={"policy": "reject", "source_reopened": True},
        ),
        gate_record(
            "operation.scene-projection",
            "pass",
            evidence={
                "mode": mode,
                "objects": sum(len(slide["objects"]) for slide in deck_ir["slides"]),
                "unsupported": len(unsupported),
            },
        ),
        gate_record(
            "contract.deck-ir",
            "pass",
            evidence={"content_hash": deck_ir["contentHash"]},
        ),
        gate_record(
            "bundle.manifest",
            "pass",
            evidence={"members": len(manifest["members"])},
        ),
        gate_record(
            "visual.roundtrip",
            "not_run",
            required=False,
            evidence={"reason": "Visual round-trip evidence is a fixture/release gate and was not requested by this Core projection."},
        ),
    ]
    return {"schema_version": "1.0", "status": "pass", "gates": gates}


def _write_json(path: Path, value: Any) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    path.write_bytes(payload)


__all__ = ["export_scene_bundle"]
