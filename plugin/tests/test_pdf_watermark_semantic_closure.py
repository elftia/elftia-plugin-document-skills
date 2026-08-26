"""Adversarial closure regressions for PDF watermark promotion."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re
from typing import Any, Callable

from PIL import Image
import pytest

from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.edit import _build_manifest
from document_skills_core.formats.pdf.object_model import parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages
from document_skills_core.formats.pdf import service as service_module
from document_skills_core.formats.pdf.service import PdfService
from document_skills_core.formats.pdf.watermark_fonts import (
    watermark_font_object_sha256,
)
from document_skills_core.formats.pdf.watermark_objects import stream_object_payload
from document_skills_core.formats.pdf.watermark_scan import scan_watermark_uses


Tamper = Callable[[Path, dict[str, Any]], None]


@pytest.mark.parametrize("tamper_kind", ["size", "color", "matrix", "text-render"])
def test_text_watermark_canonical_stream_tamper_rolls_back(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper_kind: str,
) -> None:
    def tamper(candidate: Path, report: dict[str, Any]) -> None:
        content_object = report["watermark_uses"][0]["content_object"]
        if tamper_kind == "text-render":
            _inject_stream_operator(candidate, content_object, b"3 Tr\n")
            return
        payload = parse_pdf(candidate).objects[content_object].payload_bytes
        replacements = {
            "size": (b" 48 Tf", b" 49 Tf"),
            "color": (b"0.7 0.7 0.7 rg", b"0.8 0.7 0.7 rg"),
            "matrix": (b"0.707107 0.707107", b"0.807107 0.707107"),
        }
        before, after = replacements[tamper_kind]
        changed = payload.replace(before, after, 1)
        assert changed != payload and len(changed) == len(payload)
        candidate.write_bytes(candidate.read_bytes().replace(payload, changed, 1))

    _assert_tamper_rolls_back(
        project_root,
        tmp_path,
        monkeypatch,
        _text_primitive(),
        tamper,
    )


@pytest.mark.parametrize("field", ["size", "color", "rotation", "position"])
def test_text_watermark_report_lie_rolls_back(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    lies: dict[str, object] = {
        "size": 47.0,
        "color": [0.1, 0.2, 0.3],
        "rotation": 12.0,
        "position": "top-left",
    }

    def tamper(_candidate: Path, report: dict[str, Any]) -> None:
        report[field] = lies[field]

    _assert_tamper_rolls_back(
        project_root,
        tmp_path,
        monkeypatch,
        _text_primitive(),
        tamper,
    )


@pytest.mark.parametrize(
    "target",
    ["content-dict", "extgstate", "font", "image", "smask", "alt"],
)
def test_watermark_closed_resource_dictionary_tamper_rolls_back(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    image = _rgba_png(tmp_path / "alpha.png")
    primitive = (
        _image_primitive(image)
        if target in {"image", "smask", "alt"}
        else _text_primitive()
    )

    def tamper(candidate: Path, report: dict[str, Any]) -> None:
        if target == "content-dict":
            _inject_dictionary_entry(
                candidate,
                report["watermark_uses"][0]["content_object"],
                b" /DecodeParms << /Predictor 1 >>",
            )
        elif target == "extgstate":
            raw = candidate.read_bytes()
            marker = raw.index(b"/Type /ExtGState")
            _insert_raw(candidate, raw.index(b">>", marker), b" /BM /Difference")
        elif target == "font":
            font_object = report["watermark_uses"][0]["font_object"]
            _inject_dictionary_entry(
                candidate,
                font_object,
                b" /FontMatrix [1 0 0 1 0 0]",
            )
        elif target == "image":
            _inject_dictionary_entry(
                candidate,
                report["image"]["image_object"],
                b" /Mask [0 1]",
            )
        elif target == "smask":
            _inject_dictionary_entry(
                candidate,
                report["image"]["soft_mask"]["object"],
                b" /Matte [0 0 0]",
            )
        else:
            raw = candidate.read_bytes()
            changed = raw.replace(b"/Alt (alpha)", b"/Alt (omega)", 1)
            assert changed != raw and len(changed) == len(raw)
            candidate.write_bytes(changed)

    _assert_tamper_rolls_back(
        project_root,
        tmp_path,
        monkeypatch,
        primitive,
        tamper,
    )


@pytest.mark.parametrize("target", ["content", "image", "smask"])
def test_watermark_reference_generation_tamper_rolls_back(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    image = _rgba_png(tmp_path / "generation.png")

    def tamper(candidate: Path, report: dict[str, Any]) -> None:
        object_number = {
            "content": report["watermark_uses"][0]["content_object"],
            "image": report["image"]["image_object"],
            "smask": report["image"]["soft_mask"]["object"],
        }[target]
        raw = candidate.read_bytes()
        before = f"{object_number} 0 R".encode("ascii")
        after = f"{object_number} 1 R".encode("ascii")
        changed = raw.replace(before, after, 1)
        assert changed != raw and len(changed) == len(raw)
        candidate.write_bytes(changed)

    _assert_tamper_rolls_back(
        project_root,
        tmp_path,
        monkeypatch,
        _image_primitive(image),
        tamper,
    )


@pytest.mark.parametrize(
    "tamper_kind",
    [
        "extra-page",
        "extra-record",
        "added-list",
        "content-generation",
        "content-digest",
        "image-generation",
        "image-stream-digest",
        "smask-generation",
        "image-page-bboxes",
    ],
)
def test_watermark_writer_evidence_must_be_exactly_consumed(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper_kind: str,
) -> None:
    image = _rgba_png(tmp_path / "evidence.png")

    def tamper(_candidate: Path, report: dict[str, Any]) -> None:
        if tamper_kind == "extra-page":
            report["pages"].append(2)
        elif tamper_kind == "extra-record":
            fake = deepcopy(report["watermark_uses"][0])
            fake["page"] = 2
            report["watermark_uses"].append(fake)
        elif tamper_kind == "added-list":
            report["added_objects"].append(999_999)
        elif tamper_kind == "content-generation":
            report["watermark_uses"][0]["content_object_generation"] = 1
        elif tamper_kind == "content-digest":
            report["watermark_uses"][0]["content_stream_sha256"] = "0" * 64
        elif tamper_kind == "image-generation":
            report["image"]["image_object_generation"] = 1
        elif tamper_kind == "image-stream-digest":
            report["watermark_uses"][0]["stream_sha256"] = "0" * 64
        elif tamper_kind == "smask-generation":
            report["image"]["soft_mask"]["object_generation"] = 1
        else:
            report["image"]["page_bboxes"] = deepcopy(
                report["image"]["page_bboxes"]
            )
            report["image"]["page_bboxes"][0]["bbox"][0] += 1.0

    _assert_tamper_rolls_back(
        project_root,
        tmp_path,
        monkeypatch,
        _image_primitive(image),
        tamper,
        page_count=2,
    )


def test_image_watermark_cannot_borrow_old_main_or_alpha_objects(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clean = tmp_path / "clean.pdf"
    source = tmp_path / "old-watermark.pdf"
    destination = tmp_path / "destination.pdf"
    image = _rgba_png(tmp_path / "borrow.png")
    primitive = _image_primitive(image)
    create_pdf(clean, _document(1))
    first = PdfService(project_root).execute(
        "pdf.edit",
        _request(clean, source, primitive),
    )
    assert first["status"] == "success", first
    old_evidence = first["diagnostics"]["operation_result"]["image"]
    old_use = scan_watermark_uses(parse_pdf(source), walk_pages(parse_pdf(source))[0])[0]
    real_edit = service_module.edit_pdf
    destination.write_bytes(b"preserve destination")

    def tampered_edit(
        input_path: Path,
        output_path: Path,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        operation, manifest = real_edit(input_path, output_path, arguments)
        new_object = operation["image"]["image_object"]
        raw = output_path.read_bytes()
        before = f"/DSWMImage1 {new_object} 0 R".encode("ascii")
        after = f"/DSWMImage1 {old_use.image_object} 0 R".encode("ascii")
        assert len(before) == len(after)
        changed = raw.replace(before, after, 1)
        assert changed != raw
        output_path.write_bytes(changed)
        operation["image"]["image_object"] = old_evidence["image_object"]
        operation["image"]["image_object_generation"] = old_evidence[
            "image_object_generation"
        ]
        operation["image"]["image_object_sha256"] = old_evidence[
            "image_object_sha256"
        ]
        operation["image"]["soft_mask"] = deepcopy(old_evidence["soft_mask"])
        operation["watermark_uses"][0]["image_object"] = old_evidence[
            "image_object"
        ]
        return operation, _rebound_manifest(input_path, output_path, manifest)

    monkeypatch.setattr(service_module, "edit_pdf", tampered_edit)
    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(source, destination, primitive),
    )
    _assert_failed_without_promotion(result, destination)


def test_image_primitives_cannot_borrow_each_others_objects(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    image = _rgba_png(tmp_path / "same.png")
    primitive = _image_primitive(image)
    create_pdf(source, _document(1))
    destination.write_bytes(b"preserve destination")
    real_edit = service_module.edit_pdf

    def tampered_edit(
        input_path: Path,
        output_path: Path,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        operation, manifest = real_edit(input_path, output_path, arguments)
        first, second = operation["primitives"]
        first_image = first["image"]
        second_image = second["image"]
        raw = output_path.read_bytes()
        before = (
            f"/DSWMImage1 {second_image['image_object']} 0 R".encode("ascii")
        )
        after = f"/DSWMImage1 {first_image['image_object']} 0 R".encode("ascii")
        assert len(before) == len(after)
        changed = raw.replace(before, after, 1)
        assert changed != raw
        output_path.write_bytes(changed)
        for key in (
            "image_object",
            "image_object_generation",
            "image_object_sha256",
        ):
            second_image[key] = deepcopy(first_image[key])
        second_image["soft_mask"] = deepcopy(first_image["soft_mask"])
        second["watermark_uses"][0]["image_object"] = first_image[
            "image_object"
        ]
        borrowed = {
            first_image["image_object"],
            first_image["soft_mask"]["object"],
        }
        expanded = sorted(set(second["added_objects"]) | borrowed)
        second["added_objects"][:] = expanded
        second["preservation"]["added_objects"][:] = expanded
        return operation, _rebound_manifest(input_path, output_path, manifest)

    monkeypatch.setattr(service_module, "edit_pdf", tampered_edit)
    result = PdfService(project_root).execute(
        "pdf.edit",
        {
            **_request(source, destination, primitive),
            "arguments": {"primitives": [primitive, deepcopy(primitive)]},
        },
    )
    _assert_failed_without_promotion(result, destination)


def test_watermark_pages_cannot_share_one_new_content_object(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    create_pdf(source, _document(2))
    destination.write_bytes(b"preserve destination")
    primitive = _text_primitive()
    primitive["pages"] = [1, 2]
    real_edit = service_module.edit_pdf

    def tampered_edit(
        input_path: Path,
        output_path: Path,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        operation, manifest = real_edit(input_path, output_path, arguments)
        first, second = operation["watermark_uses"]
        raw = output_path.read_bytes()
        before = f"{second['content_object']} 0 R".encode("ascii")
        after = f"{first['content_object']} 0 R".encode("ascii")
        assert len(before) == len(after)
        changed = raw.replace(before, after, 1)
        assert changed != raw
        output_path.write_bytes(changed)
        for key in (
            "content_object",
            "content_object_generation",
            "content_object_sha256",
            "content_stream_sha256",
            "content_keys",
            "content_length",
            "content_filter",
            "content_decode_parms",
        ):
            second[key] = deepcopy(first[key])
        return operation, _rebound_manifest(input_path, output_path, manifest)

    monkeypatch.setattr(service_module, "edit_pdf", tampered_edit)
    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(source, destination, primitive),
    )
    _assert_failed_without_promotion(result, destination)


def test_identity_replacement_report_cannot_swap_content_and_font_roles(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    create_pdf(source, _document(1))
    destination.write_bytes(b"preserve destination")
    real_edit = service_module.edit_pdf

    def tampered_edit(
        input_path: Path,
        output_path: Path,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        operation, manifest = real_edit(input_path, output_path, arguments)
        record = operation["primitives"][0]["watermark_uses"][0]
        for content_key, font_key in (
            ("content_object", "font_object"),
            ("content_object_generation", "font_object_generation"),
            ("content_object_sha256", "font_object_sha256"),
        ):
            record[content_key], record[font_key] = (
                record[font_key],
                record[content_key],
            )
        final_model = parse_pdf(output_path)
        final_use = scan_watermark_uses(
            final_model,
            walk_pages(final_model)[0],
        )[0]
        final_content = final_model.objects[final_use.content_object].value
        assert isinstance(final_content, tuple)
        content_stream = final_content[1]
        content_object = record["content_object"]
        content_digest = sha256(stream_object_payload(
            content_object,
            f"<< /Length {len(content_stream)} >>".encode("ascii"),
            content_stream,
        )).hexdigest()
        font_object = record["font_object"]
        font_digest = watermark_font_object_sha256(font_object, "Helvetica")
        record["content_object_sha256"] = content_digest
        record["font_object_sha256"] = font_digest
        stage_hashes = operation["primitives"][0]["preservation"][
            "expected_output_hashes"
        ]
        stage_hashes[str(content_object)] = content_digest
        stage_hashes[str(font_object)] = font_digest
        return operation, manifest

    monkeypatch.setattr(service_module, "edit_pdf", tampered_edit)
    request = _request(source, destination, _text_primitive())
    request["arguments"]["primitives"].append({
        "type": "page_sequence",
        "pages": [1],
    })
    result = PdfService(project_root).execute("pdf.edit", request)
    _assert_failed_without_promotion(result, destination)


def test_identity_replacement_report_cannot_swap_image_and_mask_roles(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    image = _rgba_png(tmp_path / "identity-alpha.png")
    create_pdf(source, _document(1))
    destination.write_bytes(b"preserve destination")
    real_edit = service_module.edit_pdf

    def tampered_edit(
        input_path: Path,
        output_path: Path,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        operation, manifest = real_edit(input_path, output_path, arguments)
        report = operation["primitives"][0]
        evidence = report["image"]
        soft_mask = evidence["soft_mask"]
        for image_key, mask_key in (
            ("image_object", "object"),
            ("image_object_generation", "object_generation"),
            ("image_object_sha256", "object_sha256"),
        ):
            evidence[image_key], soft_mask[mask_key] = (
                soft_mask[mask_key],
                evidence[image_key],
            )
        report["watermark_uses"][0]["image_object"] = evidence[
            "image_object"
        ]
        return operation, manifest

    monkeypatch.setattr(service_module, "edit_pdf", tampered_edit)
    request = _request(source, destination, _image_primitive(image))
    request["arguments"]["primitives"].append({
        "type": "page_sequence",
        "pages": [1],
    })
    result = PdfService(project_root).execute("pdf.edit", request)
    _assert_failed_without_promotion(result, destination)


def test_report_cannot_invent_identity_replacement_mode(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    create_pdf(source, _document(1))
    destination.write_bytes(b"preserve destination")
    real_edit = service_module.edit_pdf

    def tampered_edit(
        input_path: Path,
        output_path: Path,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        operation, manifest = real_edit(input_path, output_path, arguments)
        operation["primitives"][1]["primitive"] = "page_sequence"
        return operation, manifest

    monkeypatch.setattr(service_module, "edit_pdf", tampered_edit)
    request = _request(source, destination, _text_primitive())
    request["arguments"]["primitives"].append({
        "type": "rotate",
        "pages": [1],
        "degrees": 90,
    })
    result = PdfService(project_root).execute("pdf.edit", request)
    _assert_failed_without_promotion(result, destination)


def test_watermark_writer_preserves_source_generations_and_free_gaps(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _generation_gap_pdf(tmp_path / "generation-gap.pdf")
    destination = tmp_path / "destination.pdf"
    source_model = parse_pdf(source)
    source_content_hash = source_model.objects[4].sha256

    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(source, destination, _text_primitive()),
    )

    assert result["status"] == "success", result
    output = parse_pdf(destination)
    page = walk_pages(output)[0]
    assert page.contents[0].obj_num == 4
    assert page.contents[0].gen_num == 2
    assert output.objects[4].gen_num == 2
    assert output.objects[4].sha256 == source_content_hash
    assert output.xref_entries[4].gen_num == 2
    assert output.xref_entries[4].in_use is True
    assert output.xref_entries[5].in_use is False
    assert output.xref_entries[6].in_use is False
    assert len(scan_watermark_uses(output, page)) == 1


def _assert_tamper_rolls_back(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    primitive: dict[str, Any],
    tamper: Tamper,
    *,
    page_count: int = 1,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    create_pdf(source, _document(page_count))
    destination.write_bytes(b"preserve destination")
    real_edit = service_module.edit_pdf

    def tampered_edit(
        input_path: Path,
        output_path: Path,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        operation, manifest = real_edit(input_path, output_path, arguments)
        tamper(output_path, operation)
        return operation, _rebound_manifest(input_path, output_path, manifest)

    monkeypatch.setattr(service_module, "edit_pdf", tampered_edit)
    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(source, destination, primitive),
    )
    _assert_failed_without_promotion(result, destination)


def _assert_failed_without_promotion(result: dict[str, Any], output: Path) -> None:
    assert result["status"] == "failed", result
    assert result["errors"][0]["details"]["failed_gates"] == [
        "operation.mutation-semantics"
    ]
    assert output.read_bytes() == b"preserve destination"


def _inject_dictionary_entry(candidate: Path, object_number: int, addition: bytes) -> None:
    raw = candidate.read_bytes()
    object_start = raw.index(f"{object_number} 0 obj\n".encode("ascii"))
    stream_start = raw.find(b"\nstream\n", object_start)
    search_end = stream_start if stream_start >= 0 else raw.index(b"\nendobj", object_start)
    dictionary_end = raw.rfind(b">>", object_start, search_end)
    assert dictionary_end > object_start
    _insert_raw(candidate, dictionary_end, addition)


def _inject_stream_operator(candidate: Path, object_number: int, addition: bytes) -> None:
    raw = candidate.read_bytes()
    object_start = raw.index(f"{object_number} 0 obj\n".encode("ascii"))
    stream_marker = raw.index(b"\nstream\n", object_start)
    stream_start = stream_marker + len(b"\nstream\n")
    old_length = parse_pdf(candidate).objects[object_number].value[0].get("/Length")
    before = f"/Length {old_length}".encode("ascii")
    after = f"/Length {old_length + len(addition)}".encode("ascii")
    assert len(before) == len(after)
    prefix = raw[:stream_marker].replace(before, after, 1)
    candidate.write_bytes(prefix + raw[stream_marker:])
    insert_at = candidate.read_bytes().index(b"BT\n", stream_start) + len(b"BT\n")
    _insert_raw(candidate, insert_at, addition)


def _insert_raw(candidate: Path, position: int, addition: bytes) -> None:
    raw = candidate.read_bytes()
    startxref = re.search(rb"startxref\s+([0-9]+)", raw)
    assert startxref is not None
    old_xref = int(startxref.group(1))
    assert position < old_xref and raw[old_xref : old_xref + 5] == b"xref\n"
    delta = len(addition)
    tail = raw[old_xref:]

    def shifted_entry(match: re.Match[bytes]) -> bytes:
        offset = int(match.group(1))
        if offset >= position:
            offset += delta
        return f"{offset:010d}".encode("ascii") + match.group(2)

    tail = re.sub(
        rb"(?m)^([0-9]{10})( [0-9]{5} [nf]\r?)$",
        shifted_entry,
        tail,
    )
    tail = tail.replace(
        f"startxref\n{old_xref}\n".encode("ascii"),
        f"startxref\n{old_xref + delta}\n".encode("ascii"),
        1,
    )
    candidate.write_bytes(raw[:position] + addition + raw[position:old_xref] + tail)


def _rebound_manifest(
    source: Path,
    candidate: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    return _build_manifest(
        parse_pdf(source).object_hashes(),
        parse_pdf(candidate).object_hashes(),
        changed=set(manifest["changed_objects"]),
        added=set(manifest["added_objects"]),
        removed=set(manifest["removed_objects"]),
    )


def _rgba_png(path: Path) -> Path:
    Image.new("RGBA", (2, 1), (30, 90, 180, 120)).save(path, format="PNG")
    return path


def _generation_gap_pdf(path: Path) -> Path:
    content = b"q\nQ\n"
    objects = {
        1: b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj",
        2: b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj",
        3: (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R "
            b"/MediaBox [0 0 300 200] /Resources << >> /Contents 4 2 R >>\nendobj"
        ),
        4: (
            f"4 2 obj\n<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"endstream\nendobj"
        ),
    }
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: dict[int, int] = {}
    for object_number in sorted(objects):
        offsets[object_number] = len(header) + len(body)
        body.extend(objects[object_number] + b"\n")
    xref_offset = len(header) + len(body)
    xref = bytearray(b"xref\n0 7\n0000000005 65535 f\r\n")
    for object_number in (1, 2, 3):
        xref.extend(f"{offsets[object_number]:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(f"{offsets[4]:010d} 00002 n\r\n".encode("ascii"))
    xref.extend(b"0000000006 00000 f\r\n0000000000 00000 f\r\n")
    xref.extend(
        f"trailer\n<< /Size 7 /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


def _text_primitive() -> dict[str, Any]:
    return {
        "type": "watermark",
        "text": "CANONICAL",
        "pages": [1],
        "opacity": 0.35,
    }


def _image_primitive(path: Path) -> dict[str, Any]:
    return {
        "type": "watermark",
        "image": {
            "filename": str(path),
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "content_type": "image/png",
            "fit": "contain",
            "width": 80,
            "height": 40,
            "alt": path.stem,
        },
        "pages": [1],
        "opacity": 0.4,
    }


def _request(source: Path, output: Path, primitive: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "pdf.edit",
        "input": str(source),
        "output": str(output),
        "arguments": {"primitives": [primitive]},
    }


def _document(page_count: int) -> dict[str, Any]:
    return {
        "metadata": {"title": "Watermark closure", "author": "Elftia"},
        "page_size": "A4",
        "pages": [
            {
                "blocks": [{
                    "type": "paragraph",
                    "text": f"Page {number}",
                    "style": None,
                    "table": None,
                    "image": None,
                    "shape": None,
                }],
                "metadata": None,
            }
            for number in range(1, page_count + 1)
        ],
    }
