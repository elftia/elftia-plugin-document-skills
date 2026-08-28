"""Pure raster-difference tests for optional Poppler render evidence."""

from io import BytesIO
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pytest

from document_skills_core.providers.pdf_tools.render_diff import (
    aggregate_render_diff,
    compare_rendered_page,
)
from document_skills_core.providers.pdf_tools.archive import (
    manifest_bytes,
    payload_record,
    validate_archive,
    write_archive,
)
from document_skills_core.core.io.paths import sha256_file
from tests.test_pdf_tools_provider import _minimal_pdf


def _page(*, rotation=0, media_box=(0.0, 0.0, 100.0, 100.0)):
    return SimpleNamespace(
        page_number=1,
        media_box=media_box,
        crop_box=None,
        rotation=rotation,
    )


def _png(
    *,
    dimensions=(100, 100),
    patch: tuple[int, int, int, int] | None = None,
    value: int = 255,
):
    image = Image.new("RGB", dimensions, "white")
    if patch is not None:
        ImageDraw.Draw(image).rectangle(patch, fill=(value, value, value))
    payload = BytesIO()
    image.save(payload, format="PNG")
    return payload.getvalue()


def test_identical_pages_have_no_changed_samples():
    payload = _png()

    record = compare_rendered_page(
        payload,
        payload,
        _page(),
        [],
        channel_tolerance=0,
    )

    assert record["changed_samples"] == 0
    assert record["unexpected_change_ratio"] == 0.0


def test_change_inside_expected_pdf_bbox_is_not_unexpected():
    reference = _png()
    candidate = _png(patch=(10, 80, 19, 89), value=0)

    record = compare_rendered_page(
        candidate,
        reference,
        _page(),
        [{"page": 1, "bbox": [10.0, 10.0, 20.0, 20.0]}],
        channel_tolerance=0,
    )

    assert record["expected_changed_samples"] == 100
    assert record["unexpected_changed_samples"] == 0
    assert record["expected_change_ratio"] == 1.0


def test_change_outside_expected_pdf_bbox_is_unexpected():
    reference = _png()
    candidate = _png(patch=(70, 10, 79, 19), value=0)

    record = compare_rendered_page(
        candidate,
        reference,
        _page(),
        [{"page": 1, "bbox": [10.0, 10.0, 20.0, 20.0]}],
        channel_tolerance=0,
    )

    assert record["expected_changed_samples"] == 0
    assert record["unexpected_changed_samples"] == 100


@pytest.mark.parametrize(
    ("rotation", "dimensions", "patch"),
    [
        (90, (200, 100), (20, 10, 39, 29)),
        (180, (100, 200), (70, 20, 89, 39)),
        (270, (200, 100), (160, 70, 179, 89)),
    ],
)
def test_expected_pdf_bbox_maps_through_page_rotation(
    rotation,
    dimensions,
    patch,
):
    reference = _png(dimensions=dimensions)
    candidate = _png(dimensions=dimensions, patch=patch, value=0)

    record = compare_rendered_page(
        candidate,
        reference,
        _page(
            rotation=rotation,
            media_box=(0.0, 0.0, 100.0, 200.0),
        ),
        [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
        channel_tolerance=0,
    )

    assert record["expected_changed_samples"] == 400
    assert record["unexpected_changed_samples"] == 0


def test_channel_tolerance_suppresses_small_differences():
    reference = _png(patch=(0, 0, 99, 99), value=100)
    candidate = _png(patch=(0, 0, 99, 99), value=105)

    tolerated = compare_rendered_page(
        candidate,
        reference,
        _page(),
        [],
        channel_tolerance=5,
    )
    detected = compare_rendered_page(
        candidate,
        reference,
        _page(),
        [],
        channel_tolerance=4,
    )

    assert tolerated["changed_samples"] == 0
    assert detected["changed_samples"] == 10_000


def test_aggregate_thresholds_require_expected_and_unexpected_policies():
    records = [
        {
            "samples": 1_000,
            "changed_samples": 60,
            "expected_samples": 100,
            "expected_changed_samples": 50,
            "unexpected_samples": 900,
            "unexpected_changed_samples": 10,
        }
    ]

    passing = aggregate_render_diff(
        records,
        reference_sha256="b" * 64,
        channel_tolerance=2,
        max_unexpected_change_ratio=0.02,
        minimum_expected_change_ratio=0.5,
    )
    failing = aggregate_render_diff(
        records,
        reference_sha256="b" * 64,
        channel_tolerance=2,
        max_unexpected_change_ratio=0.01,
        minimum_expected_change_ratio=0.6,
    )

    assert passing["policy_pass"] is True
    assert failing["expected_change_pass"] is False
    assert failing["unexpected_change_pass"] is False
    assert failing["policy_pass"] is False


def test_archive_render_diff_gate_is_required_and_policy_authoritative(tmp_path):
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    source.write_bytes(b"%PDF-source")
    reference.write_bytes(b"%PDF-reference")
    page_payload = _png()
    page_record = payload_record("page-0001.png", page_payload)
    manifest = {
        "schema_version": "1.0",
        "operation": "pdf.render",
        "pages": [page_record],
    }
    archive = tmp_path / "render.zip"
    write_archive(
        archive,
        {
            "manifest.json": manifest_bytes(manifest),
            "page-0001.png": page_payload,
        },
    )
    comparison = {
        "policy_pass": True,
        "reference_sha256": sha256_file(reference),
    }

    passing = validate_archive(
        archive,
        payload_records=[page_record],
        manifest=manifest,
        source=source,
        source_sha256=sha256_file(source),
        reference=reference,
        reference_sha256=sha256_file(reference),
        render_comparison=comparison,
    )
    failing = validate_archive(
        archive,
        payload_records=[page_record],
        manifest=manifest,
        source=source,
        source_sha256=sha256_file(source),
        reference=reference,
        reference_sha256=sha256_file(reference),
        render_comparison={**comparison, "policy_pass": False},
    )

    passing_gates = {gate["id"]: gate for gate in passing["gates"]}
    failing_gates = {gate["id"]: gate for gate in failing["gates"]}
    assert passing_gates["visual.page-render-diff"]["required"] is True
    assert passing_gates["visual.page-render-diff"]["outcome"] == "pass"
    assert passing_gates["reference.preservation"]["outcome"] == "pass"
    assert failing["status"] == "fail"
    assert failing_gates["visual.page-render-diff"]["outcome"] == "fail"


def test_archive_reopen_reparses_pdf_render_semantics(tmp_path):
    source = _minimal_pdf(tmp_path / "source.pdf")
    page_payload = _png()
    payload = payload_record("page-0001.png", page_payload)
    page = {
        **payload,
        "page": 1,
        "format": "png",
        "media_box": [0.0, 0.0, 100.0, 100.0],
        "crop_box": None,
        "rotation": 0,
        "dpi": 72,
        "width": 100,
        "height": 100,
        "pixels": 10_000,
        "raster_evidence": {
            "expected_width": 100,
            "expected_height": 100,
            "bbox": [0, 0, 100, 100],
            "bounds": [0, 0, 100, 100],
            "bounded": True,
            "overflow": False,
        },
    }
    manifest = {
        "schema_version": "1.0",
        "operation": "pdf.render",
        "provider": "poppler",
        "dpi": 72,
        "format": "png",
        "pages": [page],
    }
    archive = tmp_path / "render.zip"
    write_archive(
        archive,
        {
            "manifest.json": manifest_bytes(manifest),
            "page-0001.png": page_payload,
        },
    )
    arguments = {"pages": [1], "dpi": 72, "format": "png"}

    passing = validate_archive(
        archive,
        payload_records=[payload],
        manifest=manifest,
        source=source,
        source_sha256=sha256_file(source),
        render_arguments=arguments,
    )

    tampered = {**manifest, "pages": [{**page, "rotation": 90}]}
    write_archive(
        archive,
        {
            "manifest.json": manifest_bytes(tampered),
            "page-0001.png": page_payload,
        },
    )
    failing = validate_archive(
        archive,
        payload_records=[payload],
        manifest=tampered,
        source=source,
        source_sha256=sha256_file(source),
        render_arguments=arguments,
    )

    passing_gates = {gate["id"]: gate for gate in passing["gates"]}
    failing_gates = {gate["id"]: gate for gate in failing["gates"]}
    assert passing["status"] == "pass"
    assert passing_gates["render.page-semantics"]["outcome"] == "pass"
    assert passing_gates["render.page-semantics"]["evidence"] == {
        "dpi": 72,
        "format": "png",
        "pages": [1],
        "validated_images": 1,
    }
    assert failing["status"] == "fail"
    assert failing_gates["render.page-semantics"]["outcome"] == "fail"
