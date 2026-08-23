"""Inert structural inspection of PDF objects, xref, streams, and features.

Inventories objects, xref, streams, content streams, fonts, images, forms,
annotations, embedded files, JavaScript actions, external links, and unknown
objects WITHOUT executing, dereferencing, following, enabling, rewriting, or
sanitizing any action or embedded content.

Module provenance: original Elftia-authored clean-room implementation.
"""

from typing import Any

from .actions import ActionClassification, classify_actions
from .byte_preflight import PdfByteLimits, preflight_pdf
from .mapping import map_acroform_fields, map_annotations, map_embedded_files, map_outlines
from .object_model import parse_pdf
from .page_labels import project_page_labels
from .page_tree import walk_pages
from .projection import project_object_inventory
from .resources import inventory_fonts, inventory_images


def inspect_pdf(path, arguments: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Inspect a PDF structure inertly.

    Returns (operation_result, warnings).
    Uses preserve-disabled (inert inventory) policy — does not reject active content.
    """
    limits = PdfByteLimits()
    preflight = preflight_pdf(path, limits)
    model = parse_pdf(path, limits)

    warnings: list[dict[str, Any]] = []
    if preflight.encrypted:
        warnings.append({
            "code": "encrypted",
            "message": "PDF is encrypted; inventory is byte-level only.",
        })

    # Object inventory
    object_inventory = project_object_inventory(model)
    max_objects = arguments.get("max_objects", 50_000)
    include_hashes = arguments.get("include_hashes", True)
    if len(object_inventory) > max_objects:
        warnings.append({
            "code": "truncation",
            "message": "Object count exceeded the caller-selected limit.",
            "affected": "objects",
        })
        object_inventory = object_inventory[:max_objects]

    if not include_hashes:
        for obj in object_inventory:
            obj.pop("sha256", None)

    # Xref inventory
    xref_entries = [
        {
            "obj_num": e.obj_num,
            "offset": e.offset,
            "gen_num": e.gen_num,
            "in_use": e.in_use,
            "is_stream_entry": e.is_stream,
        }
        for e in sorted(model.xref_entries.values(), key=lambda x: x.obj_num)
    ]

    # Stream inventory
    streams = [
        {"obj_num": num, "sha256": obj.sha256}
        for num, obj in sorted(model.objects.items())
        if obj.is_stream
    ]
    max_streams = arguments.get("max_streams", 10_000)
    if len(streams) > max_streams:
        streams = streams[:max_streams]
        warnings.append({
            "code": "truncation",
            "message": "Stream count exceeded the caller-selected limit.",
            "affected": "streams",
        })

    # Content streams, fonts, images
    pages = walk_pages(model)
    content_streams = []
    for page in pages:
        content_streams.append({
            "page": page.page_number,
            "obj_num": page.obj_num,
            "content_refs": [r.obj_num for r in page.contents],
        })

    all_fonts: list[dict[str, Any]] = []
    all_images: list[dict[str, Any]] = []
    for page in pages:
        fonts = inventory_fonts(model, page.resources)
        for f in fonts:
            entry = {
                "page": page.page_number,
                "name": f.name,
                "type": f.type,
                "embedded": f.embedded,
                "subset": f.subset,
            }
            all_fonts.append(entry)
        images = inventory_images(model, page.resources)
        for img in images:
            entry = {
                "page": page.page_number,
                "name": img.name,
                "width": img.width,
                "height": img.height,
                "color_space": img.color_space,
            }
            all_images.append(entry)

    # AcroForm inventory
    fields = map_acroform_fields(model)
    field_inventory = [
        {
            "qualified_name": f.qualified_name,
            "field_type": f.field_type,
            "flags": f.flags,
            "value": f.value,
            "default_value": f.default_value,
            "required": f.required,
            "readonly": f.readonly,
            "options": list(f.options),
            "page": f.page,
            "widget": f.widget,
            "has_appearance": f.has_appearance,
            "annotation_rect": list(f.annotation_rect) if f.annotation_rect else None,
        }
        for f in fields
    ]

    # Annotation inventory
    annotations = map_annotations(model, pages)
    annot_inventory = [
        {
            "page": a.page,
            "index": a.index,
            "subtype": a.subtype,
            "rectangle": list(a.rectangle) if a.rectangle else None,
            "contents": a.contents,
            "title": a.title,
            "color": list(a.color) if a.color else None,
            "action_kind": a.action_kind,
        }
        for a in annotations
    ]

    # Action inventory (inert)
    actions = classify_actions(model)
    action_inventory = [
        {
            "kind": a.kind,
            "source_obj": a.source_obj,
            "is_external": a.is_external,
            "is_executable": a.is_executable,
            "description": a.description,
            "mutation_authorized": False,
        }
        for a in actions
    ]

    # Embedded file inventory
    embedded_files = map_embedded_files(model)
    ef_inventory = [
        {
            "relationship": e.relationship,
            "filename": e.filename,
            "mime_type": e.mime_type,
            "size": e.size,
        }
        for e in embedded_files
    ]

    # Outline inventory
    outlines = map_outlines(model)
    outline_inventory = [{"title": o.title} for o in outlines]

    operation_result: dict[str, Any] = {
        "version": f"PDF-{model.version_major}.{model.version_minor}",
        "encrypted": preflight.encrypted,
        "total_bytes": preflight.total_bytes,
        "sha256": model.sha256,
        "object_count": len(model.objects),
        "objects": object_inventory,
        "xref": xref_entries,
        "streams": streams,
        "content_streams": content_streams,
        "page_count": len(pages),
        "fonts": all_fonts,
        "images": all_images,
        "acroform_fields": field_inventory,
        "annotations": annot_inventory,
        "actions": action_inventory,
        "embedded_files": ef_inventory,
        "outlines": outline_inventory,
        "page_labels": project_page_labels(model, len(pages)),
        "dangerous_content_present": any(a.is_external or a.is_executable for a in actions),
        "security_summary": _project_security_summary(actions, ef_inventory, preflight.encrypted),
    }
    return operation_result, warnings


def _project_security_summary(
    actions: list[ActionClassification],
    embedded_files: list[dict[str, Any]],
    encrypted: bool,
) -> dict[str, Any]:
    """Project the uniform security_summary from PDF action + embedded inventory."""
    categories: dict[str, int] = {}
    for action in actions:
        kind = action.kind.lower()
        categories[kind] = categories.get(kind, 0) + 1
    executable_embedded = sum(
        1
        for entry in embedded_files
        if isinstance(entry.get("mime_type"), str)
        and "dosexec" in entry["mime_type"].lower()
    )
    if executable_embedded:
        categories["embedded_executable"] = executable_embedded
    if encrypted:
        categories["encrypted"] = 1
    return {
        "dangerous": bool(categories),
        "categories": categories,
        "mutation_authorized": False,
    }
