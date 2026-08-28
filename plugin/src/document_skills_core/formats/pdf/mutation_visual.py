"""Provider-gated pre/post full-page raster validation for PDF mutations.

Module provenance: original Elftia-authored clean-room implementation.
"""

from collections.abc import Callable
from pathlib import Path
import time
from typing import Any, Protocol

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.io.paths import sha256_file

from .byte_preflight import preflight_pdf
from .mutation_visual_plan import derive_mutation_visual_plan
from .object_model import parse_pdf
from .page_tree import PageInfo, walk_pages

_DPI = 72
_CHANNEL_TOLERANCE = 2
_MAX_UNEXPECTED_CHANGE_RATIO = 0.0001
_MINIMUM_EXPECTED_CHANGE_RATIO = 0.0001
_MAX_PAGES = 64
_MAX_PIXELS = 40_000_000
_MAX_TOTAL_BYTES = 64 * 1024 * 1024
_TIMEOUT_SECONDS = 120.0
_GATE_ID = "visual.mutation-render-diff"


class PopplerDetector(Protocol):
    def detect(self) -> Any: ...

    def accepted_paths(self) -> dict[str, Path]: ...


class PageRenderRunner(Protocol):
    def configure(
        self,
        paths: dict[str, Path],
        *,
        languages: frozenset[str] = frozenset(),
    ) -> None: ...

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
    ) -> Path: ...


class MutationVisualValidator:
    """Run a bounded Poppler comparison without publishing render sidecars."""

    def __init__(
        self,
        project_root: Path,
        *,
        detector: PopplerDetector,
        runner: PageRenderRunner,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.project_root = project_root.resolve()
        self.detector = detector
        self.runner = runner
        self.clock = clock

    def validate(
        self,
        *,
        operation: str,
        source: Path,
        candidate: Path,
        arguments: dict[str, Any],
        operation_result: dict[str, Any],
        private_root: Path,
    ) -> dict[str, Any]:
        """Return one complete validation gate bound to the private candidate."""
        started = self.clock()
        try:
            detection = self.detector.detect()
        except Exception as error:
            return self._failure_gate(error, started, version=None)
        if not detection.available:
            reason = detection.reason or "The accepted Poppler provider is unavailable."
            return gate_record(
                _GATE_ID,
                "unavailable",
                required=False,
                validator="poppler",
                version=detection.version,
                duration_ms=_elapsed_ms(self.clock, started),
                evidence={"provider": "poppler", "reason": reason},
                warnings=[reason],
            )
        try:
            self.runner.configure(self.detector.accepted_paths())
            comparison = self._compare(
                operation=operation,
                source=source,
                candidate=candidate,
                arguments=arguments,
                operation_result=operation_result,
                private_root=private_root,
                started=started,
            )
        except Exception as error:
            return self._failure_gate(error, started, version=detection.version)
        if comparison.get("not_applicable"):
            return gate_record(
                _GATE_ID,
                "not_applicable",
                required=False,
                validator="poppler",
                version=detection.version,
                duration_ms=_elapsed_ms(self.clock, started),
                evidence=comparison,
            )
        if comparison.get("unavailable_reason"):
            reason = str(comparison["unavailable_reason"])
            return gate_record(
                _GATE_ID,
                "unavailable",
                required=False,
                validator="poppler",
                version=detection.version,
                duration_ms=_elapsed_ms(self.clock, started),
                evidence=comparison,
                warnings=[reason],
            )
        return gate_record(
            _GATE_ID,
            "pass" if comparison["policy_pass"] else "fail",
            required=True,
            validator="poppler",
            version=detection.version,
            duration_ms=_elapsed_ms(self.clock, started),
            evidence=comparison,
        )

    def _compare(
        self,
        *,
        operation: str,
        source: Path,
        candidate: Path,
        arguments: dict[str, Any],
        operation_result: dict[str, Any],
        private_root: Path,
        started: float,
    ) -> dict[str, Any]:
        preflight_pdf(source)
        preflight_pdf(candidate)
        source_model = parse_pdf(source)
        candidate_model = parse_pdf(candidate)
        source_pages = walk_pages(source_model)
        candidate_pages = walk_pages(candidate_model)
        plan = derive_mutation_visual_plan(
            operation,
            source_model,
            candidate_model,
            arguments,
            operation_result,
        )
        if plan.unavailable_reason is not None:
            return {
                "provider": "poppler",
                "operation": operation,
                "unavailable_reason": plan.unavailable_reason,
                "basis": list(plan.basis),
            }
        if not plan.pages:
            return {
                "provider": "poppler",
                "operation": operation,
                "not_applicable": True,
                "reason": "The mutation has no page-rendering effect.",
                "basis": list(plan.basis),
            }
        if len(plan.pages) > _MAX_PAGES:
            _unsafe("Automatic mutation visual validation exceeds the page limit.")
        source_by_page = {page.page_number: page for page in source_pages}
        candidate_by_page = {page.page_number: page for page in candidate_pages}
        for number in plan.pages:
            if number not in source_by_page or number not in candidate_by_page:
                return {
                    "provider": "poppler",
                    "operation": operation,
                    "unavailable_reason": "Affected pages have no stable pre/post page mapping.",
                    "basis": list(plan.basis),
                }
            if not _same_render_geometry(source_by_page[number], candidate_by_page[number]):
                return {
                    "provider": "poppler",
                    "operation": operation,
                    "unavailable_reason": "Affected pages do not share comparable render geometry.",
                    "basis": list(plan.basis),
                }
        before_source = sha256_file(source)
        before_candidate = sha256_file(candidate)
        render_root = private_root / "mutation-visual"
        render_root.mkdir(parents=True, exist_ok=True)
        page_records: list[dict[str, Any]] = []
        total_bytes = 0
        total_pixels = 0
        for number in plan.pages:
            source_payload, source_size = self._render(
                source,
                render_root / f"source-{number:04d}",
                source_by_page[number],
                total_bytes,
                started,
            )
            total_bytes += len(source_payload)
            total_pixels += source_size[0] * source_size[1]
            candidate_payload, candidate_size = self._render(
                candidate,
                render_root / f"candidate-{number:04d}",
                candidate_by_page[number],
                total_bytes,
                started,
            )
            total_bytes += len(candidate_payload)
            total_pixels += candidate_size[0] * candidate_size[1]
            if total_pixels > _MAX_PIXELS:
                _unsafe("Automatic mutation visual validation exceeds the pixel limit.")
            from document_skills_core.providers.pdf_tools.render_diff import (
                compare_rendered_page,
            )

            page_records.append(
                compare_rendered_page(
                    candidate_payload,
                    source_payload,
                    candidate_by_page[number],
                    list(plan.regions),
                    channel_tolerance=_CHANNEL_TOLERANCE,
                )
            )
        if sha256_file(source) != before_source or sha256_file(candidate) != before_candidate:
            _failed("The visual provider changed a PDF input during validation.")
        from document_skills_core.providers.pdf_tools.render_diff import (
            aggregate_render_diff,
        )

        minimum_expected = (
            0.0 if plan.includes_full_page else _MINIMUM_EXPECTED_CHANGE_RATIO
        )
        comparison = aggregate_render_diff(
            page_records,
            reference_sha256=before_source,
            channel_tolerance=_CHANNEL_TOLERANCE,
            max_unexpected_change_ratio=_MAX_UNEXPECTED_CHANGE_RATIO,
            minimum_expected_change_ratio=minimum_expected,
        )
        comparison.update({
            "operation": operation,
            "candidate_sha256": before_candidate,
            "dpi": _DPI,
            "format": "png",
            "rendered_pages": list(plan.pages),
            "expected_change_regions": list(plan.regions),
            "region_basis": list(plan.basis),
            "private_staging": True,
            "total_render_bytes": total_bytes,
            "total_render_pixels": total_pixels,
        })
        return comparison

    def _render(
        self,
        source: Path,
        prefix: Path,
        page: PageInfo,
        used_bytes: int,
        started: float,
    ) -> tuple[bytes, tuple[int, int]]:
        remaining_bytes = _MAX_TOTAL_BYTES - used_bytes
        if remaining_bytes <= 0:
            _unsafe("Automatic mutation visual validation exceeds the byte limit.")
        remaining_time = _remaining(self.clock, started)
        rendered = self.runner.render_page(
            source,
            prefix,
            page=page.page_number,
            dpi=_DPI,
            output_format="png",
            max_output_bytes=remaining_bytes,
            timeout_seconds=min(30.0, remaining_time),
        )
        _remaining(self.clock, started)
        payload = _read_bounded(rendered, remaining_bytes)
        from document_skills_core.providers.pdf_tools.render import image_dimensions
        from document_skills_core.providers.pdf_tools.render_semantics import (
            expected_raster_dimensions,
        )

        dimensions = image_dimensions(payload, "png")
        expected = expected_raster_dimensions(page, _DPI)
        if dimensions != expected:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Poppler mutation raster dimensions do not match the PDF page geometry.",
                details={
                    "page": page.page_number,
                    "expected_dimensions": list(expected),
                    "actual_dimensions": list(dimensions),
                },
            )
        return payload, dimensions

    def _failure_gate(
        self,
        error: Exception,
        started: float,
        *,
        version: str | None,
    ) -> dict[str, Any]:
        code = error.code.value if isinstance(error, DocumentSkillsError) else None
        return gate_record(
            _GATE_ID,
            "fail",
            required=True,
            validator="poppler",
            version=version,
            duration_ms=_elapsed_ms(self.clock, started),
            evidence={
                "provider": "poppler",
                "reason": code or type(error).__name__,
                "message": str(error)[:512],
            },
        )


def build_mutation_visual_validator(project_root: Path) -> MutationVisualValidator:
    """Build the private Poppler validator without creating a public operation."""
    from document_skills_core.providers.pdf_tools.detector import PdfToolDetector
    from document_skills_core.providers.pdf_tools.runner import PdfToolRunner

    return MutationVisualValidator(
        project_root,
        detector=PdfToolDetector(project_root, require_tesseract=False),
        runner=PdfToolRunner(project_root),
    )


def _same_render_geometry(source: PageInfo, candidate: PageInfo) -> bool:
    return (
        (source.crop_box or source.media_box) == (candidate.crop_box or candidate.media_box)
        and source.rotation % 360 == candidate.rotation % 360
    )


def _read_bounded(path: Path, maximum: int) -> bytes:
    if not path.is_file() or path.stat().st_size <= 0:
        _failed("Poppler mutation rendering produced no image artifact.")
    if path.stat().st_size > maximum:
        _unsafe("Poppler mutation raster exceeds the remaining byte limit.")
    with path.open("rb") as stream:
        payload = stream.read(maximum + 1)
    if len(payload) > maximum:
        _unsafe("Poppler mutation raster exceeds the remaining byte limit.")
    return payload


def _remaining(clock: Callable[[], float], started: float) -> float:
    remaining = _TIMEOUT_SECONDS - (clock() - started)
    if remaining <= 0:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "Poppler mutation visual validation exceeded its deadline.",
            details={"timeout_seconds": _TIMEOUT_SECONDS},
        )
    return remaining


def _elapsed_ms(clock: Callable[[], float], started: float) -> int:
    return max(0, int((clock() - started) * 1000))


def _failed(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.PROVIDER_FAILED, message)


def _unsafe(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)
