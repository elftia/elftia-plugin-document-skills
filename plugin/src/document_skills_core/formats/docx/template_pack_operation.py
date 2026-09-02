"""Catalog, read, and instantiation operations for DOCX template packs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import destination_snapshot, sha256_file
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedDocxRequest
from .conversion import validate_pdf_conversion
from .create import create_docx
from .document_spec import parse_document_spec
from .layout_inspection import inspect_rendered_layout
from .rendering import _provider_identity, _render_page_evidence
from .results import success_result
from .template_import import _pack_validation
from .template_operation import template_operation
from .template_pack import (
    load_builtin_catalog,
    public_pack_manifest,
    resolve_pack_reference,
    snapshot_pack_reference,
)
from .transaction import promote_candidate, write_candidate_result
from .validation import validate_created

_MAX_RENDER_BYTES = 8 * 1024 * 1024
_MAX_RENDER_PAGES = 16
_MAX_PAGE_BYTES = 4 * 1024 * 1024
_MAX_PNG_TOTAL_BYTES = 16 * 1024 * 1024


def list_pack_operation(
    request: ParsedDocxRequest,
    *,
    project_root: Path,
    schemas: SchemaCatalog,
) -> dict[str, Any]:
    packs = []
    for entry in load_builtin_catalog(project_root):
        packs.append(
            resolve_pack_reference(
                project_root,
                schemas,
                {"kind": "builtin", "id": entry["id"], "version": entry["version"]},
            ).summary()
        )
    for reference in request.arguments["local_packs"]:
        packs.append(resolve_pack_reference(project_root, schemas, reference).summary())
    return success_result(
        request,
        artifacts=[],
        operation_result={"packs": packs, "count": len(packs), "ambient_scan": False, "diagnostics": []},
        warnings=[],
        validation=_pack_validation(
            "docx.template-pack-catalog",
            evidence={"count": len(packs), "ambient_scan": False},
        ),
    )


def read_pack_operation(
    request: ParsedDocxRequest,
    *,
    project_root: Path,
    schemas: SchemaCatalog,
) -> dict[str, Any]:
    pack = resolve_pack_reference(project_root, schemas, request.arguments["pack"])
    artifacts = []
    if pack.reference_kind == "local":
        artifacts.append(
            {
                "role": "input",
                "path": str(pack.root / "manifest.json"),
                "sha256": pack.manifest_sha256,
                "bytes": pack.manifest_bytes,
            }
        )
    return success_result(
        request,
        artifacts=artifacts,
        operation_result={"pack": public_pack_manifest(pack)},
        warnings=[],
        validation=_pack_validation(
            "docx.template-pack-read",
            evidence={"manifest_sha256": pack.manifest_sha256},
        ),
    )


def instantiate_pack_operation(
    request: ParsedDocxRequest,
    *,
    project_root: Path,
    schemas: SchemaCatalog,
    apply_backend: Callable[..., tuple[Any, dict[str, Any]]],
    libreoffice: Any = None,
) -> dict[str, Any]:
    assert request.output_path is not None
    with OperationTempRoot() as operation_root:
        pack = snapshot_pack_reference(
            project_root,
            schemas,
            request.arguments["pack"],
            operation_root / "pack-snapshot",
        )
        mode = request.arguments["mode"]
        if mode not in pack.manifest["capabilities"]["modes"]:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Template pack does not declare the requested instantiation mode.",
                details={"diagnostic": "DS_DOCX_TEMPLATE_MODE_UNSUPPORTED", "mode": mode},
            )
        if mode == "template":
            result = _instantiate_template(
                request,
                pack,
                project_root=project_root,
                schemas=schemas,
                apply_backend=apply_backend,
            )
        else:
            result = _instantiate_document_spec(request, pack, schemas=schemas)
        operation_result = dict(result["diagnostics"].get("operation_result", {}))
        operation_result["pack"] = {
            "id": pack.manifest["id"],
            "version": pack.manifest["version"],
            "manifest_sha256": pack.manifest_sha256,
            "payload_sha256": pack.manifest["payload"]["sha256"],
            "mode": mode,
            "authoring_source": "operation-owned-verified-snapshot",
        }
        rendered_evidence = _rendered_evidence(
            request.arguments["verification"],
            candidate=request.output_path,
            pack=pack,
            libreoffice=libreoffice,
        )
        operation_result["rendered_evidence"] = rendered_evidence
        result["diagnostics"] = {
            **result["diagnostics"],
            "operation_result": operation_result,
        }
        if request.arguments["verification"] == "enhanced":
            warning = _render_warning(rendered_evidence)
            result["warnings"] = [
                *result["warnings"],
                *([warning] if warning is not None else []),
            ]
            visual_gate = next(
                (gate for gate in result["validation"]["gates"] if gate["id"] == "visual.render"),
                None,
            )
            if visual_gate is not None and rendered_evidence["status"] == "pass":
                visual_gate.update(
                    {
                        "outcome": "pass",
                        "evidence": {
                            "provider": "libreoffice",
                            "render_status": "pass",
                            "visual_comparison_succeeded": False,
                        },
                        "warnings": ["Rendering passed; no comparable visual baseline was declared."],
                    }
                )
        return result


def _instantiate_template(
    request: ParsedDocxRequest,
    pack: Any,
    *,
    project_root: Path,
    schemas: SchemaCatalog,
    apply_backend: Callable[..., tuple[Any, dict[str, Any]]],
) -> dict[str, Any]:
    declared_variables = {
        item["name"]: item["required"]
        for item in pack.manifest["capabilities"]["variables"]
    }
    supplied = set(request.arguments["variables"])
    missing = sorted(name for name, required in declared_variables.items() if required and name not in supplied)
    undeclared = sorted(supplied - set(declared_variables))
    if missing or undeclared:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Template variables do not match the pack declaration.",
            details={"diagnostic": "DS_DOCX_TEMPLATE_CONTROL_MISMATCH", "missing": missing, "undeclared": undeclared},
        )
    declared_regions = {
        (item["type"], item["paragraph_index"], item["expected_text"])
        for item in pack.manifest["capabilities"]["regions"]
    }
    invalid_regions = [
        {
            "type": item["type"],
            "paragraph_index": item["target"]["paragraph_index"],
        }
        for item in request.arguments.get("regions", [])
        if (item["type"], item["target"]["paragraph_index"], item["target"]["expected_text"])
        not in declared_regions
    ]
    if invalid_regions:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Template regions do not match the pack declaration.",
            details={"diagnostic": "DS_DOCX_TEMPLATE_CONTROL_MISMATCH", "regions": invalid_regions},
        )
    adapted = ParsedDocxRequest(
        request.operation,
        pack.payload_path,
        request.output_path,
        {
            "variables": request.arguments["variables"],
            "missing_policy": request.arguments["missing_policy"],
            **({"regions": request.arguments["regions"]} if "regions" in request.arguments else {}),
        },
        request.requested_fidelity,
    )
    return template_operation(
        adapted,
        project_root=project_root,
        schemas=schemas,
        apply_backend=apply_backend,
    )


def _instantiate_document_spec(
    request: ParsedDocxRequest,
    pack: Any,
    *,
    schemas: SchemaCatalog,
) -> dict[str, Any]:
    document_spec = request.arguments["document_spec"]
    compatibility = pack.manifest["compatibility"]
    if document_spec.get("version") not in compatibility["document_spec_versions"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Document-spec version is incompatible with the template pack.",
            details={"diagnostic": "DS_DOCX_TEMPLATE_PROFILE_INCOMPATIBLE"},
        )
    domain = document_spec.get("domain_profile")
    domain_key = (
        {"id": domain.get("id"), "version": domain.get("version")}
        if type(domain) is dict
        else None
    )
    if domain_key not in compatibility["domain_profiles"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Document domain profile is incompatible with the template pack.",
            details={"diagnostic": "DS_DOCX_TEMPLATE_PROFILE_INCOMPATIBLE", "domain_profile": domain_key},
        )
    authoring_format = pack.manifest["capabilities"].get("authoring_format")
    authored_spec = dict(document_spec)
    if authoring_format is not None:
        if authored_spec.get("footer") is None:
            authored_spec["footer"] = authoring_format["default_footer"]
        authored_spec["nodes"] = [
            _apply_table_format(node, authoring_format["table"])
            for node in document_spec["nodes"]
        ]
    injected = {
        **authored_spec,
        "style_profile": {
            "id": "template-mapped",
            "version": "1.0",
            "source": str(pack.payload_path),
            "expected_source_sha256": pack.manifest["payload"]["sha256"],
            "role_styles": pack.manifest["capabilities"]["role_styles"],
        },
    }
    report = parse_document_spec(injected)
    if authoring_format is not None:
        report["style_profile"]["role_formats"] = authoring_format["role_formats"]
    destination = destination_snapshot(request.output_path)
    with OperationTempRoot() as private_root:
        staged = private_root / "pack-document-spec.docx"
        creation = create_docx(staged, report)
        validation = validate_created(staged, report, creation["images"], creation["styles"])
        result = write_candidate_result(
            schemas,
            request,
            staged,
            validation,
            {"creation": creation, "adapter": "pack-owned-template-mapped"},
            warnings=[],
            source=None,
        )
        return promote_candidate(
            request,
            staged,
            result,
            source=None,
            destination=destination,
        )


def _rendered_evidence(
    verification: str,
    *,
    candidate: Path,
    pack: Any,
    libreoffice: Any,
) -> dict[str, Any]:
    if verification == "core":
        return {
            "status": "not_run",
            "provider_context": {"provider": None, "fonts": []},
            "visual_comparison_succeeded": False,
            "reason": "Enhanced verification was not requested.",
        }
    if libreoffice is None:
        return _render_failure(
            "unavailable",
            "The LibreOffice provider is unavailable.",
        )
    try:
        with OperationTempRoot() as private_root:
            rendered_pdf = private_root / "pack-render.pdf"
            payload = libreoffice.convert_pdf(candidate, _MAX_RENDER_BYTES)
            if type(payload) is not bytes:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "LibreOffice returned an invalid template-pack PDF payload.",
                )
            rendered_pdf.write_bytes(payload)
            _validation, reopened = validate_pdf_conversion(
                rendered_pdf,
                source=candidate,
                source_sha256=sha256_file(candidate),
                max_output_bytes=_MAX_RENDER_BYTES,
            )
            page_count = int(reopened["pages"])
            if page_count > _MAX_RENDER_PAGES:
                raise DocumentSkillsError(
                    ErrorCode.RESOURCE_LIMIT,
                    "Rendered template-pack evidence exceeds its page limit.",
                    details={"pages": page_count, "max_pages": _MAX_RENDER_PAGES},
                )
            layout: dict[str, Any] = {
                "status": "unavailable",
                "reason": "The provider does not expose bounded PNG page evidence.",
            }
            pages: list[dict[str, Any]] = []
            raster = (
                libreoffice.try_render_to_image
                if hasattr(libreoffice, "try_render_to_image")
                else None
            )
            if callable(raster):
                _public_pages, internal_pages = _render_page_evidence(
                    rendered_pdf,
                    original_range="all",
                    maximum_page_bytes=_MAX_PAGE_BYTES,
                    maximum_total_bytes=_MAX_PNG_TOTAL_BYTES,
                    libreoffice=libreoffice,
                    private_root=private_root,
                )
                pages = [
                    {key: value for key, value in page.items() if key != "payload"}
                    for page in internal_pages
                ]
                layout = inspect_rendered_layout(candidate, internal_pages, dpi=96)
            identity = _provider_identity(libreoffice)
            preview = next(
                (item for item in pack.manifest["evidence"] if item["kind"] == "preview"),
                None,
            )
            return {
                "status": "pass",
                "provider_context": {
                    "provider": identity["id"],
                    "version": identity["version"],
                    "fonts": [],
                },
                "render": {
                    "format": "pdf",
                    "pages": page_count,
                    "bytes": rendered_pdf.stat().st_size,
                    "sha256": sha256_file(rendered_pdf),
                    "page_evidence": pages,
                },
                "layout": layout,
                "declared_preview": preview,
                "visual_comparison_succeeded": False,
                "reason": "Rendering passed, but the pack declares no comparable visual baseline.",
            }
    except DocumentSkillsError as error:
        status = "unavailable" if error.code == ErrorCode.PROVIDER_UNAVAILABLE else "failed"
        return _render_failure(status, str(error), error_code=error.code.value)
    except Exception as error:
        return _render_failure(
            "failed",
            "Enhanced template-pack rendering failed without a visual-success claim.",
            error_type=type(error).__name__,
        )


def _apply_table_format(
    node: dict[str, Any],
    table_format: dict[str, Any],
) -> dict[str, Any]:
    if node.get("type") != "table":
        return node
    width = node.get("width_twips", table_format["width_twips"])
    return {
        **node,
        "width_twips": width,
        **(
            {}
            if "column_widths_twips" in node
            else {
                "column_widths_twips": _distributed_widths(
                    width,
                    len(node["rows"][0]),
                )
            }
        ),
        "borders": node.get("borders", table_format["borders"]),
    }


def _distributed_widths(total: int, count: int) -> list[int]:
    quotient, remainder = divmod(total, count)
    return [quotient + (1 if index < remainder else 0) for index in range(count)]


def _render_failure(status: str, reason: str, **details: Any) -> dict[str, Any]:
    return {
        "status": status,
        "provider_context": {"provider": "libreoffice", "version": None, "fonts": []},
        "visual_comparison_succeeded": False,
        "reason": reason,
        **({"details": details} if details else {}),
    }


def _render_warning(evidence: dict[str, Any]) -> dict[str, Any] | None:
    status = evidence["status"]
    if status == "pass":
        return {
            "code": "DS_DOCX_TEMPLATE_VISUAL_BASELINE_UNAVAILABLE",
            "message": "Enhanced rendering passed, but no comparable pack visual baseline was declared.",
            "details": {"provider": "libreoffice", "status": "pass"},
        }
    if status == "unavailable":
        return {
            "code": "DS_DOCX_TEMPLATE_RENDER_EVIDENCE_UNAVAILABLE",
            "message": "Enhanced pack rendering is unavailable; no visual-success claim was made.",
            "details": {"provider": "libreoffice", "status": status},
        }
    return {
        "code": "DS_DOCX_TEMPLATE_RENDER_EVIDENCE_FAILED",
        "message": "Enhanced pack rendering failed; the verified DOCX remains available without a visual-success claim.",
        "details": {"provider": "libreoffice", "status": status},
    }


__all__ = [
    "instantiate_pack_operation",
    "list_pack_operation",
    "read_pack_operation",
]
