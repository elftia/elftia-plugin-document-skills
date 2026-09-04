from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS
from types import SimpleNamespace

from document_skills_core.formats.pptx.contact_sheet import PngImage, decode_png, encode_png
from document_skills_core.formats.pptx.mapping import map_slides
from document_skills_core.formats.pptx.package import OpcPackage
from document_skills_core.formats.pptx.presentation_contracts import PresentationContractConsumer
from document_skills_core.formats.pptx.service import PptxService
from tests.support.pptx_template_fixture import build_semantic_template


class _VisualProvider:
    def detect(self) -> SimpleNamespace:
        return SimpleNamespace(available=True, version="synthetic-1")

    def try_render_to_image(self, _path: Path) -> bytes:
        return encode_png(PngImage(16, 9, bytes((32, 96, 192, 255)) * (16 * 9)))


def _inspect_request(fixture, *, contact_sheet: bool = False, output: Path | None = None):
    value = {
        "schema_version": "1.0",
        "operation": "pptx.template.inspect",
        "input": str(fixture.source),
        "arguments": {
            "catalog_ref": fixture.catalog_ref,
            "contact_sheet": contact_sheet,
            "descriptor": fixture.descriptor,
            "expected_input_sha256": sha256(fixture.source.read_bytes()).hexdigest(),
            "mode": "strict",
        },
    }
    if output is not None:
        value["output"] = str(output)
    return value


def _create_request(fixture, output: Path, pages: list[dict[str, object]]):
    return {
        "schema_version": "1.0",
        "operation": "pptx.create.from-template",
        "input": str(fixture.source),
        "output": str(output),
        "arguments": {
            "catalog_ref": fixture.catalog_ref,
            "delivery_profile": "development",
            "descriptor": fixture.descriptor,
            "expected_input_sha256": sha256(fixture.source.read_bytes()).hexdigest(),
            "pages": pages,
            "unbound_required_slot": "reject",
            "unselected_content": "physical_purge",
        },
    }


def _output_slide_id(fixture, key: str) -> str:
    deck_id = PresentationContractConsumer.stable_deck_id(
        namespace="elftia.output",
        source_template_id="semantic-neutral",
        source_template_version="1.0.0",
    )
    return PresentationContractConsumer.stable_slide_id(
        deck_id=deck_id,
        source_template_id="semantic-neutral",
        semantic_key=key,
    )


def _public_run(project_root: Path, request: Path) -> dict[str, object]:
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
            str(request),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=PUBLIC_CLI_TEST_TIMEOUT_SECONDS,
    )
    assert process.returncode in {0, 2}, process.stderr.decode("utf-8", errors="replace")
    assert process.stderr == b""
    return json.loads(process.stdout.decode("utf-8", errors="strict"))


def test_template_inspect_projects_a_contract_semantics(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root)
    result = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["descriptor"]["status"] == "passed"
    assert operation["catalog"]["hash_verification"] == "passed"
    assert operation["catalog"]["signature_verification"] == "not_provided"
    assert [item["source_slide_id"] for item in operation["pages"]] == list(fixture.slide_ids)
    assert [item["page_role"] for item in operation["pages"]] == ["cover", "content", "content"]
    for page, slot_id in zip(operation["pages"], fixture.slot_ids, strict=True):
        assert page["semantic_slots"][0]["slot_id"] == slot_id
        assert page["semantic_slots"][0]["stable_address"]["slide_id"] == page["source_slide_id"]
        assert len(page["semantic_slots"][0]["expected_hash"]) == 64
        assert page["layout"]["part"].startswith("ppt/slideLayouts/")
        assert page["master"]["part"].startswith("ppt/slideMasters/")
        assert page["theme"]["part"].startswith("ppt/theme/")
    typed = {
        slot["kind"]: slot
        for page in operation["pages"]
        for slot in page["semantic_slots"]
        if slot["kind"] != "text"
    }
    assert set(typed) == {"chart-data", "image-ref", "table-data"}
    assert all(item["stable_address"] is not None for item in typed.values())


def test_template_inspect_tolerates_bad_descriptor_only_as_diagnostics(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root)
    request = _inspect_request(fixture)
    request["arguments"]["mode"] = "tolerant"
    request["arguments"]["descriptor"]["deck_ir"]["sha256"] = "0" * 64
    request["arguments"]["catalog_ref"] = None

    result = PptxService(project_root).execute("pptx.template.inspect", request)

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["descriptor"]["status"] == "diagnostic_only"
    assert operation["descriptor"]["diagnostics"][0]["code"] == "DS_STALE_PRECONDITION"
    assert all(not page["semantic_slots"] for page in operation["pages"])


def test_template_contact_sheet_records_real_provider_regions(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root)
    output = tmp_path / "contact-sheet.png"
    result = PptxService(project_root, libreoffice=_VisualProvider()).execute(
        "pptx.template.inspect",
        _inspect_request(fixture, contact_sheet=True, output=output),
    )

    assert result["status"] == "success", result
    assert output.is_file()
    operation = result["diagnostics"]["operation_result"]
    contact = operation["contact_sheet"]
    assert contact["status"] == "passed"
    assert contact["slides"] == 3
    assert [item["slide"] for item in contact["regions"]] == [1, 2, 3]
    decoded = decode_png(output.read_bytes())
    assert (decoded.width, decoded.height) == (contact["width"], contact["height"])


def test_create_from_template_binds_slots_repeats_and_physically_purges(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root)
    inspected = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )["diagnostics"]["operation_result"]
    hashes = {
        page["source_slide_id"]: page["semantic_slots"][0]["expected_hash"]
        for page in inspected["pages"]
    }
    pages = [
        {
            "source_slide_id": fixture.slide_ids[2],
            "output_slide_id": _output_slide_id(fixture, "summary"),
            "bindings": [{
                "slot_id": fixture.slot_ids[2],
                "expected_hash": hashes[fixture.slide_ids[2]],
                "value": {"type": "text", "text": "总结结论"},
            }],
        },
        {
            "source_slide_id": fixture.slide_ids[0],
            "output_slide_id": _output_slide_id(fixture, "opening-a"),
            "bindings": [{
                "slot_id": fixture.slot_ids[0],
                "expected_hash": hashes[fixture.slide_ids[0]],
                "value": {"type": "text", "text": "第一次开场"},
            }],
        },
        {
            "source_slide_id": fixture.slide_ids[0],
            "output_slide_id": _output_slide_id(fixture, "opening-b"),
            "bindings": [{
                "slot_id": fixture.slot_ids[0],
                "expected_hash": hashes[fixture.slide_ids[0]],
                "value": {"type": "text", "text": "第二次开场"},
            }],
        },
    ]
    output = tmp_path / "materialized.pptx"
    result = PptxService(project_root).execute(
        "pptx.create.from-template",
        _create_request(fixture, output, pages),
    )

    assert result["status"] == "success", result
    assert output.is_file()
    operation = result["diagnostics"]["operation_result"]
    assert operation["physical_purge"]["private_parts_absent"] is True
    assert operation["physical_purge"]["unselected_slide_ids"] == [fixture.slide_ids[1]]
    assert operation["content_lint"]["postflight"]["status"] == "passed"
    assert len(operation["binding_receipt"]) == 3
    candidate = OpcPackage.open(output)
    assert [
        candidate.xml(item["part"]).find("{http://schemas.openxmlformats.org/presentationml/2006/main}cSld").attrib["name"]
        for item in map_slides(candidate)
    ] == [item["output_slide_id"] for item in pages]
    all_text = " ".join(
        node.text or ""
        for part in candidate.slide_parts()
        for node in candidate.xml(part).iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t")
    )
    assert "总结结论" in all_text and "第一次开场" in all_text and "第二次开场" in all_text
    assert "Template page 2" not in all_text
    source = OpcPackage.open(fixture.source)
    purged_hashes = {
        item["sha256"]
        for item in operation["purge_manifest"]["parts"]
        if not item["part"].endswith(".rels")
    }
    assert purged_hashes
    assert purged_hashes.isdisjoint(candidate.part_hashes.values())
    assert sha256(fixture.source.read_bytes()).hexdigest() == result["artifacts"][0]["sha256"]
    receipt = operation["delivery_receipt"]
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    assert receipt["receipt_sha256"] == sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def test_create_from_template_binds_image_table_and_chart_natively(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root)
    inspected = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )["diagnostics"]["operation_result"]
    hashes = {
        slot["slot_id"]: slot["expected_hash"]
        for page in inspected["pages"]
        for slot in page["semantic_slots"]
    }
    replacement = tmp_path / "replacement.png"
    replacement.write_bytes(encode_png(PngImage(4, 3, bytes((220, 80, 60, 255)) * 12)))
    typed_values = {
        "image-ref": {
            "type": "image-ref",
            "path": str(replacement),
            "content_type": "image/png",
            "fit": "contain",
            "alt_text": "Replacement image",
        },
        "table-data": {
            "type": "table-data",
            "rows": [["指标", "数值"], ["增长", "42"]],
        },
        "chart-data": {
            "type": "chart-data",
            "chart": {
                "title": "Updated chart",
                "chart_type": "column",
                "categories": ["A", "B"],
                "series": [{"name": "Value", "values": [8, 13]}],
                "legend": {"show": False, "position": "right"},
                "axes": {
                    "category": {"title": "Category", "number_format": "General"},
                    "value": {"title": "Value", "number_format": "0"},
                },
                "data_labels": {"show_value": True},
                "colors": ["CC5533"],
            },
        },
    }
    typed_for_slide = {0: "image-ref", 1: "table-data", 2: "chart-data"}
    pages = []
    for index, source_slide_id in enumerate(fixture.slide_ids):
        bindings = [{
            "slot_id": fixture.slot_ids[index],
            "expected_hash": hashes[fixture.slot_ids[index]],
            "value": {"type": "text", "text": f"Bound page {index + 1}"},
        }]
        data_type = typed_for_slide[index]
        slot_id = fixture.typed_slot_ids[data_type]
        bindings.append({
            "slot_id": slot_id,
            "expected_hash": hashes[slot_id],
            "value": typed_values[data_type],
        })
        pages.append({
            "source_slide_id": source_slide_id,
            "output_slide_id": _output_slide_id(fixture, f"typed-{index + 1}"),
            "bindings": bindings,
        })
    output = tmp_path / "typed-materialized.pptx"
    result = PptxService(project_root).execute(
        "pptx.create.from-template",
        _create_request(fixture, output, pages),
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    typed_receipts = {
        item["value_type"]: item for item in operation["binding_receipt"]
        if item["value_type"] != "text"
    }
    assert set(typed_receipts) == {"chart-data", "image-ref", "table-data"}
    assert all(item["outcome"] == "native" for item in typed_receipts.values())
    candidate = OpcPackage.open(output)
    assert sha256(replacement.read_bytes()).hexdigest() in candidate.part_hashes.values()
    text = " ".join(
        node.text or ""
        for part in candidate.slide_parts()
        for node in candidate.xml(part).iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t")
    )
    assert "指标" in text and "42" in text
    chart_text = b"".join(candidate.parts[part] for part in candidate.chart_parts())
    assert b"Updated chart" in chart_text and b"13" in chart_text


def test_create_from_template_rejects_stale_and_unbound_requests_without_output(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root, slides=1)
    inspected = PptxService(project_root).execute(
        "pptx.template.inspect",
        _inspect_request(fixture),
    )["diagnostics"]["operation_result"]
    expected = inspected["pages"][0]["semantic_slots"][0]["expected_hash"]
    output = tmp_path / "rejected.pptx"
    page = {
        "source_slide_id": fixture.slide_ids[0],
        "output_slide_id": _output_slide_id(fixture, "rejected"),
        "bindings": [{
            "slot_id": fixture.slot_ids[0],
            "expected_hash": "0" * 64,
            "value": {"type": "text", "text": "Rejected"},
        }],
    }
    stale = PptxService(project_root).execute(
        "pptx.create.from-template",
        _create_request(fixture, output, [page]),
    )
    assert stale["status"] == "invalid_request"
    assert stale["errors"][0]["code"] == "DS_STALE_PRECONDITION"
    assert not output.exists()

    page["bindings"] = []
    unbound = PptxService(project_root).execute(
        "pptx.create.from-template",
        _create_request(fixture, output, [page]),
    )
    assert unbound["status"] == "failed"
    assert unbound["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert not output.exists()
    assert expected != "0" * 64


def test_public_template_inspect_and_create_truth(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root, slides=1)
    inspect_path = tmp_path / "inspect-request.json"
    inspect_path.write_text(
        json.dumps(_inspect_request(fixture), ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    inspected = _public_run(project_root, inspect_path)
    assert inspected["status"] == "success", inspected
    assert inspected["provider_chain"] == ["core-python"]
    operation = inspected["diagnostics"]["operation_result"]
    expected_hash = operation["pages"][0]["semantic_slots"][0]["expected_hash"]

    output = tmp_path / "public-materialized.pptx"
    page = {
        "source_slide_id": fixture.slide_ids[0],
        "output_slide_id": _output_slide_id(fixture, "public-output"),
        "bindings": [{
            "slot_id": fixture.slot_ids[0],
            "expected_hash": expected_hash,
            "value": {"type": "text", "text": "Public semantic binding"},
        }],
    }
    create_path = tmp_path / "create-request.json"
    create_path.write_text(
        json.dumps(_create_request(fixture, output, [page]), ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    created = _public_run(project_root, create_path)
    assert created["status"] == "success", created
    assert created["provider_chain"] == ["core-python"]
    assert output.is_file()
    created_operation = created["diagnostics"]["operation_result"]
    assert created_operation["physical_purge"]["private_parts_absent"] is True
    assert created_operation["consumer"]["powerpoint"]["status"] == "not_run"
    assert created_operation["visual"]["status"] == "not_run"


def test_public_template_negative_security_resource_and_provider_truth(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixture = build_semantic_template(tmp_path, project_root, slides=1)
    output = tmp_path / "must-not-exist.pptx"
    stale_page = {
        "source_slide_id": fixture.slide_ids[0],
        "output_slide_id": _output_slide_id(fixture, "stale-public"),
        "bindings": [{
            "slot_id": fixture.slot_ids[0],
            "expected_hash": "0" * 64,
            "value": {"type": "text", "text": "Rejected"},
        }],
    }
    stale_request = tmp_path / "stale-public.json"
    stale_request.write_text(
        json.dumps(_create_request(fixture, output, [stale_page]), ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    stale = _public_run(project_root, stale_request)
    assert stale["status"] == "invalid_request"
    assert stale["errors"][0]["code"] == "DS_STALE_PRECONDITION"
    assert not output.exists()

    dangerous = project_root / "tests/fixtures/pptx/ecosystem_bc/templates/external-and-ole.pptx"
    contact_output = tmp_path / "dangerous-contact.png"
    dangerous_request = tmp_path / "dangerous-inspect.json"
    dangerous_request.write_text(
        json.dumps({
            "schema_version": "1.0",
            "operation": "pptx.template.inspect",
            "input": str(dangerous),
            "output": str(contact_output),
            "arguments": {"contact_sheet": True, "mode": "strict"},
        }),
        encoding="utf-8",
        newline="\n",
    )
    security = _public_run(project_root, dangerous_request)
    assert security["status"] == "degraded", security
    security_operation = security["diagnostics"]["operation_result"]
    assert security_operation["dangerous_content"]["present"] is True
    assert security_operation["contact_sheet"]["status"] == "unavailable"
    assert security_operation["contact_sheet"]["reason"] == "dangerous-input-not-opened-by-visual-provider"
    assert not contact_output.exists()

    oversized = tmp_path / "oversized-deck-ir.json"
    oversized.write_bytes(b"{" + b" " * 4_194_304 + b"}")
    descriptor = dict(fixture.descriptor)
    descriptor["deck_ir"] = {
        "path": str(oversized),
        "sha256": sha256(oversized.read_bytes()).hexdigest(),
    }
    resource_request = tmp_path / "resource-inspect.json"
    resource_request.write_text(
        json.dumps({
            "schema_version": "1.0",
            "operation": "pptx.template.inspect",
            "input": str(fixture.source),
            "arguments": {
                "contact_sheet": False,
                "descriptor": descriptor,
                "mode": "strict",
            },
        }),
        encoding="utf-8",
        newline="\n",
    )
    resource = _public_run(project_root, resource_request)
    assert resource["status"] == "invalid_request"
    assert resource["errors"][0]["code"] == "DS_RESOURCE_LIMIT"
