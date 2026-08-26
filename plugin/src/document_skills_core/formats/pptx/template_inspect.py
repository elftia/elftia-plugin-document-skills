"""Structural and A-Contract semantic inspection of inert PPTX templates."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .contact_sheet import MAX_CONTACT_SHEET_SLIDES, compose_contact_sheet
from .constants import NS, local_name
from .mapping import map_slides
from .object_xml import (
    drawable_elements,
    non_visual_properties,
    object_hash,
    object_type,
    slide_shape_tree,
)
from .package import OpcPackage
from .slide_render import write_single_slide_candidate
from .template_descriptor import (
    TemplateDescriptor,
    load_template_descriptor,
    validate_catalog_binding,
)

_A = NS["a"]
_P = NS["p"]
_STABLE_SLIDE = re.compile(r"^slide_[0-9a-f]{32}$")
_STABLE_OBJECT = re.compile(r"^object_[0-9a-f]{32}$")


def inspect_template(
    path: Path,
    arguments: dict[str, Any],
    *,
    provider: Any,
    private_root: Path,
    source_sha256: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], bytes | None]:
    input_sha256 = source_sha256
    expected = arguments["expected_input_sha256"]
    if expected is not None and expected != input_sha256:
        raise DocumentSkillsError(
            ErrorCode.STALE_PRECONDITION,
            "The template input hash no longer matches the inspect precondition.",
            status="invalid_request",
            details={"actual_sha256": input_sha256, "expected_sha256": expected},
        )
    package = OpcPackage.open(path, allow_dangerous_inventory=True)
    warnings: list[dict[str, Any]] = []
    descriptor = None
    semantic_diagnostics: list[dict[str, Any]] = []
    descriptor_ref = arguments["descriptor"]
    if descriptor_ref is not None:
        try:
            descriptor = load_template_descriptor(descriptor_ref)
        except DocumentSkillsError as error:
            if arguments["mode"] == "strict":
                raise
            semantic_diagnostics.append({
                "code": error.code.value,
                "message": str(error),
            })
            warnings.append({
                "code": "PPTX_TEMPLATE_DESCRIPTOR_TOLERATED",
                "message": "Semantic descriptor validation failed; no writable slots were projected.",
            })
    elif arguments["catalog_ref"] is not None:
        _invalid("catalog_ref requires a semantic descriptor.")

    pages = _project_pages(package)
    if descriptor is not None:
        semantic_diagnostics.extend(_apply_semantics(pages, descriptor))
        if semantic_diagnostics and arguments["mode"] == "strict":
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Template stable addresses do not match the semantic descriptor.",
                status="failed",
                details={"diagnostics": semantic_diagnostics[:64]},
            )
        if semantic_diagnostics:
            for page in pages:
                page["semantic_slots"] = []
    catalog = (
        {
            "catalog_ref": "not_provided",
            "hash_verification": "not_run",
            "license_status": "not_evaluated",
            "signature_verification": "not_provided",
        }
        if descriptor is None
        else validate_catalog_binding(
            descriptor,
            arguments["catalog_ref"],
            input_sha256=input_sha256,
        )
    )
    contact_bytes, visual = _contact_sheet(
        package,
        provider,
        private_root,
        requested=arguments["contact_sheet"],
    )
    security = package.security
    result = {
        "catalog": catalog,
        "contact_sheet": visual,
        "dangerous_content": {
            "categories": {
                key: len(value)
                for key, value in security.get("categories", {}).items()
                if value
            },
            "present": bool(security.get("dangerous")),
        },
        "descriptor": {
            "consumer": (
                {"status": "not_provided"}
                if descriptor is None
                else descriptor.contract_consumer
            ),
            "diagnostics": semantic_diagnostics,
            "mode": arguments["mode"],
            "status": (
                "not_provided"
                if descriptor_ref is None
                else "passed" if descriptor is not None and not semantic_diagnostics else "diagnostic_only"
            ),
        },
        "input_sha256": input_sha256,
        "mutation_authorized": False,
        "pages": pages,
        "slide_count": len(pages),
        "structural": {
            "charts": len(package.chart_parts()),
            "external_relationships": sum(
                item.target_mode == "External" for item in package.relationships
            ),
            "layouts": len(package.slide_layout_parts()),
            "masters": len(package.slide_master_parts()),
            "media": len(package.media_parts()),
            "notes": len(package.notes_slide_parts()),
            "parts": len(package.parts),
            "themes": len(package.theme_parts()),
        },
    }
    return result, warnings, contact_bytes


def _project_pages(package: OpcPackage) -> list[dict[str, Any]]:
    mapped = map_slides(package)
    presentation = package.xml("ppt/presentation.xml")
    slide_ids = presentation.find(f"{{{_P}}}sldIdLst")
    id_nodes = [] if slide_ids is None else list(slide_ids)
    pages: list[dict[str, Any]] = []
    for index, slide in enumerate(mapped):
        part = slide.get("part")
        if part is None:
            continue
        root = package.xml(part)
        common = root.find(f"{{{_P}}}cSld")
        source_slide_id = "" if common is None else common.attrib.get("name", "")
        if not _STABLE_SLIDE.fullmatch(source_slide_id):
            source_slide_id = None
        page = {
            "charts": [],
            "hidden": (
                index < len(id_nodes)
                and id_nodes[index].attrib.get("show", "1") == "0"
            ),
            "layout": slide.get("layout"),
            "master": slide.get("master"),
            "media": [],
            "notes": _notes_record(package, slide.get("notes")),
            "objects": [],
            "order": index + 1,
            "page_role": None,
            "part": part,
            "semantic_slots": [],
            "source_slide_id": source_slide_id,
            "theme": _theme_ref(package, slide.get("master")),
            "use_for": [],
        }
        for element in drawable_elements(slide_shape_tree(root)):
            record = _object_record(element, source_slide_id)
            page["objects"].append(record)
            if record["kind"] == "chart":
                page["charts"].append(record["stable_address"])
            if record["kind"] == "image":
                page["media"].append(record["stable_address"])
        pages.append(page)
    return pages


def _object_record(element: Any, slide_id: str | None) -> dict[str, Any]:
    properties = non_visual_properties(element)
    name = properties.attrib.get("name", "")
    stable_id = name if _STABLE_OBJECT.fullmatch(name) else None
    placeholder = next(
        (node for node in element.iter() if local_name(node.tag) == "ph"),
        None,
    )
    return {
        "expected_hash": object_hash(element),
        "hidden": properties.attrib.get("hidden", "0") == "1",
        "kind": object_type(element),
        "placeholder": (
            None
            if placeholder is None
            else {
                "idx": placeholder.attrib.get("idx", "0"),
                "type": placeholder.attrib.get("type", "body"),
            }
        ),
        "stable_address": (
            None
            if slide_id is None or stable_id is None
            else {"object_id": stable_id, "slide_id": slide_id}
        ),
        "type_scale": _type_scale(element),
    }


def _apply_semantics(
    pages: list[dict[str, Any]],
    descriptor: TemplateDescriptor,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    pages_by_id = {
        item["source_slide_id"]: item
        for item in pages
        if item["source_slide_id"] is not None
    }
    if len(pages_by_id) != len(pages):
        diagnostics.append({"code": "stable-slide-address-missing"})
    if set(pages_by_id) != set(descriptor.slides_by_id):
        diagnostics.append({
            "code": "stable-slide-address-drift",
            "descriptor": sorted(descriptor.slides_by_id),
            "physical": sorted(pages_by_id),
        })
    physical_objects: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    duplicate_object_ids: set[str] = set()
    for page in pages:
        for item in page["objects"]:
            address = item["stable_address"]
            if address is not None:
                object_id = address["object_id"]
                if object_id in physical_objects:
                    duplicate_object_ids.add(object_id)
                else:
                    physical_objects[object_id] = (page, item)
    if duplicate_object_ids:
        diagnostics.append({
            "code": "stable-object-address-duplicate",
            "object_ids": sorted(duplicate_object_ids),
        })
    for slot in descriptor.semantic_slots["slots"]:
        source_id = slot["sourceObjectId"]
        physical = physical_objects.get(source_id)
        deck_object = descriptor.objects_by_id.get(source_id)
        if physical is None or deck_object is None:
            diagnostics.append({
                "code": "semantic-slot-address-missing",
                "slot_id": slot["slotId"],
            })
            continue
        page, item = physical
        deck_slide, _ = deck_object
        if page["source_slide_id"] != deck_slide["slideId"]:
            diagnostics.append({
                "code": "semantic-slot-slide-drift",
                "slot_id": slot["slotId"],
            })
            continue
        cardinality = slot["cardinality"]
        page["semantic_slots"].append({
            "capacity": slot["capacity"],
            "expected_hash": item["expected_hash"],
            "kind": slot["dataType"],
            "repeatable": cardinality["kind"] == "repeated",
            "required": (
                cardinality["kind"] == "required"
                or cardinality["kind"] == "repeated" and cardinality["min"] > 0
            ),
            "slot_id": slot["slotId"],
            "stable_address": item["stable_address"],
            "type_scale": item["type_scale"],
        })
    for slide_id, deck_slide in descriptor.slides_by_id.items():
        page = pages_by_id.get(slide_id)
        if page is not None:
            page["page_role"] = deck_slide["role"]
            page["use_for"] = [deck_slide["role"]]
    return diagnostics


def _contact_sheet(
    package: OpcPackage,
    provider: Any,
    private_root: Path,
    *,
    requested: bool,
) -> tuple[bytes | None, dict[str, Any]]:
    if not requested:
        return None, {"provider": "libreoffice", "status": "not_run"}
    if package.security.get("dangerous"):
        return None, {
            "provider": "libreoffice",
            "reason": "dangerous-input-not-opened-by-visual-provider",
            "status": "unavailable",
        }
    evidence = _provider_evidence(provider)
    if evidence is None or evidence.available is not True:
        return None, {
            "provider": "libreoffice",
            "reason": "provider-unavailable",
            "status": "unavailable",
        }
    slide_count = len(map_slides(package))
    if slide_count > MAX_CONTACT_SHEET_SLIDES:
        return None, {
            "provider": "libreoffice",
            "reason": "contact-sheet-slide-limit",
            "status": "failed",
        }
    version = evidence.version if hasattr(evidence, "version") else None
    rendered: list[bytes] = []
    render_root = private_root / "contact-sheet"
    render_root.mkdir(parents=True, exist_ok=True)
    try:
        for number in range(1, slide_count + 1):
            candidate = write_single_slide_candidate(
                package,
                number,
                render_root / f"slide-{number}.pptx",
            )
            image = provider.try_render_to_image(candidate)
            if type(image) is not bytes or not image:
                raise ValueError("empty provider output")
            rendered.append(image)
        payload, mapping = compose_contact_sheet(rendered)
    except Exception as error:
        return None, {
            "provider": "libreoffice",
            "reason": "render-or-compose-failed",
            "reason_category": type(error).__name__,
            "status": "failed",
            "version": version,
        }
    return payload, {
        **mapping,
        "provider": "libreoffice",
        "status": "passed",
        "version": version,
    }


def _provider_evidence(provider: Any) -> Any:
    if provider is None or not hasattr(provider, "detect"):
        return None
    try:
        return provider.detect()
    except Exception:
        return None


def _notes_record(package: OpcPackage, notes: Any) -> dict[str, Any]:
    if not notes or not notes.get("part"):
        return {"present": False}
    part = notes["part"]
    payload = package.parts.get(part, b"")
    return {
        "bytes": len(payload),
        "part": part,
        "present": True,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _theme_ref(package: OpcPackage, master: Any) -> dict[str, Any] | None:
    if not master or not master.get("part"):
        return None
    for relationship in package.part_rels(master["part"]):
        if relationship.relationship_type.endswith("/theme"):
            return {"part": relationship.resolved_target}
    return None


def _type_scale(element: Any) -> dict[str, Any]:
    values = sorted({
        int(node.attrib["sz"]) / 100
        for node in element.iter()
        if local_name(node.tag) in {"defRPr", "endParaRPr", "rPr"}
        and node.attrib.get("sz", "").isdigit()
    })
    return {
        "maximum_pt": max(values) if values else None,
        "minimum_pt": min(values) if values else None,
        "values_pt": values,
    }


def _invalid(message: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
    )
