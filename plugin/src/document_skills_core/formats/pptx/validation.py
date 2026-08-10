"""PPTX reopen, semantic, structure-equality-on-reorder, and preservation gates."""

import hashlib
import math
from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.validation import validate_artifact

from .constants import NS
from .mapping import map_slides
from .package import OpcPackage, PreservationManifest
from .scene_emitter import EMU_PER_PIXEL, SLIDE_CX, SLIDE_CY
from .scene_normalizer import NormalizedScene
from .scene_opc_validation import generated_scene_opc_failures


def validate_created(
    path: Path,
    deck: dict[str, Any],
) -> dict[str, Any]:
    assertions = [
        ("consumer-package-conformance", _assert_consumer_package),
        ("create-semantics", lambda candidate: _assert_created(candidate, deck)),
    ]
    return _required_report(path, assertions=assertions)


def validate_scene_created(
    path: Path,
    scene: NormalizedScene,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    assertions = [
        ("consumer-package-conformance", _assert_consumer_package),
        (
            "scene-package-correspondence",
            lambda candidate: _assert_scene_created(candidate, scene, manifest),
        )
    ]
    return _required_report(path, assertions=assertions)


def validate_mutation(
    path: Path,
    *,
    source: Path,
    source_sha256: str,
    manifest: PreservationManifest,
    assertion: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] = [
        ("part-preservation", lambda _candidate: _assert_preservation(manifest))
    ]
    if assertion is not None:
        assertions.append(("mutation-semantics", assertion))
    return _required_report(
        path,
        source=source,
        source_sha256=source_sha256,
        assertions=assertions,
    )


def validate_reorder(
    path: Path,
    *,
    source: Path,
) -> dict[str, Any]:
    """Structure-equality-on-reorder gate.

    Reopens candidate and input, walks the slide list in the new
    presentation order, and asserts that for every slide the shape IDs,
    text-frame content, table content, chart references, image references,
    connectors, notes content, notes reference, slide-layout reference, and
    slide-master reference match the input modulo order.
    """
    input_pkg = OpcPackage.open(source)
    candidate_pkg = OpcPackage.open(path)
    input_slides = map_slides(input_pkg)
    candidate_slides = map_slides(candidate_pkg)

    if len(input_slides) != len(candidate_slides):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Reorder changed the slide count.",
            details={"input": len(input_slides), "output": len(candidate_slides)},
        )

    input_by_part = {s["part"]: s for s in input_slides if s.get("part")}
    failures: list[str] = []

    for candidate_slide in candidate_slides:
        part = candidate_slide.get("part")
        if part is None:
            failures.append(f"slide-{candidate_slide['number']}-missing-part")
            continue
        input_slide = input_by_part.get(part)
        if input_slide is None:
            failures.append(f"slide-{candidate_slide['number']}-unknown-part")
            continue

        input_shape_ids = {s.get("id") for s in input_slide.get("shapes", [])}
        candidate_shape_ids = {s.get("id") for s in candidate_slide.get("shapes", [])}
        if input_shape_ids != candidate_shape_ids:
            failures.append(f"slide-{candidate_slide['number']}-shape-ids")

        input_text = _extract_text(input_slide)
        candidate_text = _extract_text(candidate_slide)
        if input_text != candidate_text:
            failures.append(f"slide-{candidate_slide['number']}-text-content")

        if _extract_chart_refs(input_pkg, part) != _extract_chart_refs(candidate_pkg, part):
            failures.append(f"slide-{candidate_slide['number']}-chart-refs")
        if _extract_image_refs(input_pkg, part) != _extract_image_refs(candidate_pkg, part):
            failures.append(f"slide-{candidate_slide['number']}-image-refs")
        if _extract_connectors(input_slide) != _extract_connectors(candidate_slide):
            failures.append(f"slide-{candidate_slide['number']}-connector-geometry")

        if not _compare_nested(input_slide.get("layout"), candidate_slide.get("layout")):
            failures.append(f"slide-{candidate_slide['number']}-layout-ref")
        if not _compare_nested(input_slide.get("master"), candidate_slide.get("master")):
            failures.append(f"slide-{candidate_slide['number']}-master-ref")
        if not _compare_notes(input_slide.get("notes"), candidate_slide.get("notes")):
            failures.append(f"slide-{candidate_slide['number']}-notes")

    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Structure-equality-on-reorder gate failed: slide content differs beyond order.",
            details={"failures": failures},
        )
    return {"slides_checked": len(candidate_slides), "structure_equal": True}


def reopen_pptx(path: Path) -> dict[str, Any]:
    """Reopen a PPTX package and verify its required structures."""
    package = OpcPackage.open(path)
    slides = map_slides(package)
    return {
        "parts": len(package.parts),
        "relationships": len(package.relationships),
        "slides": len(slides),
    }


def _assert_created(path: Path, deck: dict[str, Any]) -> dict[str, Any]:
    package = OpcPackage.open(path)
    mapped = map_slides(package)
    failures: list[str] = []

    expected_count = len(deck.get("slides", []))
    if len(mapped) != expected_count:
        failures.append("slide-count")

    layout_parts = package.slide_layout_parts()
    if len(layout_parts) < 2:
        failures.append("layout-count")

    has_table = any(s.get("table") for s in deck.get("slides", []))
    has_chart = any(s.get("chart_reference") for s in deck.get("slides", []))
    has_image = any(s.get("image_reference") for s in deck.get("slides", []))
    has_notes = any(s.get("notes") for s in deck.get("slides", []))

    if has_chart and not package.chart_parts():
        failures.append("chart-reference")
    if has_image and not package.media_parts():
        failures.append("image-reference")
    if has_notes and not package.notes_slide_parts():
        failures.append("notes")

    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Created PPTX does not satisfy the deck semantics.",
            details={"missing_or_mismatched": failures},
        )
    return {
        "slides": len(mapped),
        "layouts": len(layout_parts),
        "requested_structure": True,
    }


def _assert_consumer_package(path: Path) -> dict[str, Any]:
    """Reject known theme/reference shapes that PowerPoint repairs or rejects."""

    package = OpcPackage.open(path)
    presentation = package.xml("ppt/presentation.xml")
    relationship_ids = {
        relationship.relationship_id
        for relationship in package.part_rels("ppt/presentation.xml")
    }
    referenced_ids = {
        value
        for node in presentation.iter()
        for name, value in node.attrib.items()
        if name == f"{{{NS['r']}}}id"
    }
    missing_relationships = sorted(referenced_ids - relationship_ids)

    theme_parts = package.theme_parts()
    missing_theme_schemes: list[str] = []
    if not theme_parts:
        missing_theme_schemes.append("theme")
    else:
        theme = package.xml(theme_parts[0])
        theme_elements = next(
            (item for item in theme if item.tag.rsplit("}", 1)[-1] == "themeElements"),
            None,
        )
        present = (
            set()
            if theme_elements is None
            else {item.tag.rsplit("}", 1)[-1] for item in theme_elements}
        )
        missing_theme_schemes.extend(
            sorted({"clrScheme", "fontScheme", "fmtScheme"} - present)
        )
    if missing_relationships or missing_theme_schemes:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PPTX package is not consumer-conformant.",
            details={
                "missing_relationship_ids": missing_relationships,
                "missing_theme_schemes": missing_theme_schemes,
            },
        )
    return {
        "referenced_relationships": len(referenced_ids),
        "theme_schemes": 3,
        "consumer_conformant": True,
    }


def _assert_scene_created(
    path: Path,
    scene: NormalizedScene,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    package = OpcPackage.open(path)
    mapped = map_slides(package)
    manifest_items = manifest.get("items")
    failures = generated_scene_opc_failures(package)
    expected_manifest_items: list[dict[str, Any]] = []
    for slide_number, slide in enumerate(scene.slides, 1):
        for z_order, item in enumerate(slide):
            geometry = _expected_scene_geometry(item)
            if geometry is None:
                failures.append(f"slide-{slide_number}-scene-geometry-{z_order + 2}")
                geometry = {}
            is_picture = item.get("outcome") == "rasterized" or item.get("kind") == "image"
            text = item.get("text")
            if type(text) is not str:
                failures.append(f"slide-{slide_number}-scene-text-{z_order + 2}")
                text = ""
            expected_manifest_items.append({
                "slide": slide_number,
                "source_id": item.get("source_id"),
                "shape_id": z_order + 2,
                "z_order": z_order,
                "kind": "image" if is_picture else item.get("kind"),
                "outcome": item.get("outcome"),
                "asset_sha256": item.get("asset_id"),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "geometry": geometry,
            })
    if len(mapped) != len(scene.slides):
        failures.append("slide-count")
    presentation = package.xml("ppt/presentation.xml")
    slide_size = presentation.find(f"{{{NS['p']}}}sldSz")
    if slide_size is None or slide_size.get("cx") != str(SLIDE_CX) or slide_size.get("cy") != str(SLIDE_CY):
        failures.append("canvas-size")
    expected_media_hashes = sorted({
        item["asset_id"]
        for slide in scene.slides
        for item in slide
        if item.get("asset_id") is not None
    })
    if (
        manifest.get("slide_size") != {"cx": SLIDE_CX, "cy": SLIDE_CY}
        or manifest.get("slides") != len(scene.slides)
        or manifest.get("objects") != len(expected_manifest_items)
        or manifest.get("media") != len(expected_media_hashes)
    ):
        failures.append("manifest-summary")
    if manifest_items != expected_manifest_items:
        failures.append("manifest-correspondence")
    for slide_number, slide in enumerate(mapped[:len(scene.slides)], 1):
        expected_scene_items = scene.slides[slide_number - 1]
        expected = [
            item for item in expected_manifest_items
            if item["slide"] == slide_number
        ]
        actual = slide.get("shapes", [])
        actual_ids = [int(shape.get("id", 0)) for shape in actual]
        if actual_ids != [item["shape_id"] for item in expected]:
            failures.append(f"slide-{slide_number}-ids-z-order")
        actual_names = [shape.get("name") for shape in actual]
        if actual_names != [str(item["source_id"])[:80] for item in expected]:
            failures.append(f"slide-{slide_number}-source-ids")
        evidence = _slide_shape_evidence(package, slide.get("part"))
        if len(evidence) != len(expected):
            failures.append(f"slide-{slide_number}-object-count")
        relationships = {
            relationship.relationship_id: relationship
            for relationship in package.relationships
            if relationship.source_part == slide.get("part")
        }
        for shape, expected_item, manifest_item, shape_evidence in zip(
            actual, expected_scene_items, expected, evidence
        ):
            shape_id = manifest_item["shape_id"]
            expected_picture = (
                expected_item.get("outcome") == "rasterized"
                or expected_item.get("kind") == "image"
            )
            if shape.get("type") != ("picture" if expected_picture else "shape"):
                failures.append(f"slide-{slide_number}-kind-{shape_id}")
            if shape_evidence.get("id") != str(shape_id):
                failures.append(f"slide-{slide_number}-xml-id-{shape_id}")
            actual_paragraph_runs = [
                [run.get("text", "") for run in paragraph.get("runs", [])]
                for frame in shape.get("text_frames", [])
                for paragraph in frame.get("paragraphs", [])
            ]
            if actual_paragraph_runs != _expected_paragraph_runs(expected_item):
                failures.append(f"slide-{slide_number}-runs-{shape_id}")
            offset = shape_evidence.get("offset") or {}
            extent = shape_evidence.get("extent") or {}
            emitted_geometry = manifest_item.get("geometry") or {}
            if (
                offset.get("x") != str(emitted_geometry.get("x"))
                or offset.get("y") != str(emitted_geometry.get("y"))
                or extent.get("cx") != str(emitted_geometry.get("cx"))
                or extent.get("cy") != str(emitted_geometry.get("cy"))
            ):
                failures.append(f"slide-{slide_number}-geometry-{shape_id}")
            if not _in_bounds_emu_geometry(offset, extent):
                failures.append(f"slide-{slide_number}-geometry-bounds-{shape_id}")
            embed_id = shape_evidence.get("embed")
            if expected_picture:
                relationship = relationships.get(embed_id)
                target = relationship.resolved_target if relationship is not None else None
                actual_asset_hash = package.part_hashes.get(target or "")
                if (
                    relationship is None
                    or not relationship.relationship_type.endswith("/image")
                    or actual_asset_hash != expected_item.get("asset_id")
                ):
                    failures.append(f"slide-{slide_number}-media-{shape_id}")
            elif embed_id is not None:
                failures.append(f"slide-{slide_number}-unexpected-media-{shape_id}")
    media_hashes = sorted(
        hashlib.sha256(package.parts[name]).hexdigest()
        for name in package.media_parts()
    )
    if media_hashes != expected_media_hashes or manifest.get("media_hashes") != expected_media_hashes:
        failures.append("media-hashes")
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Scene-to-package validation failed.",
            details={"failures": failures[:64]},
        )
    return {
        "slides": len(mapped),
        "objects": len(expected_manifest_items),
        "media": len(media_hashes),
        "deterministic_ids": True,
        "finite_in_bounds_geometry": True,
        "one_to_one_manifest": True,
    }


def _slide_shape_evidence(
    package: OpcPackage,
    slide_part: str | None,
) -> list[dict[str, Any]]:
    if slide_part is None:
        return []
    root = package.xml(slide_part)
    tree = root.find(f"{{{NS['p']}}}cSld/{{{NS['p']}}}spTree")
    if tree is None:
        return []
    result: list[dict[str, Any]] = []
    for element in tree:
        if element.tag not in {f"{{{NS['p']}}}sp", f"{{{NS['p']}}}pic"}:
            continue
        non_visual = element.find(f".//{{{NS['p']}}}cNvPr")
        properties = element.find(f"{{{NS['p']}}}spPr")
        transform = properties.find(f"{{{NS['a']}}}xfrm") if properties is not None else None
        offset = transform.find(f"{{{NS['a']}}}off") if transform is not None else None
        extent = transform.find(f"{{{NS['a']}}}ext") if transform is not None else None
        blip = element.find(f"{{{NS['p']}}}blipFill/{{{NS['a']}}}blip")
        result.append({
            "id": non_visual.get("id", "") if non_visual is not None else "",
            "offset": dict(offset.attrib) if offset is not None else {},
            "extent": dict(extent.attrib) if extent is not None else {},
            "embed": blip.get(f"{{{NS['r']}}}embed") if blip is not None else None,
        })
    return result


def _expected_scene_geometry(item: dict[str, Any]) -> dict[str, int] | None:
    names = ("x", "y", "width", "height")
    values = [item.get(name) for name in names]
    if any(type(value) not in {int, float} or not math.isfinite(value) for value in values):
        return None
    x, y, width, height = values
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return None
    if (x + width) * EMU_PER_PIXEL > SLIDE_CX or (y + height) * EMU_PER_PIXEL > SLIDE_CY:
        return None
    return {
        "x": max(0, min(SLIDE_CX, int(round(x * EMU_PER_PIXEL)))),
        "y": max(0, min(SLIDE_CX, int(round(y * EMU_PER_PIXEL)))),
        "cx": max(0, min(SLIDE_CX, int(round(width * EMU_PER_PIXEL)))),
        "cy": max(0, min(SLIDE_CX, int(round(height * EMU_PER_PIXEL)))),
    }


def _expected_paragraph_runs(item: dict[str, Any]) -> list[list[str]]:
    if not item.get("text"):
        return []
    paragraphs = item.get("paragraphs") or [{"runs": [{"text": item["text"]}]}]
    return [
        [run.get("text", "") for run in paragraph.get("runs", [])]
        for paragraph in paragraphs
    ]


def _in_bounds_emu_geometry(offset: dict[str, str], extent: dict[str, str]) -> bool:
    try:
        x = int(offset["x"])
        y = int(offset["y"])
        width = int(extent["cx"])
        height = int(extent["cy"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        x >= 0
        and y >= 0
        and width > 0
        and height > 0
        and x + width <= SLIDE_CX
        and y + height <= SLIDE_CY
    )


def _assert_preservation(manifest: PreservationManifest) -> dict[str, Any]:
    if manifest.removed:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "A PPTX mutation removed package parts.",
            details={"removed_parts": list(manifest.removed)},
        )
    mismatched = [
        name
        for name in manifest.preserved
        if manifest.input_hashes[name] != manifest.output_hashes[name]
    ]
    if mismatched:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "A preserved PPTX part changed.",
            details={"parts": mismatched},
        )
    return {
        "changed_parts": list(manifest.changed),
        "added_parts": list(manifest.added),
        "removed_parts": list(manifest.removed),
        "preserved_parts": len(manifest.preserved),
    }


def _extract_text(slide: dict[str, Any]) -> str:
    texts: list[str] = []
    for shape in slide.get("shapes", []):
        for frame in shape.get("text_frames", []):
            for para in frame.get("paragraphs", []):
                for run in para.get("runs", []):
                    texts.append(run.get("text", ""))
        table = shape.get("table")
        if table:
            for row in table.get("rows", []):
                for cell in row.get("cells", []):
                    texts.append(cell.get("text", ""))
    return "|".join(texts)


def _extract_chart_refs(package: OpcPackage, slide_part: str) -> list[tuple[str, str]]:
    """Slide-level chart relationship references (rId, resolved target), sorted for stable comparison."""
    refs = [
        (rel.relationship_id, rel.resolved_target or "")
        for rel in package.relationships
        if rel.source_part == slide_part and "chart" in rel.relationship_type
    ]
    return sorted(refs)


def _extract_image_refs(package: OpcPackage, slide_part: str) -> list[tuple[str, str]]:
    """Slide-level image relationship references (rId, resolved target), sorted for stable comparison."""
    refs = [
        (rel.relationship_id, rel.resolved_target or "")
        for rel in package.relationships
        if rel.source_part == slide_part and "image" in rel.relationship_type
    ]
    return sorted(refs)


def _extract_connectors(slide: dict[str, Any]) -> list[tuple[str, str, str, str, str, str]]:
    """Connector definitions (id, preset, off-x, off-y, ext-cx, ext-cy), sorted for stable comparison."""
    connectors: list[tuple[str, str, str, str, str, str]] = []
    for shape in slide.get("shapes", []):
        if shape.get("type") != "connector":
            continue
        geom = shape.get("geometry") or {}
        offset = geom.get("offset") or {}
        extent = geom.get("extent") or {}
        connectors.append((
            shape.get("id", ""),
            geom.get("preset", ""),
            offset.get("x", ""),
            offset.get("y", ""),
            extent.get("cx", ""),
            extent.get("cy", ""),
        ))
    return sorted(connectors)


def _compare_nested(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if type(a) is not dict or type(b) is not dict:
        return a == b
    return a.get("part") == b.get("part") and a.get("relationship_id") == b.get("relationship_id")


def _compare_notes(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if a.get("part") != b.get("part"):
        return False
    return _extract_notes_text(a) == _extract_notes_text(b)


def _extract_notes_text(notes: dict[str, Any]) -> str:
    texts: list[str] = []
    for frame in notes.get("text_frames", []):
        for para in frame.get("paragraphs", []):
            for run in para.get("runs", []):
                texts.append(run.get("text", ""))
    return "|".join(texts)


def _required_report(
    path: Path,
    *,
    source: Path | None = None,
    source_sha256: str | None = None,
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] | None = None,
) -> dict[str, Any]:
    report = validate_artifact(
        path,
        expected_format="pptx",
        source_path=source,
        source_sha256=source_sha256,
        reopen=reopen_pptx,
        assertions=assertions,
        visual_available=False,
        schema_available=False,
    )
    if report["status"] != "pass":
        failed = [
            gate["id"]
            for gate in report["gates"]
            if gate["required"] and gate["outcome"] != "pass"
        ]
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Staged PPTX failed required validation gates.",
            details={"failed_gates": failed},
            validation=report,
        )
    return report
