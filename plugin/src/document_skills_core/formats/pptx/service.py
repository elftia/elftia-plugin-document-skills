"""PPTX dispatch and shared transactional mutation."""

from pathlib import Path
import time
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import make_error_result
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    assert_source_preserved,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedPptxRequest, parse_deck, parse_pptx_request
from .create import create_pptx
from .edit_service import execute_pptx_edit
from .inspect import inspect_pptx
from .markdown import parse_markdown_deck
from .outline import outline_validation, write_outline
from .read import read_pptx
from .html_capture import HtmlDeckCapture
from .results import read_validation, success_result
from .scene_emitter import emit_scene_pptx
from .scene_normalizer import normalize_scene
from .schema_validation import validate_schema_gate, with_schema_gate
from .transaction import promote_candidate, write_candidate_result
from .validation import validate_created, validate_scene_created
from .visual_validation import validate_scene_visuals, with_visual_gate


class PptxService:
    def __init__(
        self,
        project_root: Path,
        libreoffice=None,
        html_browser_detector=None,
        dotnet=None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.schemas = SchemaCatalog(self.project_root)
        self.libreoffice = libreoffice
        self.html_browser_detector = html_browser_detector
        self.dotnet = dotnet

    def execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._execute(operation, request)
        except DocumentSkillsError as error:
            options = request.get("options", {})
            requested_fidelity = (
                options.get("fidelity", "core") if type(options) is dict else "unknown"
            )
            return make_error_result(
                operation,
                error,
                requested_fidelity=requested_fidelity,
            )

    def _execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_pptx_request(request)
        if parsed.operation != operation:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "PPTX provider binding does not match the request operation.",
                status="invalid_request",
            )
        if operation == "pptx.read":
            return self._read(parsed)
        if operation == "pptx.inspect.structure":
            return self._inspect(parsed)
        if operation == "pptx.create":
            return self._create(parsed)
        if operation == "pptx.outline.create":
            return self._create_outline(parsed)
        if operation == "pptx.create.from-markdown":
            return self._create_from_markdown(parsed)
        if operation == "pptx.create.from-html":
            return self._create_from_html(parsed)
        return execute_pptx_edit(parsed, self.schemas, self.dotnet)

    def _read(self, request: ParsedPptxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        source = file_record(request.input_path, "input")
        operation_result, warnings = read_pptx(request.input_path, request.arguments)
        assert_source_preserved(source.path, source.sha256)
        return success_result(
            request,
            artifacts=[source.as_dict()],
            operation_result=operation_result,
            warnings=warnings,
            validation=read_validation("operation.structured-read", operation_result),
        )

    def _inspect(self, request: ParsedPptxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        source = file_record(request.input_path, "input")
        operation_result, warnings = inspect_pptx(request.input_path, request.arguments)
        assert_source_preserved(source.path, source.sha256)
        return success_result(
            request,
            artifacts=[source.as_dict()],
            operation_result=operation_result,
            warnings=warnings,
            validation=read_validation("operation.inert-inspection", operation_result),
        )

    def _create(self, request: ParsedPptxRequest) -> dict[str, Any]:
        assert request.output_path is not None
        deck = request.arguments["deck"]
        template_path = request.arguments.get("template")
        template_source = None
        if template_path is not None:
            assert_distinct_paths(template_path, request.output_path, in_place=False)
            template_source = file_record(template_path, "input")
        destination = destination_snapshot(request.output_path)
        with OperationTempRoot() as private_root:
            staged = private_root / "created.pptx"
            creation = create_pptx(staged, deck, template=template_path)
            validation = validate_created(staged, deck, creation)
            validation = with_schema_gate(
                validation,
                validate_schema_gate(staged, self.dotnet),
            )
            operation_result = {"creation": creation}
            result = write_candidate_result(
                self.schemas,
                request,
                staged,
                validation,
                operation_result,
                warnings=[],
                source=template_source,
            )
            return promote_candidate(
                request,
                staged,
                result,
                source=template_source,
                destination=destination,
            )

    def _create_outline(self, request: ParsedPptxRequest) -> dict[str, Any]:
        assert request.output_path is not None
        destination = destination_snapshot(request.output_path)
        with OperationTempRoot() as private_root:
            staged = private_root / "outline.json"
            plan = write_outline(staged, request.arguments)
            result = write_candidate_result(
                self.schemas,
                request,
                staged,
                outline_validation(staged, plan),
                {
                    "artifact_type": "planning-json",
                    "presentation_generated": False,
                    "slides": len(plan["slides"]),
                },
                warnings=[],
                source=None,
            )
            return promote_candidate(
                request,
                staged,
                result,
                source=None,
                destination=destination,
            )

    def _create_from_markdown(self, request: ParsedPptxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        assert request.output_path is not None
        source = file_record(request.input_path, "input")
        destination = destination_snapshot(request.output_path)
        try:
            with OperationTempRoot() as private_root:
                raw_deck, reconstruction = parse_markdown_deck(
                    request.input_path,
                    request.arguments,
                )
                deck = parse_deck(raw_deck)
                staged = private_root / "created-from-markdown.pptx"
                creation = create_pptx(
                    staged,
                    deck,
                    template=request.arguments.get("template"),
                )
                validation = validate_created(staged, deck, creation)
                validation = with_schema_gate(
                    validation,
                    validate_schema_gate(staged, self.dotnet),
                )
                result = write_candidate_result(
                    self.schemas,
                    request,
                    staged,
                    validation,
                    {
                        "creation": creation,
                        "reconstruction": reconstruction,
                    },
                    warnings=[{
                        "code": "PPTX_MARKDOWN_SEMANTIC_RECONSTRUCTION",
                        "message": "Markdown semantics were reconstructed; source visual styling was not preserved.",
                    }],
                    source=source,
                )
                return promote_candidate(
                    request,
                    staged,
                    result,
                    source=source,
                    destination=destination,
                )
        except Exception as error:
            merge_source_preservation_failure(error, source.path, source.sha256)
            raise

    def _create_from_html(self, request: ParsedPptxRequest) -> dict[str, Any]:
        assert request.input_path is not None
        assert request.output_path is not None
        if self.html_browser_detector is None:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "HTML browser provider is unavailable.",
                status="unavailable",
            )
        source = file_record(request.input_path, "input")
        destination = destination_snapshot(request.output_path)
        started = time.monotonic()
        base = self.project_root / ".document-skills-tmp" / "document-skills-operations"
        try:
            with OperationTempRoot(base=base) as private_root:
                capture_started = time.monotonic()
                captured = HtmlDeckCapture(
                    self.project_root,
                    self.html_browser_detector,
                ).capture(
                    request.input_path,
                    private_root,
                    request.arguments["fallback_policy"],
                    capture_visuals=_visual_validation_available(self.libreoffice),
                )
                capture_ms = int((time.monotonic() - capture_started) * 1000)
                normalize_started = time.monotonic()
                normalized = normalize_scene(captured)
                normalize_ms = int((time.monotonic() - normalize_started) * 1000)
                staged = private_root / "created-from-html.pptx"
                emission_started = time.monotonic()
                emission = emit_scene_pptx(
                    staged,
                    normalized,
                    request.arguments["metadata"],
                )
                emission_ms = int((time.monotonic() - emission_started) * 1000)
                validation_started = time.monotonic()
                validation = validate_scene_created(staged, normalized, emission)
                validation = with_schema_gate(
                    validation,
                    validate_schema_gate(staged, self.dotnet),
                )
                visual_gate = validate_scene_visuals(
                    staged,
                    normalized,
                    self.libreoffice,
                    private_root,
                )
                validation = with_visual_gate(validation, visual_gate)
                validation_ms = int((time.monotonic() - validation_started) * 1000)
                outcomes = normalized.diagnostics["outcomes"]
                fidelity_degraded = (
                    outcomes.get("approximated", 0) > 0
                    or outcomes.get("rasterized", 0) > 0
                )
                visual_degraded = visual_gate["outcome"] != "pass"
                degraded = fidelity_degraded or visual_degraded
                operation_result = {
                    "input": {
                        "canvas": {"width": 1920, "height": 1080},
                        "slides": len(normalized.slides),
                    },
                    "conversion": normalized.diagnostics,
                    "emission": {
                        key: value for key, value in emission.items() if key != "items"
                    },
                    "manifest": {
                        "items": emission["items"][:64],
                        "truncated": max(0, len(emission["items"]) - 64),
                    },
                    "validation": {
                        "status": validation["status"],
                        "gates": [
                            {
                                "id": gate["id"],
                                "outcome": gate["outcome"],
                                "required": gate["required"],
                            }
                            for gate in validation["gates"]
                        ],
                    },
                    "timing_ms": {
                        "capture": capture_ms,
                        "normalize": normalize_ms,
                        "emission": emission_ms,
                        "validation": validation_ms,
                        "total": int((time.monotonic() - started) * 1000),
                    },
                }
                degradations = []
                if fidelity_degraded:
                    degradations.append({
                        "code": "HTML_FIDELITY_FALLBACK",
                        "semantic_difference": "Some source items were approximated or rasterized as declared by diagnostics.",
                        "missing_capabilities": [],
                        "recommended_providers": [],
                    })
                if visual_degraded:
                    degradations.append({
                        "code": "HTML_VISUAL_PARITY_UNESTABLISHED",
                        "semantic_difference": "Optional visual parity was unavailable or outside the declared thresholds.",
                        "missing_capabilities": (
                            ["libreoffice.render-image"]
                            if visual_gate["outcome"] == "unavailable"
                            else []
                        ),
                        "recommended_providers": (
                            ["libreoffice"]
                            if visual_gate["outcome"] == "unavailable"
                            else []
                        ),
                    })
                result = write_candidate_result(
                    self.schemas,
                    request,
                    staged,
                    validation,
                    operation_result,
                    warnings=[],
                    source=source,
                    status="degraded" if degraded else "success",
                    degraded=degraded,
                    degradations=degradations,
                )
                return promote_candidate(
                    request,
                    staged,
                    result,
                    source=source,
                    destination=destination,
                )
        except Exception as error:
            merge_source_preservation_failure(error, source.path, source.sha256)
            raise


def build_pptx_service(
    project_root: Path,
    libreoffice=None,
    dotnet=None,
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    service = PptxService(project_root, libreoffice=libreoffice, dotnet=dotnet)
    return service.execute


def build_html_pptx_service(
    project_root: Path,
    html_browser_detector: Any,
    libreoffice=None,
    dotnet=None,
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    service = PptxService(
        project_root,
        libreoffice=libreoffice,
        html_browser_detector=html_browser_detector,
        dotnet=dotnet,
    )
    return service.execute


def _visual_validation_available(provider: Any) -> bool:
    if provider is None or not hasattr(provider, "detect"):
        return False
    try:
        return provider.detect().available is True
    except Exception:
        return False
