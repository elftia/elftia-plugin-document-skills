"""Fail-closed DOCX/DOTX reference inspection and canonical pack import."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil
import stat
from typing import Any

from document_skills_core import __version__
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.directory_promotion import atomic_publish_directory
from document_skills_core.core.io.paths import (
    assert_source_preserved,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .constants import NS, WORD_MAIN, qn
from .contracts import ParsedDocxRequest
from .mapping import document_stories, iter_paragraphs, map_paragraph
from .package import OpcPackage
from .results import success_result
from .style_profiles import render_style_profile
from .template import TOKEN_PATTERN
from .template_format_inventory import inspect_format_features, mode_compatibility
from .template_regions import executable_body_paragraphs
from .template_pack import (
    canonical_json_bytes,
    member_record,
    public_pack_manifest,
    resolve_pack_directory,
)

_REPARSE_POINT = 0x400


def inspect_reference_operation(request: ParsedDocxRequest) -> dict[str, Any]:
    assert request.input_path is not None
    source = file_record(request.input_path, "input")
    expected = request.arguments["expected_source_sha256"]
    if source.sha256 != expected:
        raise DocumentSkillsError(
            ErrorCode.STALE_PRECONDITION,
            "Reference source digest does not match expected_source_sha256.",
            status="invalid_request",
            details={"diagnostic": "DS_DOCX_TEMPLATE_SOURCE_IDENTITY"},
        )
    try:
        result = inspect_reference(request.input_path, expected)
        assert_source_preserved(source.path, source.sha256)
    except Exception as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise
    return success_result(
        request,
        artifacts=[source.as_dict()],
        operation_result=result,
        warnings=[],
        validation=_pack_validation(
            "docx.template-reference-inspection",
            evidence={"source_sha256": source.sha256, "safe": True},
        ),
    )


def inspect_reference(path: Path, expected_sha256: str) -> dict[str, Any]:
    _assert_plain_source(path)
    source = file_record(path, "input")
    if source.sha256 != expected_sha256:
        raise DocumentSkillsError(
            ErrorCode.STALE_PRECONDITION,
            "Reference source changed before inspection.",
            status="invalid_request",
            details={"diagnostic": "DS_DOCX_TEMPLATE_SOURCE_IDENTITY"},
        )
    package = OpcPackage.open(
        path,
        allow_template_main=path.suffix.casefold() == ".dotx",
    )
    styles, style_diagnostics = _style_inventory(package)
    variables, regions, token_diagnostics = _template_inventory(package)
    format_inventory = inspect_format_features(package)
    role_candidates = _role_candidates(styles)
    unsupported = [*style_diagnostics, *token_diagnostics]
    if format_inventory["overflows"]:
        unsupported.append(
            {
                "code": "DS_DOCX_TEMPLATE_FORMAT_INVENTORY_OVERFLOW",
                "severity": "enhancement_required",
                "details": {"overflows": format_inventory["overflows"]},
            }
        )
    if package.unknown_parts:
        unsupported.append(
            {
                "code": "DS_DOCX_TEMPLATE_UNKNOWN_SAFE_PARTS",
                "severity": "warning",
                "details": {"parts": list(package.unknown_parts[:64])},
            }
        )
    document_spec_supported = bool(styles) and not any(
        item["code"] in {
            "DS_DOCX_TEMPLATE_NUMBERING_BOUND_STYLE",
            "DS_DOCX_TEMPLATE_RELATIONSHIP_BOUND_STYLE",
            "DS_DOCX_TEMPLATE_STYLE_DEPENDENCY_MISSING",
        }
        for item in unsupported
    )
    template_supported = not any(
        item["code"] == "DS_DOCX_TEMPLATE_TOKEN_SYNTAX"
        for item in unsupported
    )
    compatibility = mode_compatibility(
        format_inventory,
        template_syntax_supported=template_supported,
        document_spec_styles_supported=document_spec_supported,
    )
    assert_source_preserved(source.path, source.sha256)
    return {
        "source": {
            "filename": path.name,
            "extension": path.suffix.casefold(),
            "sha256": source.sha256,
            "bytes": source.bytes,
        },
        "package_safety": {
            "status": "pass",
            "active_content": False,
            "part_count": len(package.parts),
            "relationship_count": len(package.relationships),
            "security": package.security,
        },
        "styles": styles,
        "variables": variables,
        "regions": regions,
        "role_candidates": role_candidates,
        "format_inventory": format_inventory,
        "mode_compatibility": compatibility,
        "supported_modes": [
            mode for mode, evidence in compatibility.items()
            if evidence["status"] != "incompatible"
        ],
        "unsupported_features": unsupported,
        "diagnostics": [
            {
                "code": "DS_DOCX_TEMPLATE_MAPPING_ADVISORY",
                "severity": "information",
                "message": "Semantic role candidates are advisory and require explicit import approval.",
            }
        ],
    }


def create_import_operation(
    request: ParsedDocxRequest,
    *,
    schemas: SchemaCatalog,
) -> dict[str, Any]:
    assert request.input_path is not None
    assert request.output_path is not None
    source = file_record(request.input_path, "input")
    expected = request.arguments["expected_source_sha256"]
    if source.sha256 != expected:
        raise DocumentSkillsError(
            ErrorCode.STALE_PRECONDITION,
            "Reference source digest does not match expected_source_sha256.",
            status="invalid_request",
            details={"diagnostic": "DS_DOCX_TEMPLATE_SOURCE_IDENTITY"},
        )
    try:
        inspection = inspect_reference(request.input_path, expected)
        metadata = request.arguments["manifest"]
        declared_compatibility = _validate_import_declarations(
            request.input_path,
            expected,
            inspection,
            metadata,
        )
        provenance = _provenance_record(request, source)
        with OperationTempRoot() as private_root:
            candidate = private_root / "candidate-pack"
            evidence_root = candidate / "evidence"
            evidence_root.mkdir(parents=True)
            payload_relative = f"template{request.input_path.suffix.casefold()}"
            payload_path = candidate / payload_relative
            shutil.copyfile(request.input_path, payload_path)
            if sha256(payload_path.read_bytes()).hexdigest() != expected:
                raise DocumentSkillsError(
                    ErrorCode.STALE_PRECONDITION,
                    "Reference source changed while the immutable payload was copied.",
                    details={"diagnostic": "DS_DOCX_TEMPLATE_SOURCE_IDENTITY"},
                )
            evidence_relative = "evidence/inspection.json"
            evidence_path = candidate / Path(*evidence_relative.split("/"))
            evidence_path.write_bytes(canonical_json_bytes(inspection))
            payload = member_record(
                payload_path,
                payload_relative,
                (
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.template"
                    if request.input_path.suffix.casefold() == ".dotx"
                    else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                "payload",
            )
            evidence = member_record(
                evidence_path,
                evidence_relative,
                "application/json",
                "evidence",
            )
            manifest = _build_manifest(
                metadata,
                provenance,
                payload.as_dict(),
                [payload.as_dict(), evidence.as_dict()],
                declared_compatibility,
            )
            schemas.validate("docx-template-pack", manifest)
            manifest_bytes = canonical_json_bytes(manifest)
            manifest_path = candidate / "manifest.json"
            manifest_path.write_bytes(manifest_bytes)
            manifest_digest = sha256(manifest_bytes).hexdigest()
            resolved = resolve_pack_directory(
                candidate,
                schemas,
                expected_manifest_sha256=manifest_digest,
            )
            assert_source_preserved(source.path, source.sha256)
            published = atomic_publish_directory(
                candidate,
                request.output_path,
                expected_manifest_sha256=manifest_digest,
            )
        source_error = None
        try:
            assert_source_preserved(source.path, source.sha256)
        except DocumentSkillsError as error:
            source_error = error
        warnings = []
        if source_error is not None:
            warnings.append(
                {
                    "code": "DS_SOURCE_CHANGED_AFTER_COMMIT",
                    "message": "The pack committed, but the reference source changed concurrently afterward.",
                    "details": source_error.details,
                }
            )
        return success_result(
            request,
            artifacts=[
                source.as_dict(),
                {
                    "role": "output",
                    "path": published.path,
                    "sha256": published.sha256,
                    "bytes": published.bytes,
                },
            ],
            operation_result={
                "pack": public_pack_manifest(resolved),
                "source_sha256": source.sha256,
                "manifest_sha256": manifest_digest,
                "members": [member.as_dict() for member in resolved.members],
                "provenance": provenance,
                "diagnostics": inspection["diagnostics"],
                "promotion": published.promotion_details(),
            },
            warnings=warnings,
            validation=_pack_validation(
                "docx.template-pack-import",
                evidence={"manifest_sha256": manifest_digest, "source_preserved_before_commit": True},
            ),
        )
    except Exception as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise


def _style_inventory(package: OpcPackage) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = package.xml("word/styles.xml")
    styles = []
    diagnostics = []
    available = {
        node.attrib.get(qn("w", "styleId"))
        for node in root.findall(qn("w", "style"))
        if node.attrib.get(qn("w", "styleId"))
    }
    relationship_prefix = f"{{{NS['r']}}}"
    if any(name.startswith(relationship_prefix) for node in root.iter() for name in node.attrib):
        diagnostics.append(
            {
                "code": "DS_DOCX_TEMPLATE_RELATIONSHIP_BOUND_STYLE",
                "severity": "enhancement_required",
                "details": {},
            }
        )
    if next(root.iter(qn("w", "numId")), None) is not None:
        diagnostics.append(
            {
                "code": "DS_DOCX_TEMPLATE_NUMBERING_BOUND_STYLE",
                "severity": "enhancement_required",
                "details": {},
            }
        )
    for node in root.findall(qn("w", "style")):
        style_id = node.attrib.get(qn("w", "styleId"))
        style_type = node.attrib.get(qn("w", "type"))
        if not style_id or style_type not in {"paragraph", "table", "character", "numbering"}:
            continue
        name_node = node.find(qn("w", "name"))
        dependencies = {
            relationship: dependency.attrib.get(qn("w", "val"))
            for relationship in ("basedOn", "link", "next")
            if (dependency := node.find(qn("w", relationship))) is not None
            and dependency.attrib.get(qn("w", "val"))
        }
        missing = sorted(set(dependencies.values()) - available)
        if missing:
            diagnostics.append(
                {
                    "code": "DS_DOCX_TEMPLATE_STYLE_DEPENDENCY_MISSING",
                    "severity": "enhancement_required",
                    "details": {"style_id": style_id, "dependencies": missing},
                }
            )
        styles.append(
            {
                "style_id": style_id,
                "name": name_node.attrib.get(qn("w", "val"), "") if name_node is not None else "",
                "type": style_type,
                "dependencies": dict(sorted(dependencies.items())),
                "authoring_format": _style_authoring_format(node),
            }
        )
    styles.sort(key=lambda item: (item["type"], item["style_id"].casefold(), item["style_id"]))
    return styles, diagnostics


def _style_authoring_format(style: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    run = style.find(qn("w", "rPr"))
    if run is not None:
        fonts = run.find(qn("w", "rFonts"))
        if fonts is not None:
            latin = {
                fonts.attrib.get(qn("w", name))
                for name in ("ascii", "hAnsi", "cs")
                if fonts.attrib.get(qn("w", name))
            }
            if len(latin) == 1:
                result["latin_font"] = next(iter(latin))
            east_asia = fonts.attrib.get(qn("w", "eastAsia"))
            if east_asia:
                result["east_asia_font"] = east_asia
        sizes = {
            node.attrib.get(qn("w", "val"))
            for name in ("sz", "szCs")
            if (node := run.find(qn("w", name))) is not None
            if node.attrib.get(qn("w", "val"))
        }
        if len(sizes) == 1:
            try:
                result["size_half_points"] = int(next(iter(sizes)))
            except ValueError:
                pass
        if run.find(qn("w", "b")) is not None:
            result["bold"] = True
    paragraph = style.find(qn("w", "pPr"))
    if paragraph is not None:
        alignment = paragraph.find(qn("w", "jc"))
        if alignment is not None and (value := alignment.attrib.get(qn("w", "val"))):
            result["alignment"] = value
        indentation = paragraph.find(qn("w", "ind"))
        if indentation is not None:
            for source, target in (
                ("firstLineChars", "first_line_chars"),
                ("hanging", "hanging_twips"),
                ("left", "left_twips"),
            ):
                if (value := indentation.attrib.get(qn("w", source))) is not None:
                    try:
                        result[target] = int(value)
                    except ValueError:
                        pass
        spacing = paragraph.find(qn("w", "spacing"))
        if spacing is not None:
            for source, target in (
                ("before", "space_before_twips"),
                ("after", "space_after_twips"),
                ("line", "line_twips"),
            ):
                if (value := spacing.attrib.get(qn("w", source))) is not None:
                    try:
                        result[target] = int(value)
                    except ValueError:
                        pass
    return result


def _template_inventory(package: OpcPackage) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    names: set[str] = set()
    diagnostics = []
    body_regions = []
    stories = document_stories(package)
    for story in stories:
        for paragraph_index, paragraph in enumerate(iter_paragraphs(story.root)):
            mapped = map_paragraph(paragraph)
            paragraph_names = {
                match.group(1)
                for group in mapped.groups
                for match in TOKEN_PATTERN.finditer(group.text)
            }
            names.update(paragraph_names)
            raw_text = "".join(group.text for group in mapped.groups)
            scrubbed = TOKEN_PATTERN.sub("", raw_text)
            if "{" in scrubbed or "}" in scrubbed:
                diagnostics.append(
                    {
                        "code": "DS_DOCX_TEMPLATE_TOKEN_SYNTAX",
                        "severity": "enhancement_required",
                        "details": {"story": story.kind, "paragraph_index": paragraph_index},
                    }
                )
    document = package.xml(WORD_MAIN)
    for paragraph_index, paragraph in executable_body_paragraphs(document):
        mapped = map_paragraph(paragraph)
        if not any(TOKEN_PATTERN.search(group.text) for group in mapped.groups):
            continue
        body_regions.extend(
            [
                {
                    "id": f"paragraph-{paragraph_index}-{kind}",
                    "type": kind,
                    "paragraph_index": paragraph_index,
                    "expected_text": mapped.full_text,
                }
                for kind in ("paragraph_condition", "paragraph_repeat")
            ]
        )
    return (
        [{"name": name, "required": True} for name in sorted(names)],
        sorted(body_regions, key=lambda item: item["id"]),
        diagnostics,
    )


def _role_candidates(styles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for style in styles:
        if style["type"] not in {"paragraph", "table"}:
            continue
        combined = f"{style['style_id']} {style['name']}".casefold()
        roles: list[tuple[str, str, str]] = []
        if style["type"] == "table":
            roles.append(("table", "high", "The source declares a table style."))
        else:
            if "title" in combined:
                roles.append(("title", "high", "Style id/name contains title."))
            if "subtitle" in combined:
                roles.append(("subtitle", "high", "Style id/name contains subtitle."))
            if "abstract" in combined:
                roles.append(("abstract", "high", "Style id/name contains abstract."))
            if "caption" in combined:
                roles.append(("caption", "high", "Style id/name contains caption."))
            for level in range(1, 7):
                if f"heading{level}" in combined.replace(" ", ""):
                    roles.append((f"heading.{level}", "high", f"Style id/name identifies heading level {level}."))
            if not roles and style["style_id"] in {"Normal", "BodyText", "ElftiaBody"}:
                roles.append(("paragraph", "medium", "Style resembles the normal body paragraph style."))
        for role, confidence, reason in roles:
            candidates.append(
                {
                    "role": role,
                    "style_id": style["style_id"],
                    "style_type": style["type"],
                    "confidence": confidence,
                    "reason": reason,
                    "approved": False,
                }
            )
    return sorted(candidates, key=lambda item: (item["role"], item["style_id"]))


def _validate_import_declarations(
    source: Path,
    expected: str,
    inspection: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    overflow_reasons = sorted(
        {
            item["reason"]
            for item in inspection["format_inventory"].get("overflows", [])
        }
    )
    if overflow_reasons and "document-spec" in metadata["modes"]:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Document-spec import cannot confirm a truncated formatting inventory.",
            status="enhancement_required",
            details={
                "diagnostic": "DS_DOCX_TEMPLATE_FORMAT_INVENTORY_OVERFLOW",
                "reasons": overflow_reasons,
                "overflows": inspection["format_inventory"]["overflows"],
            },
        )
    unsupported_modes = sorted(set(metadata["modes"]) - set(inspection["supported_modes"]))
    if unsupported_modes:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Reference cannot honor one or more declared template-pack modes.",
            status="enhancement_required",
            details={"diagnostic": "DS_DOCX_TEMPLATE_MODE_UNSUPPORTED", "modes": unsupported_modes},
        )
    declared_variables = {item["name"] for item in metadata["variables"]}
    inspected_variables = {item["name"] for item in inspection["variables"]}
    if "template" in metadata["modes"] and declared_variables != inspected_variables:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Declared template variables must exactly match the inspected payload.",
            details={
                "diagnostic": "DS_DOCX_TEMPLATE_CONTROL_MISMATCH",
                "missing": sorted(inspected_variables - declared_variables),
                "undeclared": sorted(declared_variables - inspected_variables),
            },
        )
    inspected_regions = {
        (item["type"], item["paragraph_index"], item["expected_text"])
        for item in inspection["regions"]
    }
    invalid_regions = [
        item["id"]
        for item in metadata["regions"]
        if (item["type"], item["paragraph_index"], item["expected_text"])
        not in inspected_regions
    ]
    if invalid_regions:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Declared template regions were not found in the inspected payload.",
            details={"diagnostic": "DS_DOCX_TEMPLATE_CONTROL_MISMATCH", "regions": invalid_regions},
        )
    if "document-spec" in metadata["modes"]:
        render_style_profile(
            {
                "id": "template-mapped",
                "version": "1.0",
                "source": source,
                "expected_source_sha256": expected,
                "role_styles": metadata["role_styles"],
            }
        )
        compatibility = inspection["mode_compatibility"]["document-spec"]
        authoring_format = metadata["authoring_format"]
        material_reasons = [
            reason
            for reason in compatibility["reasons"]
            if reason.endswith("requires-explicit-authoring-map")
        ]
        if material_reasons and authoring_format is None:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Document-spec import requires an explicit authoring-format mapping.",
                status="enhancement_required",
                details={
                    "diagnostic": "DS_DOCX_TEMPLATE_AUTHORING_FORMAT_REQUIRED",
                    "reasons": material_reasons,
                },
            )
        if authoring_format is not None:
            _validate_authoring_format_mapping(
                inspection,
                metadata["role_styles"],
                authoring_format,
            )
    declared = {
        mode: {
            **inspection["mode_compatibility"][mode],
            "reasons": list(inspection["mode_compatibility"][mode]["reasons"]),
        }
        for mode in metadata["modes"]
    }
    if "document-spec" in declared and metadata["authoring_format"] is not None:
        declared["document-spec"] = {
            **declared["document-spec"],
            "status": "compatible",
            "reasons": [],
            "unsupported_fields": [],
            "mapped_by": "explicit-authoring-format/v1",
        }
    return declared


def _validate_authoring_format_mapping(
    inspection: dict[str, Any],
    role_styles: dict[str, str],
    authoring_format: dict[str, Any],
) -> None:
    styles = {item["style_id"]: item for item in inspection["styles"]}
    inventory = inspection["format_inventory"]
    if overflows := inventory.get("overflows", []):
        _authoring_loss(
            overflows[0]["reason"],
            overflows=overflows,
        )
    direct_by_style = _direct_role_formats(inventory)
    formatted_styles = {
        style_id
        for style_id, evidence in direct_by_style.items()
        if evidence
    }
    mapped_styles = set(role_styles.values())
    if missing := sorted(formatted_styles - mapped_styles):
        _authoring_loss("direct-format-style-is-not-mapped", style_ids=missing)
    profile_roles_by_style: dict[str, list[str]] = {}
    for role, role_format in authoring_format["role_formats"].items():
        style_id = role_styles[role]
        profile_roles_by_style.setdefault(style_id, []).append(role)
        style = styles.get(style_id)
        if style is None:
            _authoring_loss("mapped-style-is-missing", role=role, style_id=style_id)
        effective = {
            **style["authoring_format"],
            **direct_by_style.get(style_id, {}),
        }
        if effective != role_format:
            _authoring_loss(
                "role-format-does-not-match-source",
                role=role,
                style_id=style_id,
                expected=effective,
                declared=role_format,
            )
    if unconsumed := sorted(formatted_styles - set(profile_roles_by_style)):
        _authoring_loss("direct-format-is-not-consumed", style_ids=unconsumed)
    _validate_table_authoring_format(inventory["tables"], authoring_format["table"])
    _validate_footer_authoring_format(
        inventory["stories"],
        authoring_format["default_footer"],
    )


def _direct_role_formats(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for category, converter in (
        ("direct_run_formats", _direct_run_role_format),
        ("direct_paragraph_formats", _direct_paragraph_role_format),
    ):
        for item in inventory[category]:
            raw = item["format"]
            location = raw.get("location")
            if location == "table":
                material = {
                    key: value
                    for key, value in raw.items()
                    if key not in {"bold", "location", "paragraph_style"}
                }
                if material:
                    _authoring_loss(
                        "table-cell-direct-format-is-not-representable",
                        format=material,
                    )
                continue
            if location in {"header", "footer"}:
                material = {
                    key: value
                    for key, value in raw.items()
                    if key not in {"alignment", "location", "paragraph_style"}
                }
                if material:
                    _authoring_loss(
                        "story-direct-format-is-not-representable",
                        story=location,
                        format=material,
                    )
                continue
            if location != "body":
                _authoring_loss("direct-format-location-is-not-representable", location=location)
            style_id = raw.get("paragraph_style") or ""
            converted = converter(raw)
            if converted:
                grouped.setdefault(style_id, {}).setdefault(category, []).append(converted)
    result: dict[str, dict[str, Any]] = {}
    for style_id, categories in grouped.items():
        merged: dict[str, Any] = {}
        for category, candidates in categories.items():
            unique = {tuple(sorted(candidate.items())) for candidate in candidates}
            if len(unique) != 1:
                _authoring_loss(
                    "direct-format-is-not-uniform",
                    style_id=style_id,
                    category=category,
                )
            candidate = dict(next(iter(unique)))
            conflicts = {
                key: (merged[key], value)
                for key, value in candidate.items()
                if key in merged and merged[key] != value
            }
            if conflicts:
                _authoring_loss(
                    "direct-format-values-conflict",
                    style_id=style_id,
                    conflicts=conflicts,
                )
            merged.update(candidate)
        result[style_id] = merged
    return result


def _direct_run_role_format(raw: dict[str, Any]) -> dict[str, Any]:
    supported = {
        "font_ascii", "font_hAnsi", "font_eastAsia", "font_cs",
        "sz", "szCs", "bold", "location", "paragraph_style",
    }
    if unsupported := sorted(set(raw) - supported):
        _authoring_loss("direct-run-format-is-not-representable", fields=unsupported)
    result: dict[str, Any] = {}
    latin = {
        raw[key]
        for key in ("font_ascii", "font_hAnsi", "font_cs")
        if key in raw
    }
    if len(latin) > 1:
        _authoring_loss("direct-run-latin-fonts-conflict", values=sorted(latin))
    if latin:
        result["latin_font"] = next(iter(latin))
    if "font_eastAsia" in raw:
        result["east_asia_font"] = raw["font_eastAsia"]
    sizes = {raw[key] for key in ("sz", "szCs") if key in raw}
    if len(sizes) > 1:
        _authoring_loss("direct-run-sizes-conflict", values=sorted(sizes))
    if sizes:
        try:
            result["size_half_points"] = int(next(iter(sizes)))
        except ValueError:
            _authoring_loss("direct-run-size-is-invalid", values=sorted(sizes))
    if raw.get("bold") is True:
        result["bold"] = True
    return result


def _direct_paragraph_role_format(raw: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "alignment": "alignment",
        "indent_firstLineChars": "first_line_chars",
        "indent_hanging": "hanging_twips",
        "indent_left": "left_twips",
        "spacing_before": "space_before_twips",
        "spacing_after": "space_after_twips",
        "spacing_line": "line_twips",
    }
    supported = {*mapping, "spacing_lineRule", "location", "paragraph_style"}
    if unsupported := sorted(set(raw) - supported):
        _authoring_loss("direct-paragraph-format-is-not-representable", fields=unsupported)
    if raw.get("spacing_lineRule") not in {None, "auto"}:
        _authoring_loss(
            "direct-paragraph-line-rule-is-not-representable",
            line_rule=raw["spacing_lineRule"],
        )
    result: dict[str, Any] = {}
    for source, target in mapping.items():
        if source not in raw:
            continue
        value: Any = raw[source]
        if source != "alignment":
            try:
                value = int(value)
            except ValueError:
                _authoring_loss("direct-paragraph-number-is-invalid", field=source)
        result[target] = value
    return result


def _validate_table_authoring_format(
    tables: list[dict[str, Any]],
    declared: dict[str, Any],
) -> None:
    if not tables:
        _authoring_loss("authoring-table-is-not-present-in-source")
    for table in tables:
        columns = table["columns"]
        width = table["table_width_twips"]
        grid = table["grid_widths_twips"]
        expected_grid = _distributed_widths(width, columns) if columns else []
        cell_widths = table["cell_widths_twips"]
        valid_cells = all(
            cell_widths[index:index + columns] == grid
            for index in range(0, len(cell_widths), columns or 1)
        )
        if (
            not table["grid_positive"]
            or not table["cell_widths_complete"]
            or table["layout"] != "fixed"
            or width != declared["width_twips"]
            or grid != expected_grid
            or not valid_cells
        ):
            _authoring_loss(
                "table-geometry-is-not-representable",
                table_index=table["index"],
            )
        actual_borders = _inventory_borders(table["borders"])
        if actual_borders != declared["borders"]:
            _authoring_loss(
                "table-borders-do-not-match-source",
                table_index=table["index"],
                expected=actual_borders,
                declared=declared["borders"],
            )


def _inventory_borders(value: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
    mapping = {"insideH": "inside_h", "insideV": "inside_v"}
    result = {}
    for source, border in value.items():
        if border.get("val") in {"", "nil", "none"}:
            continue
        if border.get("space") not in {"", "0"}:
            _authoring_loss("table-border-space-is-not-representable", border=source)
        style = border.get("val")
        if style not in {"single", "double"}:
            _authoring_loss("table-border-style-is-not-representable", border=source)
        try:
            size = int(border.get("sz", ""))
        except ValueError:
            _authoring_loss("table-border-size-is-invalid", border=source)
        color = border.get("color", "").upper()
        result[mapping.get(source, source)] = {
            "style": style,
            "size_eighth_points": size,
            "color": color,
        }
    return result


def _validate_footer_authoring_format(
    stories: list[dict[str, Any]],
    declared: dict[str, Any],
) -> None:
    if any(
        story["kind"] == "header"
        and any(paragraph["runs"] for paragraph in story["paragraphs"])
        for story in stories
    ):
        _authoring_loss("source-header-is-not-representable")
    footers = [story for story in stories if story["kind"] == "footer"]
    if not footers:
        _authoring_loss("authoring-footer-is-not-present-in-source")
    expected = _story_signature(declared)
    for footer in footers:
        if footer["paragraphs"] != expected:
            _authoring_loss(
                "authoring-footer-does-not-match-source",
                part=footer["part"],
            )


def _story_signature(story: dict[str, Any]) -> list[dict[str, Any]]:
    paragraphs = []
    for paragraph in story["paragraphs"]:
        runs = []
        for run in paragraph["runs"]:
            if "field" in run:
                runs.append({"field": run["field"]})
            else:
                encoded = run["text"].encode("utf-8", errors="strict")
                runs.append(
                    {
                        "text_sha256": sha256(encoded).hexdigest(),
                        "text_bytes": len(encoded),
                    }
                )
        paragraphs.append({"alignment": paragraph["alignment"], "runs": runs})
    return paragraphs


def _distributed_widths(total: int, count: int) -> list[int]:
    quotient, remainder = divmod(total, count)
    return [quotient + (1 if index < remainder else 0) for index in range(count)]


def _authoring_loss(reason: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        "The explicit authoring-format mapping would discard or invent source formatting.",
        status="enhancement_required",
        details={
            "diagnostic": "DS_DOCX_TEMPLATE_AUTHORING_FORMAT_LOSSY",
            "reason": reason,
            **details,
        },
    )


def _provenance_record(request: ParsedDocxRequest, source: Any) -> dict[str, Any]:
    provenance = request.arguments["provenance"]
    network = provenance.get("network")
    if network is not None and network["downloaded_sha256"] != source.sha256:
        raise DocumentSkillsError(
            ErrorCode.STALE_PRECONDITION,
            "Network downloaded digest does not match the imported local source.",
            status="invalid_request",
            details={"diagnostic": "DS_DOCX_TEMPLATE_NETWORK_DIGEST_MISMATCH"},
        )
    return {
        "source_kind": provenance["source_kind"],
        "original_filename": request.input_path.name,
        "source_sha256": source.sha256,
        "importer": {"id": "elftia-document-skills", "version": __version__},
        "imported_at": provenance["imported_at"],
        "license": provenance["license"],
        "redistributable": provenance["redistributable"],
        **({"network": network} if network is not None else {}),
    }


def _build_manifest(
    metadata: dict[str, Any],
    provenance: dict[str, Any],
    payload: dict[str, Any],
    members: list[dict[str, Any]],
    compatibility: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "docx-template-pack/v1",
        "id": metadata["id"],
        "version": metadata["version"],
        "display_name": metadata["display_name"],
        "description": metadata["description"],
        "payload": payload,
        "members": sorted(members, key=lambda item: item["path"]),
        "capabilities": {
            "modes": metadata["modes"],
            "variables": metadata["variables"],
            "regions": metadata["regions"],
            "role_styles": metadata["role_styles"],
            **(
                {"authoring_format": metadata["authoring_format"]}
                if metadata["authoring_format"] is not None
                else {}
            ),
            "mode_compatibility": {
                mode: compatibility[mode]
                for mode in metadata["modes"]
            },
        },
        "compatibility": metadata["compatibility"],
        "language_policy": metadata["language_policy"],
        "provenance": provenance,
        "evidence": [
            {
                "kind": "inspection",
                "path": "evidence/inspection.json",
                "status": "pass",
                "provider_context": {"provider": "document-skills-core", "version": __version__},
            }
        ],
    }


def _assert_plain_source(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise DocumentSkillsError(ErrorCode.INPUT_NOT_FOUND, "Reference source does not exist.") from error
    redirected = bool(os.name == "nt" and metadata.st_file_attributes & _REPARSE_POINT)
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink() or redirected:
        raise DocumentSkillsError(
            ErrorCode.PATH_UNSAFE,
            "Reference source must be a plain local file, not a redirected path.",
        )


def _pack_validation(gate_id: str, *, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "pass",
        "gates": [
            gate_record("docx.package-security", "pass", evidence={"policy": "reject"}),
            gate_record(gate_id, "pass", evidence=evidence),
            gate_record(
                "visual.render",
                "unavailable",
                required=False,
                evidence={"reason": "Enhanced rendered evidence was not requested or is unavailable."},
                warnings=["No successful visual comparison is claimed."],
            ),
        ],
    }


__all__ = [
    "create_import_operation",
    "inspect_reference",
    "inspect_reference_operation",
]
