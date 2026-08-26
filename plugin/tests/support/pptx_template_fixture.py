"""Synthetic A-Contract semantic template fixture builder for B2 tests."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import tostring

from document_skills_core.formats.pptx.constants import NS
from document_skills_core.formats.pptx.contact_sheet import PngImage, encode_png
from document_skills_core.formats.pptx.contracts import parse_deck
from document_skills_core.formats.pptx.create import create_pptx
from document_skills_core.formats.pptx.package import OpcPackage, write_deterministic_zip
from document_skills_core.formats.pptx.object_xml import object_type
from document_skills_core.formats.pptx.presentation_contracts import (
    PresentationContractConsumer,
    _canonical_deck_hash,
)

_P = NS["p"]
_A = NS["a"]


@dataclass(frozen=True)
class SemanticTemplateFixture:
    source: Path
    descriptor: dict[str, Any]
    catalog_ref: dict[str, str]
    slide_ids: tuple[str, ...]
    slot_ids: tuple[str, ...]
    typed_slot_ids: dict[str, str]


def build_semantic_template(
    root: Path,
    project_root: Path,
    *,
    slides: int = 3,
    template_id: str = "semantic-neutral",
    slide_roles: tuple[str, ...] | None = None,
) -> SemanticTemplateFixture:
    contract_root = _owner_contract_root(project_root)
    roles = slide_roles or tuple("cover" if index == 0 else "content" for index in range(slides))
    if len(roles) != slides:
        raise ValueError("slide_roles must contain exactly one role per slide")
    deck_id = PresentationContractConsumer.stable_deck_id(
        namespace="elftia.synthetic",
        source_template_id=template_id,
        source_template_version="1.0.0",
    )
    slide_ids = tuple(
        PresentationContractConsumer.stable_slide_id(
            deck_id=deck_id,
            source_template_id=template_id,
            semantic_key=f"page-{index + 1}",
        )
        for index in range(slides)
    )
    slot_ids = tuple(f"page-{index + 1}-title" for index in range(slides))
    object_ids = tuple(
        PresentationContractConsumer.stable_object_id(
            slide_id=slide_id,
            semantic_key=slot_id,
        )
        for slide_id, slot_id in zip(slide_ids, slot_ids, strict=True)
    )
    typed_slot_ids = {
        "image-ref": "page-1-image",
        "table-data": "page-2-table",
        "chart-data": "page-3-chart",
    } if slides >= 3 else {}
    typed_object_ids = {
        kind: PresentationContractConsumer.stable_object_id(
            slide_id=slide_ids[{"image-ref": 0, "table-data": 1, "chart-data": 2}[kind]],
            semantic_key=slot_id,
        )
        for kind, slot_id in typed_slot_ids.items()
    }
    images = []
    for index in range(slides):
        image = root / f"source-{index + 1}.png"
        color = (
            min(240, 40 + index * 35),
            min(230, 90 + index * 25),
            max(20, 170 - index * 25),
            255,
        )
        image.write_bytes(encode_png(PngImage(2, 2, bytes(color) * 4)))
        images.append(image)
    source = root / "semantic-template.pptx"
    deck = {
        "metadata": {"title": "Semantic fixture", "creator": "Elftia", "subject": "B2"},
        "slides": [
            {
                "layout": "content",
                "title": f"Template page {index + 1}",
                "shapes": [{"text": f"Body {index + 1}", "runs": []}],
                "table": (
                    {"rows": [{"cells": ["Metric", "Value"]}, {"cells": ["A", "1"]}]}
                    if index == 1
                    else None
                ),
                "chart_reference": _chart(index + 1),
                "image_reference": {
                    "path": str(images[index]),
                    "content_type": "image/png",
                    "fit": "contain",
                    "alt_text": f"Synthetic image {index + 1}",
                },
                "notes": f"Approved notes {index + 1}",
            }
            for index in range(slides)
        ],
    }
    create_pptx(source, parse_deck(deck))
    _assign_stable_addresses(source, slide_ids, object_ids, typed_object_ids)
    source_hash = sha256(source.read_bytes()).hexdigest()
    template_contract = {
        "schemaVersion": "1.0.0",
        "templateId": template_id,
        "version": "1.0.0",
        "assetRef": {
            "catalogId": "synthetic",
            "assetId": template_id,
            "version": "1.0.0",
            "sha256": f"sha256:{source_hash}",
        },
        "provenanceRef": {"catalogId": "synthetic", "assetId": template_id},
        "licenseStatus": "not_evaluated",
        "semanticSlotSchemaVersion": "1.0.0",
        "deckIrSchemaVersion": "1.0.0",
    }
    semantic_slots = {
        "schemaVersion": "1.0.0",
        "templateId": template_id,
        "slots": [
            _slot(slot_id, object_id, "text", "title", required=True)
            for slot_id, object_id in zip(slot_ids, object_ids, strict=True)
        ] + [
            _slot(
                typed_slot_ids[data_type],
                typed_object_ids[data_type],
                data_type,
                {"image-ref": "image", "table-data": "table", "chart-data": "chart"}[data_type],
                required=False,
            )
            for data_type in ("image-ref", "table-data", "chart-data")
            if data_type in typed_slot_ids
        ],
    }
    deck_ir = _deck_ir(
        deck_id,
        template_id,
        slide_ids,
        slot_ids,
        object_ids,
        typed_slot_ids,
        typed_object_ids,
        roles,
    )
    refs = {}
    for key, value in (
        ("template_contract", template_contract),
        ("semantic_slots", semantic_slots),
        ("deck_ir", deck_ir),
    ):
        path = root / f"{key}.json"
        data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        path.write_bytes(data)
        refs[key] = {"path": str(path), "sha256": sha256(data).hexdigest()}
    catalog_ref = dict(template_contract["assetRef"])
    return SemanticTemplateFixture(
        source,
        {"contract_root": str(contract_root), **refs},
        catalog_ref,
        slide_ids,
        slot_ids,
        typed_slot_ids,
    )


def _deck_ir(
    deck_id: str,
    template_id: str,
    slide_ids: tuple[str, ...],
    slot_ids: tuple[str, ...],
    object_ids: tuple[str, ...],
    typed_slot_ids: dict[str, str],
    typed_object_ids: dict[str, str],
    slide_roles: tuple[str, ...],
) -> dict[str, Any]:
    result = {
        "schemaVersion": "1.0.0",
        "contractVersion": "1.0.0",
        "featureFlags": ["semantic-slots"],
        "migration": {"policy": "explicit-only", "minimumReaderVersion": "1.0.0"},
        "deckId": deck_id,
        "title": "Semantic fixture",
        "canvasProfiles": [{"id": "screen-16x9", "width": 13.333, "height": 7.5, "unit": "in"}],
        "refs": {"licenseStatus": "not_evaluated"},
        "editability": "native",
        "nativeTarget": "both",
        "degradationBudget": {"maximum": "none", "allowedFallbacks": []},
        "slides": [
            {
                "slideId": slide_id,
                "role": slide_roles[index],
                "canvasProfileId": "screen-16x9",
                "objects": [
                    _text_object(template_id=template_id, slot_id=slot_id, object_id=object_id, text=f"Template page {index + 1}")
                ] + _typed_objects(
                    index,
                    template_id,
                    typed_slot_ids,
                    typed_object_ids,
                ),
            }
            for index, (slide_id, slot_id, object_id) in enumerate(zip(slide_ids, slot_ids, object_ids, strict=True))
        ],
        "materializationDiagnostics": [],
        "unsupportedFeatures": [],
        "generatedBy": {"producer": "synthetic-test", "contractVersion": "1.0.0"},
        "contentHash": "sha256:" + "0" * 64,
    }
    result["contentHash"] = _canonical_deck_hash(result)
    return result


def _text_object(*, template_id: str, slot_id: str, object_id: str, text: str) -> dict[str, Any]:
    return {
        "objectId": object_id,
        "type": "text",
        "bounds": {"x": 0.8, "y": 0.6, "width": 11.7, "height": 0.8},
        "zOrder": 1,
        "slotBinding": {"templateId": template_id, "slotId": slot_id},
        "refs": {"licenseStatus": "not_evaluated"},
        "editability": "native",
        "nativeTarget": "both",
        "degradationBudget": {"maximum": "none", "allowedFallbacks": []},
        "unsupportedFeatures": [],
        "materializationDiagnostics": [],
        "content": {"text": text},
    }


def _typed_objects(
    slide_index: int,
    template_id: str,
    slots: dict[str, str],
    objects: dict[str, str],
) -> list[dict[str, Any]]:
    common = {
        "refs": {"licenseStatus": "not_evaluated"},
        "editability": "native",
        "nativeTarget": "both",
        "degradationBudget": {"maximum": "none", "allowedFallbacks": []},
        "unsupportedFeatures": [],
        "materializationDiagnostics": [],
    }
    if slide_index == 0 and "image-ref" in slots:
        return [{
            "objectId": objects["image-ref"],
            "type": "image",
            "bounds": {"x": 9.0, "y": 4.5, "width": 2.0, "height": 1.5},
            "zOrder": 2,
            "slotBinding": {"templateId": template_id, "slotId": slots["image-ref"]},
            **common,
            "content": {
                "assetRef": {"catalogId": "synthetic", "assetId": "fixture-image"},
                "altText": "Synthetic image 1",
                "fit": "contain",
            },
        }]
    if slide_index == 1 and "table-data" in slots:
        return [{
            "objectId": objects["table-data"],
            "type": "table",
            "bounds": {"x": 0.8, "y": 3.0, "width": 5.0, "height": 2.0},
            "zOrder": 2,
            "slotBinding": {"templateId": template_id, "slotId": slots["table-data"]},
            **common,
            "content": {"rows": [["Metric", "Value"], ["A", "1"]], "headerRows": 1},
        }]
    if slide_index == 2 and "chart-data" in slots:
        return [{
            "objectId": objects["chart-data"],
            "type": "chart",
            "bounds": {"x": 5.8, "y": 2.0, "width": 6.0, "height": 4.0},
            "zOrder": 2,
            "slotBinding": {"templateId": template_id, "slotId": slots["chart-data"]},
            **common,
            "content": {
                "chartKind": "column",
                "categories": ["A", "B"],
                "series": [{"name": "Value", "values": [3, 4]}],
            },
        }]
    return []


def _assign_stable_addresses(
    source: Path,
    slide_ids: tuple[str, ...],
    object_ids: tuple[str, ...],
    typed_object_ids: dict[str, str],
) -> None:
    package = OpcPackage.open(source)
    parts = dict(package.parts)
    for index, (slide_id, object_id) in enumerate(zip(slide_ids, object_ids, strict=True), 1):
        part = f"ppt/slides/slide{index}.xml"
        root = package.xml(part)
        common = root.find(f"{{{_P}}}cSld")
        assert common is not None
        common.set("name", slide_id)
        title = f"Template page {index}"
        shape = next(
            item
            for item in root.iter(f"{{{_P}}}sp")
            if any((node.text or "") == title for node in item.iter(f"{{{_A}}}t"))
        )
        properties = next(shape.iter(f"{{{_P}}}cNvPr"))
        properties.set("name", object_id)
        typed_kind = {0: "image-ref", 1: "table-data", 2: "chart-data"}.get(index - 1)
        if typed_kind in typed_object_ids:
            expected_type = {
                "image-ref": "image",
                "table-data": "table",
                "chart-data": "chart",
            }[typed_kind]
            typed = next(
                item
                for item in list(root.find(f"{{{_P}}}cSld").find(f"{{{_P}}}spTree"))
                if object_type(item) == expected_type
            )
            next(typed.iter(f"{{{_P}}}cNvPr")).set("name", typed_object_ids[typed_kind])
        parts[part] = tostring(root, encoding="UTF-8", xml_declaration=True)
    write_deterministic_zip(source, parts)


def _chart(value: int) -> dict[str, Any]:
    return {
        "title": f"Chart {value}",
        "chart_type": "column",
        "categories": ["A", "B"],
        "series": [{"name": "Value", "values": [value, value + 1]}],
        "legend": {"show": False, "position": "right"},
        "axes": {
            "category": {"title": "Category", "number_format": "General"},
            "value": {"title": "Value", "number_format": "0"},
        },
        "data_labels": {"show_value": True},
        "colors": ["3366CC"],
    }


def _slot(
    slot_id: str,
    object_id: str,
    data_type: str,
    role: str,
    *,
    required: bool,
) -> dict[str, Any]:
    return {
        "slotId": slot_id,
        "role": role,
        "dataType": data_type,
        "cardinality": {
            "kind": "required" if required else "optional",
            "min": 1 if required else 0,
            "max": 1,
        },
        "capacity": {
            "latinRecommendedCharacters": 72,
            "cjkRecommendedCharacters": 36,
            "maxLines": 6,
            "minFontSizePt": 12,
            "overflowPolicy": "reject",
        },
        "constraints": {},
        "styleBinding": {"layoutToken": f"layout.{role}"},
        "sourceObjectId": object_id,
        "licenseBoundary": "user-content",
    }


def _owner_contract_root(project_root: Path) -> Path:
    root = project_root.parents[1] / "elftia" / "packages" / "presentation-contracts"
    if not root.is_dir():
        raise RuntimeError("presentation-contract owner package is required for B2 fixtures")
    return root
