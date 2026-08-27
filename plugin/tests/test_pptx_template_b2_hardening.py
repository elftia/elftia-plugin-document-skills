from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import posixpath
import shutil
import struct
import subprocess
import zlib
from xml.etree.ElementTree import SubElement, tostring

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pptx import (
    image as pptx_image,
    package as pptx_package,
    template_descriptor,
    template_materialize,
    template_service,
)
from document_skills_core.formats.pptx.constants import NS
from document_skills_core.formats.pptx.contact_sheet import decode_png
from document_skills_core.formats.pptx.mapping import map_slides
from document_skills_core.formats.pptx.mutation import MutablePptxPackage
from document_skills_core.formats.pptx.object_xml import object_hash, select_object
from document_skills_core.formats.pptx.package import OpcPackage, write_deterministic_zip
from document_skills_core.formats.pptx.presentation_contracts import (
    PresentationContractConsumer,
    _canonical_deck_hash,
)
from document_skills_core.formats.pptx.service import PptxService
from document_skills_core.formats.pptx.slide_graph import delete_slide, relationship_part_for
from document_skills_core.formats.pptx.template_purge import template_private_closure
from tests.fixtures.recipes.docx_fixture_support import PNG_1X1
from tests.support.pptx_template_fixture import build_semantic_template

_P_CNV_PR = f"{{{NS['p']}}}cNvPr"


def test_image_loader_uses_one_bounded_file_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "image.png"
    source.write_bytes(PNG_1X1)
    real_stat = Path.stat
    real_is_file = Path.is_file
    real_read_bytes = Path.read_bytes

    def reject_stat(path: Path, *args, **kwargs):
        if path == source:
            raise AssertionError("image loading must not stat before opening")
        return real_stat(path, *args, **kwargs)

    def reject_is_file(path: Path, *args, **kwargs):
        if path == source:
            raise AssertionError("image loading must inspect the open handle")
        return real_is_file(path, *args, **kwargs)

    def reject_read_bytes(path: Path, *args, **kwargs):
        if path == source:
            raise AssertionError("image loading must read from the inspected handle")
        return real_read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", reject_stat)
    monkeypatch.setattr(Path, "is_file", reject_is_file)
    monkeypatch.setattr(Path, "read_bytes", reject_read_bytes)

    image = pptx_image.load_pptx_image(
        {
            "path": source,
            "expected_sha256": sha256(PNG_1X1).hexdigest(),
        },
        1,
    )

    assert image["bytes"] == PNG_1X1
    assert image["sha256"] == sha256(PNG_1X1).hexdigest()


def test_descriptor_loader_uses_one_bounded_file_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'{"schemaVersion":"1.0"}'
    source = tmp_path / "descriptor.json"
    source.write_bytes(payload)
    real_stat = Path.stat
    real_is_file = Path.is_file
    real_read_bytes = Path.read_bytes

    def reject_stat(path: Path, *args, **kwargs):
        if path == source:
            raise AssertionError("descriptor loading must not stat before opening")
        return real_stat(path, *args, **kwargs)

    def reject_is_file(path: Path, *args, **kwargs):
        if path == source:
            raise AssertionError("descriptor loading must inspect the open handle")
        return real_is_file(path, *args, **kwargs)

    def reject_read_bytes(path: Path, *args, **kwargs):
        if path == source:
            raise AssertionError("descriptor loading must read from the inspected handle")
        return real_read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", reject_stat)
    monkeypatch.setattr(Path, "is_file", reject_is_file)
    monkeypatch.setattr(Path, "read_bytes", reject_read_bytes)

    value, record = template_descriptor._read_json_ref(
        {"path": source, "sha256": sha256(payload).hexdigest()},
        "deck_ir",
    )

    assert value == {"schemaVersion": "1.0"}
    assert record["bytes"] == len(payload)


def _inspect_request(fixture, *, mode: str = "strict") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": "pptx.template.inspect",
        "input": str(fixture.source),
        "arguments": {
            "catalog_ref": fixture.catalog_ref,
            "contact_sheet": False,
            "descriptor": fixture.descriptor,
            "expected_input_sha256": sha256(fixture.source.read_bytes()).hexdigest(),
            "mode": mode,
        },
    }


def _create_request(
    fixture,
    output: Path,
    pages: list[dict[str, object]],
    *,
    profile: str = "development",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": "pptx.create.from-template",
        "input": str(fixture.source),
        "output": str(output),
        "arguments": {
            "catalog_ref": fixture.catalog_ref,
            "delivery_profile": profile,
            "descriptor": fixture.descriptor,
            "expected_input_sha256": sha256(fixture.source.read_bytes()).hexdigest(),
            "pages": pages,
            "unbound_required_slot": "reject",
            "unselected_content": "physical_purge",
        },
    }


def _output_slide_id(template_id: str, key: str) -> str:
    deck_id = PresentationContractConsumer.stable_deck_id(
        namespace="elftia.hardening",
        source_template_id=template_id,
        source_template_version="1.0.0",
    )
    return PresentationContractConsumer.stable_slide_id(
        deck_id=deck_id,
        source_template_id=template_id,
        semantic_key=key,
    )


def _rewrite_template_contract(fixture, transform) -> dict[str, object]:
    reference = fixture.descriptor["template_contract"]
    path = Path(reference["path"])
    contract = json.loads(path.read_text(encoding="utf-8"))
    transform(contract)
    payload = (
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.write_bytes(payload)
    reference["sha256"] = sha256(payload).hexdigest()
    return contract


def _rewrite_descriptor_json(fixture, key: str, transform) -> dict[str, object]:
    reference = fixture.descriptor[key]
    path = Path(reference["path"])
    value = json.loads(path.read_text(encoding="utf-8"))
    transform(value)
    if key == "deck_ir":
        value["contentHash"] = _canonical_deck_hash(value)
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.write_bytes(payload)
    reference["sha256"] = sha256(payload).hexdigest()
    return value


def _sync_template_source_hash(fixture) -> str:
    source_hash = sha256(fixture.source.read_bytes()).hexdigest()
    _rewrite_template_contract(
        fixture,
        lambda contract: contract["assetRef"].update(
            {"sha256": f"sha256:{source_hash}"}
        ),
    )
    fixture.catalog_ref["sha256"] = f"sha256:{source_hash}"
    return source_hash


def _public_run(
    project_root: Path,
    request_path: Path,
    *,
    cwd: Path | None = None,
) -> dict[str, object]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-pptx/scripts/run.py"),
            "run",
            "--request",
            str(request_path),
        ],
        cwd=project_root if cwd is None else cwd,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=75,
    )
    assert process.returncode in {0, 2}, process.stderr.decode("utf-8", errors="replace")
    assert process.stderr == b""
    return json.loads(process.stdout.decode("utf-8", errors="strict"))


def test_descriptor_asset_hash_binds_source_without_caller_catalog(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root, slides=1)
    _rewrite_template_contract(
        fixture,
        lambda contract: contract["assetRef"].update({"sha256": "sha256:" + "0" * 64}),
    )
    request = _inspect_request(fixture)
    request["arguments"]["catalog_ref"] = None

    result = PptxService(project_root).execute("pptx.template.inspect", request)

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_STALE_PRECONDITION"


def test_tolerant_physical_drift_never_exposes_partial_writable_slots(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root)
    package = OpcPackage.open(fixture.source)
    parts = dict(package.parts)
    first_part, second_part = package.slide_parts()[:2]
    first = package.xml(first_part)
    second = package.xml(second_part)
    first_ids = [
        node for node in first.iter(_P_CNV_PR)
        if node.attrib.get("name", "").startswith("object_")
    ]
    second_ids = [
        node for node in second.iter(_P_CNV_PR)
        if node.attrib.get("name", "").startswith("object_")
    ]
    assert len(first_ids) >= 2 and second_ids
    first_ids[1].set("name", first_ids[0].attrib["name"])
    second_ids[0].set("name", "drifted-object")
    parts[first_part] = tostring(first, encoding="UTF-8", xml_declaration=True)
    parts[second_part] = tostring(second, encoding="UTF-8", xml_declaration=True)
    write_deterministic_zip(fixture.source, parts)
    source_hash = sha256(fixture.source.read_bytes()).hexdigest()
    _rewrite_template_contract(
        fixture,
        lambda contract: contract["assetRef"].update({"sha256": f"sha256:{source_hash}"}),
    )
    request = _inspect_request(fixture, mode="tolerant")
    request["arguments"]["catalog_ref"] = None

    result = PptxService(project_root).execute("pptx.template.inspect", request)

    assert result["status"] == "success", json.dumps(result, ensure_ascii=False, indent=2)
    operation = result["diagnostics"]["operation_result"]
    codes = {item["code"] for item in operation["descriptor"]["diagnostics"]}
    assert "stable-object-address-duplicate" in codes
    assert "semantic-slot-address-missing" in codes
    assert all(not page["semantic_slots"] for page in operation["pages"])


def test_commercial_profile_is_blocked_before_open_without_governance(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root, slides=1)
    _rewrite_template_contract(
        fixture,
        lambda contract: contract.update({
            "decisionRef": {
                "assetId": "semantic-neutral",
                "catalogId": "synthetic",
                "decisionId": "synthetic-commercial-allow",
                "policyVersion": "1.0.0",
                "profile": "commercial",
            },
            "licenseStatus": "allowed",
        }),
    )
    inspected = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )["diagnostics"]["operation_result"]
    slot = inspected["pages"][0]["semantic_slots"][0]
    page = {
        "source_slide_id": fixture.slide_ids[0],
        "output_slide_id": _output_slide_id("semantic-neutral", "commercial"),
        "bindings": [{
            "slot_id": slot["slot_id"],
            "expected_hash": slot["expected_hash"],
            "value": {"type": "text", "text": "Must remain blocked"},
        }],
    }
    output = tmp_path / "commercial.pptx"

    with monkeypatch.context() as context:
        context.setattr(
            template_materialize.OpcPackage,
            "open",
            lambda *_args, **_kwargs: pytest.fail("template package opened before license gate"),
        )
        result = PptxService(project_root).execute(
            "pptx.create.from-template",
            _create_request(fixture, output, [page], profile="commercial"),
        )

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_LICENSE_BLOCKED"
    assert not output.exists()


def test_malformed_table_binding_is_typed_invalid_request(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root)
    inspected = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )["diagnostics"]["operation_result"]
    slots = {item["kind"]: item for item in inspected["pages"][1]["semantic_slots"]}
    output = tmp_path / "malformed-table.pptx"
    page = {
        "source_slide_id": fixture.slide_ids[1],
        "output_slide_id": _output_slide_id("semantic-neutral", "bad-table"),
        "bindings": [
            {
                "slot_id": slots["text"]["slot_id"],
                "expected_hash": slots["text"]["expected_hash"],
                "value": {"type": "text", "text": "Valid title"},
            },
            {
                "slot_id": slots["table-data"]["slot_id"],
                "expected_hash": slots["table-data"]["expected_hash"],
                "value": {"type": "table-data", "rows": 42},
            },
        ],
    }

    result = PptxService(project_root).execute(
        "pptx.create.from-template",
        _create_request(fixture, output, [page]),
    )

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert not output.exists()


def test_png_decoder_rejects_decompression_bomb_with_bounded_output() -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    bomb = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\x00" + b"A" * 1_000_000))
        + chunk(b"IEND", b"")
    )

    with pytest.raises(DocumentSkillsError, match="scanline size"):
        decode_png(bomb)


def test_binding_receipt_hash_matches_final_output_object(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root, slides=1)
    inspected = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )["diagnostics"]["operation_result"]
    slot = inspected["pages"][0]["semantic_slots"][0]
    output = tmp_path / "receipt-hash.pptx"
    page = {
        "source_slide_id": fixture.slide_ids[0],
        "output_slide_id": _output_slide_id("semantic-neutral", "receipt-hash"),
        "bindings": [{
            "slot_id": slot["slot_id"],
            "expected_hash": slot["expected_hash"],
            "value": {"type": "text", "text": "Final identity hash"},
        }],
    }

    result = PptxService(project_root).execute(
        "pptx.create.from-template",
        _create_request(fixture, output, [page]),
    )

    assert result["status"] == "success", json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
    )
    operation = result["diagnostics"]["operation_result"]
    receipt = operation["binding_receipt"][0]
    mapping = next(
        item
        for item in operation["object_mapping"]
        if item["source_object_id"] == receipt["source_object_id"]
    )
    package = OpcPackage.open(output)
    slide_part = map_slides(package)[0]["part"]
    element = select_object(
        package.xml(slide_part),
        {"id": None, "name": mapping["output_object_id"], "type": None},
    )
    assert receipt["after_sha256"] == object_hash(element)
    assert operation["changed_objects"][0]["after_sha256"] == object_hash(element)


def test_unused_selected_relationship_cannot_rescue_unselected_private_media(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root, slides=2)
    package = OpcPackage.open(fixture.source)
    parts = dict(package.parts)
    selected_part, unselected_part = package.slide_parts()
    private_media = next(
        relationship.resolved_target
        for relationship in package.part_rels(unselected_part)
        if relationship.relationship_type.endswith("/image")
    )
    rels_part = relationship_part_for(selected_part)
    relationships = package.xml(rels_part)
    SubElement(
        relationships,
        f"{{{NS['rels']}}}Relationship",
        {
            "Id": "rIdUnusedLeak",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            "Target": posixpath.relpath(private_media, posixpath.dirname(selected_part)),
        },
    )
    parts[rels_part] = tostring(
        relationships,
        encoding="UTF-8",
        xml_declaration=True,
    )
    write_deterministic_zip(fixture.source, parts)
    _sync_template_source_hash(fixture)
    inspected = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )["diagnostics"]["operation_result"]
    slot = inspected["pages"][0]["semantic_slots"][0]
    output = tmp_path / "must-not-leak.pptx"
    page = {
        "source_slide_id": fixture.slide_ids[0],
        "output_slide_id": _output_slide_id("semantic-neutral", "purge-attack"),
        "bindings": [{
            "slot_id": slot["slot_id"],
            "expected_hash": slot["expected_hash"],
            "value": {"type": "text", "text": "Selected content only"},
        }],
    }

    result = PptxService(project_root).execute(
        "pptx.create.from-template",
        _create_request(fixture, output, [page]),
    )

    assert result["status"] == "failed", result
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert not output.exists()


def test_public_worker_resolves_relative_descriptor_and_binding_image_paths(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root)
    inspected = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )["diagnostics"]["operation_result"]
    slots = {item["kind"]: item for item in inspected["pages"][0]["semantic_slots"]}
    output = tmp_path / "relative-paths.pptx"
    page = {
        "source_slide_id": fixture.slide_ids[0],
        "output_slide_id": _output_slide_id("semantic-neutral", "relative-paths"),
        "bindings": [
            {
                "slot_id": slots["text"]["slot_id"],
                "expected_hash": slots["text"]["expected_hash"],
                "value": {"type": "text", "text": "Relative public paths"},
            },
            {
                "slot_id": slots["image-ref"]["slot_id"],
                "expected_hash": slots["image-ref"]["expected_hash"],
                "value": {
                    "type": "image-ref",
                    "path": "source-1.png",
                    "expected_sha256": sha256(
                        (tmp_path / "source-1.png").read_bytes()
                    ).hexdigest(),
                    "content_type": "image/png",
                    "fit": "contain",
                    "alt_text": "Relative image",
                },
            },
        ],
    }
    request = _create_request(fixture, output, [page])
    request["input"] = fixture.source.name
    request["output"] = output.name
    descriptor = request["arguments"]["descriptor"]
    contract_copy = tmp_path / "contract-root"
    shutil.copytree(Path(descriptor["contract_root"]), contract_copy)
    descriptor["contract_root"] = contract_copy.name
    for field in ("deck_ir", "semantic_slots", "template_contract"):
        descriptor[field]["path"] = Path(descriptor[field]["path"]).name
    request_path = tmp_path / "relative-request.json"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )

    result = _public_run(project_root, request_path, cwd=tmp_path)

    assert result["status"] == "success", json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
    )
    assert output.is_file()


def test_template_image_expected_sha256_rejects_changed_bytes(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root)
    inspected = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )["diagnostics"]["operation_result"]
    slots = {item["kind"]: item for item in inspected["pages"][0]["semantic_slots"]}
    output = tmp_path / "stale-image.pptx"
    page = {
        "source_slide_id": fixture.slide_ids[0],
        "output_slide_id": _output_slide_id("semantic-neutral", "stale-image"),
        "bindings": [
            {
                "slot_id": slots["text"]["slot_id"],
                "expected_hash": slots["text"]["expected_hash"],
                "value": {"type": "text", "text": "Stale image must fail"},
            },
            {
                "slot_id": slots["image-ref"]["slot_id"],
                "expected_hash": slots["image-ref"]["expected_hash"],
                "value": {
                    "type": "image-ref",
                    "path": str(tmp_path / "source-1.png"),
                    "expected_sha256": "0" * 64,
                    "content_type": "image/png",
                    "fit": "contain",
                    "alt_text": "Stale image",
                },
            },
        ],
    }

    result = PptxService(project_root).execute(
        "pptx.create.from-template",
        _create_request(fixture, output, [page]),
    )

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_STALE_PRECONDITION"
    assert not output.exists()


def test_template_images_have_an_aggregate_resource_budget(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root)
    inspected = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )["diagnostics"]["operation_result"]
    slots = {item["kind"]: item for item in inspected["pages"][0]["semantic_slots"]}
    output = tmp_path / "image-budget.pptx"
    page = {
        "source_slide_id": fixture.slide_ids[0],
        "output_slide_id": _output_slide_id("semantic-neutral", "image-budget"),
        "bindings": [
            {
                "slot_id": slots["text"]["slot_id"],
                "expected_hash": slots["text"]["expected_hash"],
                "value": {"type": "text", "text": "Bounded"},
            },
            {
                "slot_id": slots["image-ref"]["slot_id"],
                "expected_hash": slots["image-ref"]["expected_hash"],
                "value": {
                    "type": "image-ref",
                    "path": str(tmp_path / "source-1.png"),
                    "content_type": "image/png",
                    "fit": "contain",
                    "alt_text": "Budgeted image",
                },
            },
        ],
    }
    monkeypatch.setattr(template_materialize, "MAX_TOTAL_IMAGE_BYTES", 1)

    result = PptxService(project_root).execute(
        "pptx.create.from-template",
        _create_request(fixture, output, [page]),
    )

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_RESOURCE_LIMIT"
    assert not output.exists()


def test_repeated_page_dependency_budget_is_checked_before_copy(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root, slides=1)
    inspected = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )["diagnostics"]["operation_result"]
    slot = inspected["pages"][0]["semantic_slots"][0]
    source = OpcPackage.open(fixture.source)
    target = MutablePptxPackage(source)
    delete_slide(target, 1)
    private_parts = template_private_closure(source, source.slide_parts()[0])
    one_copy_limit = (
        sum(len(payload) for payload in target.parts.values())
        + sum(len(source.parts[item]) for item in private_parts if item in source.parts)
        + 1024 * sum(1 for item in private_parts if item.endswith(".rels"))
    )
    monkeypatch.setattr(template_materialize, "MAX_PPTX_BYTES", one_copy_limit)
    pages = [
        {
            "source_slide_id": fixture.slide_ids[0],
            "output_slide_id": _output_slide_id("semantic-neutral", f"repeat-{index}"),
            "bindings": [{
                "slot_id": slot["slot_id"],
                "expected_hash": slot["expected_hash"],
                "value": {"type": "text", "text": f"Repeat {index}"},
            }],
        }
        for index in range(2)
    ]
    output = tmp_path / "dependency-budget.pptx"

    result = PptxService(project_root).execute(
        "pptx.create.from-template",
        _create_request(fixture, output, pages),
    )

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_RESOURCE_LIMIT"
    assert not output.exists()


def test_repeated_slot_cardinality_counts_repeated_output_pages(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root, slides=1)
    _rewrite_descriptor_json(
        fixture,
        "semantic_slots",
        lambda slots: slots["slots"][0].update({
            "cardinality": {"kind": "repeated", "min": 2, "max": 2}
        }),
    )
    inspected = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )["diagnostics"]["operation_result"]
    slot = inspected["pages"][0]["semantic_slots"][0]
    assert slot["repeatable"] is True
    assert slot["required"] is True

    def page(index: int) -> dict[str, object]:
        return {
            "source_slide_id": fixture.slide_ids[0],
            "output_slide_id": _output_slide_id("semantic-neutral", f"cardinality-{index}"),
            "bindings": [{
                "slot_id": slot["slot_id"],
                "expected_hash": slot["expected_hash"],
                "value": {"type": "text", "text": f"Item {index}"},
            }],
        }

    rejected_output = tmp_path / "too-few.pptx"
    rejected = PptxService(project_root).execute(
        "pptx.create.from-template",
        _create_request(fixture, rejected_output, [page(1)]),
    )
    assert rejected["status"] == "failed"
    assert rejected["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert not rejected_output.exists()

    output = tmp_path / "repeated-cardinality.pptx"
    result = PptxService(project_root).execute(
        "pptx.create.from-template",
        _create_request(fixture, output, [page(1), page(2)]),
    )
    assert result["status"] == "success", result
    assert output.is_file()


def test_slot_and_source_object_key_collision_is_rejected(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root)
    slots = json.loads(
        Path(fixture.descriptor["semantic_slots"]["path"]).read_text(encoding="utf-8")
    )
    image_slot = next(item for item in slots["slots"] if item["dataType"] == "image-ref")
    colliding_key = image_slot["sourceObjectId"]

    def change_slots(value):
        value["slots"][0]["slotId"] = colliding_key
        value["slots"] = [
            item for item in value["slots"] if item["dataType"] != "image-ref"
        ]

    def change_deck(value):
        title, image = value["slides"][0]["objects"]
        title["slotBinding"]["slotId"] = colliding_key
        image.pop("slotBinding")

    _rewrite_descriptor_json(fixture, "semantic_slots", change_slots)
    _rewrite_descriptor_json(fixture, "deck_ir", change_deck)
    inspected = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )["diagnostics"]["operation_result"]
    slot = inspected["pages"][0]["semantic_slots"][0]
    output = tmp_path / "domain-separated.pptx"
    page = {
        "source_slide_id": fixture.slide_ids[0],
        "output_slide_id": _output_slide_id("semantic-neutral", "domain-separated"),
        "bindings": [{
            "slot_id": slot["slot_id"],
            "expected_hash": slot["expected_hash"],
            "value": {"type": "text", "text": "No collision"},
        }],
    }

    result = PptxService(project_root).execute(
        "pptx.create.from-template",
        _create_request(fixture, output, [page]),
    )

    assert result["status"] == "invalid_request", result
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert not output.exists()


def test_inspect_size_gate_runs_before_source_hashing(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "oversized.pptx"
    source.write_bytes(b"not-a-package")
    monkeypatch.setattr(pptx_package, "MAX_PPTX_BYTES", 4)
    monkeypatch.setattr(
        template_service,
        "file_record",
        lambda *_args, **_kwargs: pytest.fail("oversized input was hashed"),
    )
    request = {
        "schema_version": "1.0",
        "operation": "pptx.template.inspect",
        "input": str(source),
        "arguments": {"contact_sheet": False, "mode": "strict"},
    }

    result = PptxService(project_root).execute("pptx.template.inspect", request)

    assert result["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"
