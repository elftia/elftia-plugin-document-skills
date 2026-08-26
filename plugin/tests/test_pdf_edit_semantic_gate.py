"""Fail-closed semantic and mutation-plan gates for public PDF edits."""

from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, FloatObject, NameObject

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.edit import _build_manifest
from document_skills_core.formats.pdf.object_model import parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages
from document_skills_core.formats.pdf import service as service_module
from document_skills_core.formats.pdf.service import PdfService


def _document(page_count: int = 2) -> dict[str, Any]:
    return {
        "metadata": {"title": "Semantic gate", "author": "Elftia", "subject": ""},
        "page_size": "A4",
        "pages": [
            {
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": f"Page {page}",
                        "style": None,
                        "table": None,
                        "image": None,
                        "shape": None,
                    }
                ],
                "metadata": None,
            }
            for page in range(1, page_count + 1)
        ],
    }


def _request(source: Path, output: Path, primitives: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "pdf.edit",
        "input": str(source),
        "output": str(output),
        "arguments": {"primitives": primitives},
    }


@pytest.mark.parametrize(
    "primitive",
    [
        {"type": "rotate", "pages": [3], "degrees": 90},
        {"type": "split", "page_ranges": [[3, 3]]},
        {"type": "split", "page_ranges": [[2, 1]]},
    ],
)
def test_service_rejects_invalid_staged_page_selection_without_publishing(
    project_root: Path,
    tmp_path: Path,
    primitive: dict[str, Any],
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    create_pdf(source, _document())
    destination.write_bytes(b"existing destination")

    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(source, destination, [primitive]),
    )

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == ErrorCode.REQUEST_INVALID.value
    assert destination.read_bytes() == b"existing destination"


def test_manifest_builder_rejects_an_unplanned_object_change() -> None:
    with pytest.raises(DocumentSkillsError) as caught:
        _build_manifest(
            {1: "source-one", 2: "source-two"},
            {1: "changed-one", 2: "source-two"},
            changed=set(),
            added=set(),
            removed=set(),
        )

    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    assert caught.value.details["unexpected_changed_objects"] == [1]


def test_service_runs_required_composite_semantic_assertion(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "edited.pdf"
    create_pdf(source, _document())

    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(
            source,
            destination,
            [
                {"type": "rotate", "pages": [1], "degrees": 90},
                {
                    "type": "watermark",
                    "text": "REVIEW",
                    "pages": [2],
                    "opacity": 0.25,
                },
            ],
        ),
    )

    assert result["status"] == "success", result
    gate = next(
        item for item in result["validation"]["gates"]
        if item["id"] == "operation.mutation-semantics"
    )
    assert gate["outcome"] == "pass"
    assert gate["evidence"]["page_tree"] is True
    assert gate["evidence"]["rotate"] == 1
    assert gate["evidence"]["watermark"] == 1
    operation = result["diagnostics"]["operation_result"]
    assert operation["primitive_count"] == 2
    assert len(operation["preservation"]["primitive_plans"]) == 2
    assert operation["preservation"]["expected_output_hashes"]


def test_multiple_watermarks_bind_distinct_opacity_resources(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "watermarked.pdf"
    create_pdf(source, _document(page_count=1))

    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(
            source,
            destination,
            [
                {
                    "type": "watermark",
                    "text": "FIRST",
                    "pages": [1],
                    "opacity": 0.25,
                },
                {
                    "type": "watermark",
                    "text": "SECOND",
                    "pages": [1],
                    "opacity": 0.75,
                },
            ],
        ),
    )

    assert result["status"] == "success", result
    operations = result["diagnostics"]["operation_result"]["primitives"]
    assert [item["graphics_state"] for item in operations] == [
        "/DSWMGS",
        "/DSWMGS1",
    ]
    model = parse_pdf(destination)
    graphics = walk_pages(model)[0].resources.get("/ExtGState")
    assert graphics.get("/DSWMGS").get("/ca") == 0.25
    assert graphics.get("/DSWMGS1").get("/ca") == 0.75


def test_watermark_does_not_borrow_or_overwrite_an_existing_graphics_state(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "watermarked.pdf"
    create_pdf(source, _document(page_count=1))
    reader = PdfReader(source)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    resources = writer.pages[0]["/Resources"]
    resources[NameObject("/ExtGState")] = DictionaryObject({
        NameObject("/DSWMGS"): DictionaryObject({
            NameObject("/Type"): NameObject("/ExtGState"),
            NameObject("/ca"): FloatObject(0.9),
            NameObject("/CA"): FloatObject(0.9),
        }),
    })
    with source.open("wb") as handle:
        writer.write(handle)

    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(
            source,
            destination,
            [{
                "type": "watermark",
                "text": "DEDICATED",
                "pages": [1],
                "opacity": 0.25,
            }],
        ),
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["graphics_state"] == "/DSWMGS1"
    graphics = walk_pages(parse_pdf(destination))[0].resources.get("/ExtGState")
    assert graphics.get("/DSWMGS").get("/ca") == 0.9
    assert graphics.get("/DSWMGS1").get("/ca") == 0.25


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(
            lambda payload: payload.replace(
                b"/ca 0.25 /CA 0.25",
                b"/ca 0.75 /CA 0.25",
                1,
            ),
            id="wrong-nonstroking-opacity",
        ),
        pytest.param(
            lambda payload: payload.replace(
                b"/ca 0.25 /CA 0.25",
                b"/ca 0.25 /CA 0.75",
                1,
            ),
            id="wrong-stroking-opacity",
        ),
        pytest.param(
            lambda payload: payload.replace(b"/DSWMGS", b"/Borrow", 2),
            id="borrowed-graphics-state",
        ),
        pytest.param(
            lambda payload: payload.replace(b"/DSWMGS gs", b"/DSWMGS xx", 1),
            id="missing-graphics-state-binding",
        ),
    ],
)
def test_watermark_graphics_state_tamper_does_not_promote(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: Callable[[bytes], bytes],
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    create_pdf(source, _document(page_count=1))
    destination.write_bytes(b"preserve destination")
    real_edit_pdf = service_module.edit_pdf

    def tampered_edit(
        input_path: Path,
        output_path: Path,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        operation, manifest = real_edit_pdf(input_path, output_path, arguments)
        candidate = output_path.read_bytes()
        tampered = tamper(candidate)
        assert tampered != candidate
        output_path.write_bytes(tampered)
        output_hashes = parse_pdf(output_path).object_hashes()
        manifest = _build_manifest(
            parse_pdf(input_path).object_hashes(),
            output_hashes,
            changed=set(manifest["changed_objects"]),
            added=set(manifest["added_objects"]),
            removed=set(manifest["removed_objects"]),
        )
        operation["preservation"] = manifest
        return operation, manifest

    monkeypatch.setattr(service_module, "edit_pdf", tampered_edit)
    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(
            source,
            destination,
            [{
                "type": "watermark",
                "text": "TAMPER",
                "pages": [1],
                "opacity": 0.25,
            }],
        ),
    )

    assert result["status"] == "failed", result
    assert result["errors"][0]["details"]["failed_gates"] == [
        "operation.mutation-semantics"
    ]
    assert destination.read_bytes() == b"preserve destination"


def test_service_semantic_gate_rejects_a_hash_bound_wrong_rotation(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    create_pdf(source, _document())
    destination.write_bytes(b"preserve me")

    def wrong_edit(
        input_path: Path,
        output_path: Path,
        _arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        output_path.write_bytes(input_path.read_bytes())
        model = parse_pdf(input_path)
        hashes = model.object_hashes()
        page_object = walk_pages(model)[0].obj_num
        manifest = _build_manifest(
            hashes,
            hashes,
            changed={page_object},
            added=set(),
            removed=set(),
        )
        return {"primitive": "rotate", "preservation": manifest}, manifest

    monkeypatch.setattr(service_module, "edit_pdf", wrong_edit)
    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(
            source,
            destination,
            [{"type": "rotate", "pages": [1], "degrees": 90}],
        ),
    )

    assert result["status"] == "failed"
    assert result["errors"][0]["details"]["failed_gates"] == [
        "operation.mutation-semantics"
    ]
    assert destination.read_bytes() == b"preserve me"


def test_later_invalid_primitive_preserves_existing_destination(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    create_pdf(source, _document())
    source_digest = sha256(source.read_bytes()).hexdigest()
    original_destination = b"do not replace"
    destination.write_bytes(original_destination)

    result = PdfService(project_root).execute(
        "pdf.edit",
        _request(
            source,
            destination,
            [
                {"type": "rotate", "pages": [1], "degrees": 90},
                {"type": "rotate", "pages": [9], "degrees": 180},
            ],
        ),
    )

    assert result["status"] == "invalid_request"
    assert destination.read_bytes() == original_destination
    assert sha256(source.read_bytes()).hexdigest() == source_digest
