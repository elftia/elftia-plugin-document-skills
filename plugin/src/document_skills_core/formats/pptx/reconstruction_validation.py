"""Mandatory validation for layered reconstruction receipts and scenes."""

import math
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record

from .constants import NS
from .package import OpcPackage
from .reconstruction_scene import union_area
from .scene_emitter import EMU_PER_PIXEL, SLIDE_CX, SLIDE_CY
from .scene_normalizer import NormalizedScene


def with_reconstruction_gate(
    validation: dict[str, Any],
    path: Path,
    scene: NormalizedScene,
    emission: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    evidence = _assert_reconstruction(path, scene, emission, receipt)
    gate = gate_record(
        "reconstruction-layer-integrity",
        "pass",
        required=True,
        evidence=evidence,
    )
    return {**validation, "gates": [*validation["gates"], gate]}


def _assert_reconstruction(
    path: Path,
    scene: NormalizedScene,
    emission: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    if not path.is_file() or len(scene.slides) != 1:
        _failed("Reconstruction candidate or slide inventory is invalid.")
    elements = receipt.get("elements")
    items = emission.get("items")
    if (
        type(elements) is not list
        or type(items) is not list
        or len(elements) != len(items)
        or emission.get("objects") != len(elements)
    ):
        _failed("Reconstruction receipt does not match emitted objects.")
    scene_items = [item for slide in scene.slides for item in slide]
    scene_by_id = _by_identity(scene_items, "source_id")
    emission_by_id = _by_identity(items, "source_id")
    receipt_by_id = _by_identity(elements, "id")
    if set(scene_by_id) != set(receipt_by_id) or set(emission_by_id) != set(receipt_by_id):
        _failed("Reconstruction object inventories do not match.")
    coverage = receipt.get("editable_coverage")
    if type(coverage) is not dict:
        _failed("Reconstruction coverage evidence is missing.")
    _assert_coverage(coverage, elements)
    if receipt.get("whole_slide_raster") is not False:
        _failed("Whole-slide raster reconstruction is forbidden.")
    canvas = receipt.get("canvas")
    if (
        type(canvas) is not dict
        or set(canvas) != {"height", "width"}
        or any(type(canvas[name]) is not int or canvas[name] <= 0 for name in canvas)
    ):
        _failed("Reconstruction canvas evidence is invalid.")
    rasterized = 0
    picture_expectations: dict[str, dict[str, dict[str, int]]] = {}
    for element in elements:
        identity = element["id"]
        scene_item = scene_by_id[identity]
        emitted = emission_by_id[identity]
        outcome = element.get("outcome")
        if outcome not in {"editable", "rasterized"}:
            _failed("Reconstruction element outcome is invalid.")
        scene_outcome = scene_item.get("outcome")
        emitted_outcome = emitted.get("outcome")
        outcome_matches = (
            scene_outcome == "rasterized" and emitted_outcome == "rasterized"
            if outcome == "rasterized"
            else scene_outcome in {"approximated", "native"}
            and emitted_outcome == scene_outcome
        )
        if not outcome_matches:
            _failed("Reconstruction outcome does not match emitted evidence.")
        if scene_item.get("opacity") != 1:
            _failed("Reconstruction objects must remain visible.")
        is_picture = outcome == "rasterized" or scene_item.get("kind") == "image"
        if is_picture:
            if emitted.get("kind") != "image" or emitted.get("asset_sha256") is None:
                _failed("Reconstruction raster inventory is invalid.")
            expected_crop = _expected_crop(element.get("source_region"), canvas)
            _assert_crop(scene_item.get("image_crop"), expected_crop)
            expected_transform = _expected_transform(
                element.get("geometry"),
                canvas,
                scene_item,
            )
            if emitted.get("geometry") != expected_transform:
                _failed("Reconstruction emission geometry does not match the receipt.")
            picture_expectations[identity] = {
                "crop": {
                    side[0]: int(round(expected_crop[side] * 100_000))
                    for side in ("bottom", "left", "right", "top")
                },
                "transform": expected_transform,
            }
        elif emitted.get("kind") == "image" or emitted.get("asset_sha256") is not None:
            _failed("Editable reconstruction object unexpectedly references raster media.")
        if outcome == "rasterized":
            rasterized += 1
    _assert_package_pictures(path, picture_expectations)
    return {
        "elements": len(elements),
        "picture_elements": len(picture_expectations),
        "rasterized_elements": rasterized,
        "whole_slide_raster": False,
    }


def _by_identity(values: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    if any(type(item) is not dict or type(item.get(field)) is not str for item in values):
        _failed("Reconstruction identity evidence is invalid.")
    result = {item[field]: item for item in values}
    if len(result) != len(values):
        _failed("Reconstruction identities must be unique.")
    return result


def _assert_coverage(coverage: dict[str, Any], elements: list[dict[str, Any]]) -> None:
    by_area = coverage.get("by_area")
    by_count = coverage.get("by_object_count")
    for record in (by_area, by_count):
        if (
            type(record) is not dict
            or set(record) != {"editable", "ratio", "total"}
            or any(type(record[name]) not in {int, float} for name in record)
            or any(not math.isfinite(record[name]) for name in record)
            or record["editable"] < 0
            or record["total"] <= 0
            or record["editable"] > record["total"]
            or not 0 <= record["ratio"] <= 1
        ):
            _failed("Reconstruction coverage evidence is invalid.")
    editable = [item for item in elements if item.get("outcome") == "editable"]
    total_area = union_area(item["source_region"] for item in elements)
    editable_area = union_area(item["source_region"] for item in editable)
    expected_area_ratio = editable_area / total_area
    expected_count_ratio = len(editable) / len(elements)
    if (
        by_area["editable"] != editable_area
        or by_area["total"] != total_area
        or not math.isclose(by_area["ratio"], expected_area_ratio, rel_tol=1e-12)
        or by_count["editable"] != len(editable)
        or by_count["total"] != len(elements)
        or not math.isclose(by_count["ratio"], expected_count_ratio, rel_tol=1e-12)
    ):
        _failed("Reconstruction coverage does not match final element outcomes.")


def _assert_crop(value: Any, expected: dict[str, float]) -> None:
    if (
        type(value) is not dict
        or set(value) != {"bottom", "left", "right", "top"}
        or any(type(item) not in {int, float} or not math.isfinite(item) for item in value.values())
        or any(not 0 <= item < 1 for item in value.values())
        or value["left"] + value["right"] >= 1
        or value["top"] + value["bottom"] >= 1
        or not any(item > 0 for item in value.values())
    ):
        _failed("Rasterized reconstruction element lacks a bounded crop.")
    if any(
        not math.isclose(value[name], expected[name], rel_tol=0, abs_tol=1e-12)
        for name in expected
    ):
        _failed("Reconstruction scene crop does not match the receipt.")


def _expected_crop(value: Any, canvas: dict[str, int]) -> dict[str, float]:
    rect = _validated_rect(value, canvas, "source region")
    return {
        "bottom": 1 - (rect["y"] + rect["height"]) / canvas["height"],
        "left": rect["x"] / canvas["width"],
        "right": 1 - (rect["x"] + rect["width"]) / canvas["width"],
        "top": rect["y"] / canvas["height"],
    }


def _expected_transform(
    value: Any,
    canvas: dict[str, int],
    scene_item: dict[str, Any],
) -> dict[str, int]:
    rect = _validated_rect(value, canvas, "geometry")
    projected = {
        "height": rect["height"] * 1_080 / canvas["height"],
        "width": rect["width"] * 1_920 / canvas["width"],
        "x": rect["x"] * 1_920 / canvas["width"],
        "y": rect["y"] * 1_080 / canvas["height"],
    }
    if any(
        type(scene_item.get(name)) not in {int, float}
        or not math.isclose(
            scene_item[name],
            projected[name],
            rel_tol=0,
            abs_tol=1e-12,
        )
        for name in projected
    ):
        _failed("Reconstruction scene geometry does not match the receipt.")
    transform = {
        "cx": _emu(projected["width"]),
        "cy": _emu(projected["height"]),
        "x": _emu(projected["x"]),
        "y": _emu(projected["y"]),
    }
    if _is_full_slide_transform(transform):
        _failed("Whole-slide raster destination geometry is forbidden.")
    return transform


def _validated_rect(value: Any, canvas: dict[str, int], label: str) -> dict[str, float]:
    if type(value) is not dict or set(value) != {"height", "width", "x", "y"}:
        _failed(f"Reconstruction {label} evidence is invalid.")
    rect: dict[str, float] = {}
    for name in ("height", "width", "x", "y"):
        number = value[name]
        if type(number) not in {int, float} or not math.isfinite(number):
            _failed(f"Reconstruction {label} evidence is invalid.")
        rect[name] = float(number)
    if (
        rect["x"] < 0
        or rect["y"] < 0
        or rect["width"] <= 0
        or rect["height"] <= 0
        or rect["x"] + rect["width"] > canvas["width"]
        or rect["y"] + rect["height"] > canvas["height"]
    ):
        _failed(f"Reconstruction {label} evidence is invalid.")
    return rect


def _emu(value: float) -> int:
    return max(0, min(SLIDE_CX, int(round(value * EMU_PER_PIXEL))))


def _is_full_slide_transform(value: dict[str, int]) -> bool:
    return (
        value["x"] == 0
        and value["y"] == 0
        and value["cx"] >= SLIDE_CX
        and value["cy"] >= SLIDE_CY
    )


def _assert_package_pictures(
    path: Path,
    expectations: dict[str, dict[str, dict[str, int]]],
) -> None:
    package = OpcPackage.open(path)
    pictures: dict[str, Any] = {}
    for slide_part in package.slide_parts():
        root = package.xml(slide_part)
        for picture in root.iter(f"{{{NS['p']}}}pic"):
            non_visual = picture.find(f"{{{NS['p']}}}nvPicPr/{{{NS['p']}}}cNvPr")
            identity = non_visual.get("name") if non_visual is not None else None
            if type(identity) is not str or identity in pictures:
                _failed("Reconstruction package picture identities are invalid.")
            if non_visual.get("hidden") not in {None, "0", "false"}:
                _failed("Hidden reconstruction raster underlays are forbidden.")
            pictures[identity] = picture
    if set(pictures) != set(expectations):
        _failed("Reconstruction package picture inventory does not match the receipt.")
    for identity, picture in pictures.items():
        source_rect = picture.find(f"{{{NS['p']}}}blipFill/{{{NS['a']}}}srcRect")
        if source_rect is None:
            _failed("Reconstruction package picture lacks crop evidence.")
        try:
            crop = {name: int(source_rect.get(name, "0")) for name in ("b", "l", "r", "t")}
        except ValueError:
            _failed("Reconstruction package crop evidence is invalid.")
        if any(not 0 <= value < 100_000 for value in crop.values()) or not any(crop.values()):
            _failed("Whole-slide or invalid package raster crop is forbidden.")
        if crop != expectations[identity]["crop"]:
            _failed("Reconstruction package crop does not match the receipt.")
        transform = picture.find(f"{{{NS['p']}}}spPr/{{{NS['a']}}}xfrm")
        offset = None if transform is None else transform.find(f"{{{NS['a']}}}off")
        extent = None if transform is None else transform.find(f"{{{NS['a']}}}ext")
        if offset is None or extent is None:
            _failed("Reconstruction package picture transform is missing.")
        try:
            actual_transform = {
                "cx": int(extent.get("cx", "")),
                "cy": int(extent.get("cy", "")),
                "x": int(offset.get("x", "")),
                "y": int(offset.get("y", "")),
            }
        except ValueError:
            _failed("Reconstruction package picture transform is invalid.")
        if _is_full_slide_transform(actual_transform):
            _failed("Whole-slide package picture transform is forbidden.")
        if actual_transform != expectations[identity]["transform"]:
            _failed("Reconstruction package transform does not match the receipt.")


def _failed(message: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        message,
        details={"reconstruction_layer_integrity": False},
    )
