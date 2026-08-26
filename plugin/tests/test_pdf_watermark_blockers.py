"""Public regressions for watermark copy-on-write and semantic binding."""

from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from PIL import Image
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from document_skills_core.formats.pdf.content_streams import extract_content_stream
from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.edit import _build_manifest
from document_skills_core.formats.pdf.object_model import parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages
from document_skills_core.formats.pdf import service as service_module
from document_skills_core.formats.pdf.service import PdfService
from document_skills_core.formats.pdf.watermark_scan import scan_watermark_uses


def test_public_watermark_copy_on_writes_a_shared_content_stream(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _shared_content_pdf(tmp_path / "shared.pdf")
    destination = tmp_path / "watermarked.pdf"
    source_model = parse_pdf(source)
    source_pages = walk_pages(source_model)
    shared = source_pages[0].contents[0]
    assert source_pages[1].contents == [shared]

    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(source, destination, [{
            "type": "watermark",
            "text": "PAGE ONE ONLY",
            "pages": [1],
            "opacity": 0.35,
        }]),
    )

    assert result["status"] == "success", result
    output_model = parse_pdf(destination)
    output_pages = walk_pages(output_model)
    assert output_pages[0].contents[0] == shared
    assert len(output_pages[0].contents) == 2
    assert output_pages[1].contents == [shared]
    assert output_model.objects[shared.obj_num].sha256 == source_model.objects[
        shared.obj_num
    ].sha256
    page_two = extract_content_stream(
        output_model,
        output_pages[1].contents,
        2,
    )
    assert b"PAGE ONE ONLY" not in page_two
    operation = result["diagnostics"]["operation_result"]
    assert operation["changed_objects"] == [output_pages[0].obj_num]
    assert shared.obj_num in operation["preservation"]["preserved_objects"]


def test_public_two_image_watermarks_keep_distinct_assets_and_resources(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "two-images.pdf"
    create_pdf(source, _document(1))
    first = _rgb_png(tmp_path / "first.png", (255, 0, 0))
    second = _rgb_png(tmp_path / "second.png", (0, 0, 255))

    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(source, destination, [
            _image_primitive(first, width=80, height=40),
            _image_primitive(second, width=60, height=30),
        ]),
    )

    assert result["status"] == "success", result
    reports = result["diagnostics"]["operation_result"]["primitives"]
    assert [item["image"]["resource"] for item in reports] == [
        "/DSWMImage",
        "/DSWMImage1",
    ]
    assert len({item["image"]["image_object"] for item in reports}) == 2
    assert [item["image"]["asset_sha256"] for item in reports] == [
        sha256(first.read_bytes()).hexdigest(),
        sha256(second.read_bytes()).hexdigest(),
    ]
    assert all(
        item["image"]["type"] == "/XObject"
        and item["image"]["subtype"] == "/Image"
        and item["image"]["decode_parms"] is None
        and item["image"]["soft_mask"] is None
        for item in reports
    )
    model = parse_pdf(destination)
    uses = scan_watermark_uses(model, walk_pages(model)[0])
    assert [use.image_resource for use in uses] == ["/DSWMImage", "/DSWMImage1"]
    assert [use.asset_sha256 for use in uses] == [
        sha256(first.read_bytes()).hexdigest(),
        sha256(second.read_bytes()).hexdigest(),
    ]
    assert len({use.stream_sha256 for use in uses}) == 2


def test_public_cover_image_watermark_keeps_clipped_bbox_semantics(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "cover.pdf"
    create_pdf(source, _document(1))
    image = _rgb_png(tmp_path / "wide.png", (40, 120, 200))
    primitive = _image_primitive(image, width=40, height=40)
    primitive["image"]["fit"] = "cover"

    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(source, destination, [primitive]),
    )

    assert result["status"] == "success", result
    evidence = result["diagnostics"]["operation_result"]["image"]
    assert evidence["bbox"][2] - evidence["bbox"][0] == 40.0
    assert evidence["bbox"][3] - evidence["bbox"][1] == 40.0


def test_watermark_evidence_survives_a_later_page_identity_replacement(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "selected.pdf"
    create_pdf(source, _document(2))

    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(source, destination, [
            {
                "type": "watermark",
                "text": "KEEP AFTER RENUMBER",
                "pages": [2],
                "opacity": 0.3,
            },
            {"type": "page_sequence", "pages": [2]},
        ]),
    )

    assert result["status"] == "success", result
    model = parse_pdf(destination)
    pages = walk_pages(model)
    assert len(pages) == 1
    assert b"KEEP AFTER RENUMBER" in extract_content_stream(model, pages[0].contents, 1)


def test_image_watermark_asset_binding_survives_later_page_renumbering(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "selected-image.pdf"
    create_pdf(source, _document(2))
    image = _rgb_png(tmp_path / "renumber.png", (20, 160, 80))
    primitive = _image_primitive(image, width=60, height=30)
    primitive["pages"] = [2]

    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(source, destination, [
            primitive,
            {"type": "page_sequence", "pages": [2]},
        ]),
    )

    assert result["status"] == "success", result
    model = parse_pdf(destination)
    uses = scan_watermark_uses(model, walk_pages(model)[0])
    assert len(uses) == 1
    assert uses[0].asset_sha256 == sha256(image.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "tamper_kind",
    ["resource-object", "bbox", "decode-parms", "main-subtype"],
)
def test_image_watermark_tamper_does_not_promote(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper_kind: str,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    create_pdf(source, _document(1))
    first = _rgb_png(tmp_path / "first.png", (255, 0, 0))
    second = _rgb_png(tmp_path / "second.png", (0, 0, 255))
    destination.write_bytes(b"preserve destination")
    real_edit = service_module.edit_pdf

    def tampered_edit(
        input_path: Path,
        output_path: Path,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        operation, manifest = real_edit(input_path, output_path, arguments)
        reports = operation["primitives"]
        candidate = output_path.read_bytes()
        if tamper_kind == "resource-object":
            first_object = reports[0]["image"]["image_object"]
            second_object = reports[1]["image"]["image_object"]
            before = f"/DSWMImage1 {second_object} 0 R".encode("ascii")
            after = f"/DSWMImage1 {first_object} 0 R".encode("ascii")
            assert len(before) == len(after)
            tampered = candidate.replace(before, after, 1)
        elif tamper_kind == "bbox":
            content_object = reports[1]["watermark_uses"][0]["content_object"]
            payload = parse_pdf(output_path).objects[content_object].payload_bytes
            changed = payload.replace(b"60 0 0 30", b"50 0 0 30", 1)
            assert changed != payload
            tampered = candidate.replace(payload, changed, 1)
        else:
            image_object = reports[1]["image"]["image_object"]
            if tamper_kind == "decode-parms":
                _inject_decode_parms(output_path, image_object)
                tampered = output_path.read_bytes()
            else:
                payload = parse_pdf(output_path).objects[image_object].payload_bytes
                changed = payload.replace(
                    b"/Subtype /Image",
                    b"/Subtype /Xmage",
                    1,
                )
                assert changed != payload
                tampered = candidate.replace(payload, changed, 1)
        assert tampered != candidate
        output_path.write_bytes(tampered)
        return operation, _rebound_manifest(input_path, output_path, manifest)

    monkeypatch.setattr(service_module, "edit_pdf", tampered_edit)
    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(source, destination, [
            _image_primitive(first, width=80, height=40),
            _image_primitive(second, width=60, height=30),
        ]),
    )

    assert result["status"] == "failed", result
    assert result["errors"][0]["details"]["failed_gates"] == [
        "operation.mutation-semantics"
    ]
    assert destination.read_bytes() == b"preserve destination"


def test_alpha_watermark_soft_mask_dictionary_tamper_does_not_promote(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    create_pdf(source, _document(1))
    image = _rgba_png(tmp_path / "alpha.png", (30, 90, 180, 120))
    destination.write_bytes(b"preserve destination")
    real_edit = service_module.edit_pdf

    def tampered_edit(
        input_path: Path,
        output_path: Path,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        operation, manifest = real_edit(input_path, output_path, arguments)
        soft_mask = operation["image"]["soft_mask"]
        payload = parse_pdf(output_path).objects[soft_mask["object"]].payload_bytes
        changed = payload.replace(
            b"/ColorSpace /DeviceGray",
            b"/ColorSpace /DeviceRGB ",
            1,
        )
        assert changed != payload
        candidate = output_path.read_bytes()
        output_path.write_bytes(candidate.replace(payload, changed, 1))
        return operation, _rebound_manifest(input_path, output_path, manifest)

    monkeypatch.setattr(service_module, "edit_pdf", tampered_edit)
    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(source, destination, [_image_primitive(image, width=80, height=40)]),
    )

    assert result["status"] == "failed", result
    assert result["errors"][0]["details"]["failed_gates"] == [
        "operation.mutation-semantics"
    ]
    assert destination.read_bytes() == b"preserve destination"


def test_existing_matching_watermark_cannot_satisfy_a_new_request(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clean = tmp_path / "clean.pdf"
    source = tmp_path / "already-watermarked.pdf"
    destination = tmp_path / "destination.pdf"
    create_pdf(clean, _document(1))
    primitive = {
        "type": "watermark",
        "text": "BORROWED",
        "pages": [1],
        "opacity": 0.25,
    }
    first_result = PdfService(project_root).execute(
        "pdf.edit",
        _request(clean, source, [primitive]),
    )
    assert first_result["status"] == "success", first_result
    destination.write_bytes(b"preserve destination")
    real_edit = service_module.edit_pdf

    def unchanged_edit(
        input_path: Path,
        output_path: Path,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        operation, _manifest = real_edit(input_path, output_path, arguments)
        output_path.write_bytes(input_path.read_bytes())
        unchanged = _build_manifest(
            parse_pdf(input_path).object_hashes(),
            parse_pdf(output_path).object_hashes(),
            changed=set(),
            added=set(),
            removed=set(),
        )
        operation["preservation"] = unchanged
        return operation, unchanged

    monkeypatch.setattr(service_module, "edit_pdf", unchanged_edit)
    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(source, destination, [primitive]),
    )

    assert result["status"] == "failed", result
    assert result["errors"][0]["details"]["failed_gates"] == [
        "operation.mutation-semantics"
    ]
    assert destination.read_bytes() == b"preserve destination"


def _shared_content_pdf(path: Path) -> Path:
    created = path.with_name("unshared.pdf")
    create_pdf(created, _document(2))
    reader = PdfReader(created)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    shared = writer.pages[0].raw_get("/Contents")
    writer.pages[1][NameObject("/Contents")] = shared
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _rgb_png(path: Path, color: tuple[int, int, int]) -> Path:
    Image.new("RGB", (2, 1), color).save(path, format="PNG")
    return path


def _rgba_png(path: Path, color: tuple[int, int, int, int]) -> Path:
    Image.new("RGBA", (2, 1), color).save(path, format="PNG")
    return path


def _image_primitive(path: Path, *, width: int, height: int) -> dict[str, Any]:
    return {
        "type": "watermark",
        "image": {
            "filename": str(path),
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "content_type": "image/png",
            "fit": "contain",
            "width": width,
            "height": height,
            "alt": path.stem,
        },
        "pages": [1],
        "opacity": 0.4,
    }


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


def _inject_decode_parms(candidate: Path, object_number: int) -> None:
    """Inject DecodeParms while retaining valid classical xref offsets."""
    raw = candidate.read_bytes()
    object_start = raw.index(f"{object_number} 0 obj\n".encode("ascii"))
    stream_start = raw.index(b"\nstream\n", object_start)
    dictionary_end = raw.rfind(b">>", object_start, stream_start)
    startxref = re.search(rb"startxref\s+([0-9]+)", raw)
    assert startxref is not None
    old_xref = int(startxref.group(1))
    assert dictionary_end > object_start
    assert raw[old_xref : old_xref + 5] == b"xref\n"
    addition = b" /DecodeParms << /ColorTransform 1 >>"
    delta = len(addition)
    tail = raw[old_xref:]

    def shifted_entry(match: re.Match[bytes]) -> bytes:
        offset = int(match.group(1))
        if offset >= dictionary_end:
            offset += delta
        return f"{offset:010d}".encode("ascii") + match.group(2)

    tail = re.sub(
        rb"(?m)^([0-9]{10})( [0-9]{5} [nf]\r?)$",
        shifted_entry,
        tail,
    )
    old_marker = f"startxref\n{old_xref}\n".encode("ascii")
    new_marker = f"startxref\n{old_xref + delta}\n".encode("ascii")
    assert old_marker in tail
    tail = tail.replace(old_marker, new_marker, 1)
    candidate.write_bytes(
        raw[:dictionary_end] + addition + raw[dictionary_end:old_xref] + tail
    )


def _request(
    source: Path,
    output: Path,
    primitives: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "pdf.edit",
        "input": str(source),
        "output": str(output),
        "arguments": {"primitives": primitives},
    }


def _document(page_count: int) -> dict[str, Any]:
    return {
        "metadata": {"title": "Watermark blockers", "author": "Elftia"},
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
