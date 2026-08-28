"""Automatic provider-gated visual validation for Core PDF mutations.

The injected renderer is deterministic orchestration coverage only. The PDF Skill
explicitly states that fake-runner tests are not real Poppler/platform evidence.
"""

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
import pytest

from document_skills_core.core.capabilities import DetectionEvidence
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.mutation_visual import MutationVisualValidator
from document_skills_core.formats.pdf.mutation_visual_plan import (
    derive_mutation_visual_plan,
)
from document_skills_core.formats.pdf.object_model import parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages
from document_skills_core.formats.pdf.service import PdfService
from document_skills_core.providers.pdf_tools.render_semantics import (
    expected_raster_dimensions,
)
from tests.test_pdf_form_flatten import _f1_text_form
from tests.test_pdf_rewrite_targeting import _blocks, _request, _write_pdf


class StaticDetector:
    def __init__(self, *, available: bool) -> None:
        self.available = available

    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(
            self.available,
            version="25.1.0" if self.available else None,
            reason=None if self.available else "Poppler is absent in this profile.",
        )

    def accepted_paths(self) -> dict[str, Path]:
        return {"pdftoppm": Path("accepted-pdftoppm")}


class DeterministicRenderRunner:
    def __init__(
        self,
        source: Path,
        *,
        mode: str,
        expected_bbox: tuple[float, float, float, float],
    ) -> None:
        self.source = source.resolve()
        self.mode = mode
        self.expected_bbox = expected_bbox
        self.calls: list[tuple[Path, int]] = []
        self.configured: dict[str, Path] = {}

    def configure(
        self,
        paths: dict[str, Path],
        *,
        languages: frozenset[str] = frozenset(),
    ) -> None:
        assert not languages
        self.configured = dict(paths)

    def render_page(
        self,
        source: Path,
        output_prefix: Path,
        *,
        page: int,
        dpi: int,
        output_format: str,
        max_output_bytes: int,
        timeout_seconds: float = 30.0,
    ) -> Path:
        del max_output_bytes
        assert output_format == "png"
        assert timeout_seconds > 0
        self.calls.append((source.resolve(), page))
        if self.mode in {"crash", "timeout"}:
            message = (
                "provider crashed" if self.mode == "crash" else "provider timed out"
            )
            raise DocumentSkillsError(ErrorCode.PROVIDER_FAILED, message)
        rendered = output_prefix.with_suffix(".png")
        if self.mode == "malformed":
            rendered.write_bytes(b"not-a-png")
            return rendered
        page_info = walk_pages(parse_pdf(source))[page - 1]
        dimensions = expected_raster_dimensions(page_info, dpi)
        image = Image.new("RGB", dimensions, "white")
        if source.resolve() != self.source:
            if self.mode == "expected":
                _draw_pdf_bbox(image, page_info, self.expected_bbox)
            elif self.mode == "unexpected":
                ImageDraw.Draw(image).rectangle((500, 700, 519, 719), fill="black")
        image.save(rendered, format="PNG")
        return rendered


def test_rewrite_runs_required_private_pre_post_render_diff(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source, block = _rewrite_source(tmp_path)
    destination = tmp_path / "rewritten.pdf"
    request = _request(source, destination, block, "Changed")
    authorized_bbox = request["arguments"]["blocks"][0]["bbox"]
    runner = DeterministicRenderRunner(
        source,
        mode="expected",
        expected_bbox=tuple(float(value) for value in authorized_bbox),
    )
    result = _service(project_root, source, runner).execute(
        "pdf.rewrite.apply",
        request,
    )

    assert result["status"] == "success", result
    gate = _visual_gate(result)
    assert gate["required"] is True
    assert gate["outcome"] == "pass"
    assert gate["validator"] == "poppler"
    assert gate["evidence"]["private_staging"] is True
    assert gate["evidence"]["rendered_pages"] == [1]
    assert gate["evidence"]["expected_change_regions"] == [
        {
            "page": 1,
            "bbox": authorized_bbox,
        }
    ]
    assert gate["evidence"]["expected_changed_samples"] > 0
    assert gate["evidence"]["unexpected_changed_samples"] == 0
    assert runner.configured == {"pdftoppm": Path("accepted-pdftoppm")}
    assert len(runner.calls) == 2
    assert destination.is_file()


def test_edit_runs_required_diff_with_watermark_full_page_region(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source, block = _rewrite_source(tmp_path)
    destination = tmp_path / "edited.pdf"
    runner = DeterministicRenderRunner(
        source,
        mode="expected",
        expected_bbox=block.bbox,
    )
    request = {
        "schema_version": "1.0",
        "operation": "pdf.edit",
        "input": str(source),
        "output": str(destination),
        "arguments": {
            "primitives": [
                {
                    "type": "watermark",
                    "text": "REVIEW",
                    "pages": [1],
                    "opacity": 0.25,
                }
            ]
        },
    }

    result = _service(project_root, source, runner).execute("pdf.edit", request)

    assert result["status"] == "success", result
    gate = _visual_gate(result)
    assert gate["required"] is True
    assert gate["outcome"] == "pass"
    assert gate["evidence"]["region_basis"] == ["watermark-full-page"]
    assert gate["evidence"]["expected_change_regions"] == [
        {
            "page": 1,
            "bbox": [0.0, 0.0, 612.0, 792.0],
        }
    ]
    assert len(runner.calls) == 2


def test_unavailable_poppler_is_truthful_and_does_not_disable_core_mutation(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source, block = _rewrite_source(tmp_path)
    destination = tmp_path / "rewritten.pdf"
    runner = DeterministicRenderRunner(
        source,
        mode="expected",
        expected_bbox=block.bbox,
    )
    validator = MutationVisualValidator(
        project_root,
        detector=StaticDetector(available=False),
        runner=runner,
    )
    result = PdfService(project_root, mutation_visual=validator).execute(
        "pdf.rewrite.apply",
        _request(source, destination, block, "Changed"),
    )

    assert result["status"] == "success", result
    gate = _visual_gate(result)
    assert gate["outcome"] == "unavailable"
    assert gate["required"] is False
    assert runner.calls == []
    assert destination.is_file()


@pytest.mark.parametrize("mode", ["identical", "unexpected"])
def test_visual_ratio_miss_preserves_existing_destination(
    project_root: Path,
    tmp_path: Path,
    mode: str,
) -> None:
    source, block = _rewrite_source(tmp_path)
    destination = tmp_path / "rewritten.pdf"
    destination.write_bytes(b"existing destination")
    runner = DeterministicRenderRunner(
        source,
        mode=mode,
        expected_bbox=block.bbox,
    )
    result = _service(project_root, source, runner).execute(
        "pdf.rewrite.apply",
        _request(source, destination, block, "Changed"),
    )

    assert result["status"] == "failed"
    gate = _visual_gate(result)
    assert gate["required"] is True
    assert gate["outcome"] == "fail"
    assert gate["evidence"]["policy_pass"] is False
    if mode == "identical":
        assert gate["evidence"]["expected_change_pass"] is False
    else:
        assert gate["evidence"]["unexpected_change_pass"] is False
    assert destination.read_bytes() == b"existing destination"


@pytest.mark.parametrize("mode", ["crash", "timeout", "malformed"])
def test_provider_failure_is_a_required_atomic_gate_failure(
    project_root: Path,
    tmp_path: Path,
    mode: str,
) -> None:
    source, block = _rewrite_source(tmp_path)
    destination = tmp_path / "rewritten.pdf"
    destination.write_bytes(b"existing destination")
    runner = DeterministicRenderRunner(
        source,
        mode=mode,
        expected_bbox=block.bbox,
    )
    result = _service(project_root, source, runner).execute(
        "pdf.rewrite.apply",
        _request(source, destination, block, "Changed"),
    )

    assert result["status"] == "failed"
    gate = _visual_gate(result)
    assert gate["outcome"] == "fail"
    assert gate["required"] is True
    assert destination.read_bytes() == b"existing destination"


def test_edit_plan_uses_annotation_form_redaction_and_watermark_regions(
    tmp_path: Path,
) -> None:
    source = _f1_text_form(tmp_path / "form.pdf")
    model = parse_pdf(source)
    cases: list[tuple[dict[str, Any], dict[str, Any], str, list[float]]] = [
        (
            {
                "type": "annotation",
                "action": "add",
                "page": 1,
                "rectangle": [30.0, 40.0, 50.0, 60.0],
            },
            {},
            "annotation-rectangle",
            [30.0, 40.0, 50.0, 60.0],
        ),
        (
            {"type": "form_fill", "fields": {"name": "Ada"}, "flatten": False},
            {},
            "form-widget-rectangle",
            [20.0, 300.0, 180.0, 330.0],
        ),
        (
            {"type": "redact_text", "page": 1, "text": "secret"},
            {"bbox": [40.0, 50.0, 90.0, 70.0]},
            "redaction-result-bbox",
            [40.0, 50.0, 90.0, 70.0],
        ),
        (
            {"type": "watermark", "pages": [1]},
            {},
            "watermark-full-page",
            [0.0, 0.0, 300.0, 400.0],
        ),
    ]

    for primitive, operation_result, basis, bbox in cases:
        plan = derive_mutation_visual_plan(
            "pdf.edit",
            model,
            model,
            {"primitives": [primitive]},
            operation_result,
        )
        assert plan.pages == (1,)
        assert basis in plan.basis
        assert {"page": 1, "bbox": bbox} in plan.regions


def _service(
    project_root: Path,
    source: Path,
    runner: DeterministicRenderRunner,
) -> PdfService:
    return PdfService(
        project_root,
        mutation_visual=MutationVisualValidator(
            project_root,
            detector=StaticDetector(available=True),
            runner=runner,
        ),
    )


def _rewrite_source(tmp_path: Path):
    source = _write_pdf(
        tmp_path / "source.pdf",
        [b"BT /F1 12 Tf 1 0 0 1 72 720 Tm (Title) Tj ET\n"],
    )
    return source, _blocks(source)[0]


def _visual_gate(result: dict[str, Any]) -> dict[str, Any]:
    return next(
        gate
        for gate in result["validation"]["gates"]
        if gate["id"] == "visual.mutation-render-diff"
    )


def _draw_pdf_bbox(
    image: Image.Image,
    page: Any,
    bbox: tuple[float, float, float, float],
) -> None:
    box = page.crop_box or page.media_box
    width = float(box[2]) - float(box[0])
    height = float(box[3]) - float(box[1])
    x0, y0, x1, y1 = bbox
    left = round((x0 - box[0]) / width * image.width)
    right = round((x1 - box[0]) / width * image.width)
    top = round((box[3] - y1) / height * image.height)
    bottom = round((box[3] - y0) / height * image.height)
    ImageDraw.Draw(image).rectangle(
        (left, top, max(left, right - 1), max(top, bottom - 1)),
        fill="black",
    )
