"""LibreOffice provider dispatcher and injectable factory.

Exposes ``build_libreoffice_provider(project_root, detector=None, runner=None)``
returning a ``(ProviderDefinition, LibreOfficeProvider)`` pair. The
ProviderDefinition is registered in the catalog; the LibreOfficeProvider
is the consultation object passed to format services.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from ...core.capabilities.catalog import (
    Capability,
    DetectionEvidence,
    ProviderDefinition,
    ProviderId,
)
from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.contracts.models import make_error_result
from ...formats.pptx.render_operations import execute_pptx_libreoffice_operation
from .convert import convert_to_pdf
from .detector import LibreOfficeDetector
from .legacy import read_or_convert_legacy
from .recalc import recalculate_xlsx
from .render import render_to_image
from .runner import LibreOfficeRunner


class LibreOfficeProvider:
    """Wraps detector + runner; provides consultation methods for format services."""

    def __init__(
        self,
        project_root: Path,
        detector: LibreOfficeDetector | None = None,
        runner: LibreOfficeRunner | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.detector = detector or LibreOfficeDetector(project_root)
        self.runner = runner or LibreOfficeRunner(project_root)

    def detect(self) -> DetectionEvidence:
        return self.detector.detect()

    def diagnostics(self) -> dict[str, Any]:
        evidence = self.detector.detect()
        if evidence.available:
            return {"path": evidence.path, "version": evidence.version}
        return {
            "path": None,
            "version": None,
            "reason": evidence.reason or "unavailable",
        }

    def execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a provider-execute call to the appropriate operation."""
        try:
            return self._dispatch(operation, request)
        except DocumentSkillsError as error:
            return make_error_result(operation, error, requested_fidelity="enhanced")

    def _dispatch(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        evidence = self.detector.detect()
        if not evidence.available:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "LibreOffice is not callable.",
            )
        if evidence.path:
            self.runner.set_executable(evidence.path)
        if operation == "libreoffice.recalc-xlsx":
            return self._do_recalc(Path(request["input"]))
        if operation == "libreoffice.convert-pdf":
            return self._do_convert_pdf(Path(request["input"]))
        if operation == "libreoffice.render-image":
            return self._do_render(Path(request["input"]))
        if operation == "libreoffice.read-legacy":
            return self._do_legacy(Path(request["input"]), request.get("target_format"))
        if operation in {"pptx.convert.pdf", "pptx.render"}:
            return execute_pptx_libreoffice_operation(
                operation,
                request,
                self.runner,
                project_root=self.project_root,
                version=evidence.version,
            )
        raise DocumentSkillsError(
            ErrorCode.OPERATION_UNKNOWN,
            f"Unknown LibreOffice operation: {operation}",
        )

    def try_recalc_xlsx(self, input_path: Path) -> dict[str, Any] | None:
        """Consult LibreOffice for XLSX recalculation. Returns cached values or None."""
        evidence = self.detector.detect()
        if not evidence.available:
            return None
        try:
            if evidence.path:
                self.runner.set_executable(evidence.path)
            return recalculate_xlsx(input_path, self.runner)
        except DocumentSkillsError:
            return None

    def try_convert_to_pdf(self, input_path: Path) -> bytes | None:
        """Consult LibreOffice for Office-to-PDF conversion. Returns PDF bytes."""
        evidence = self.detector.detect()
        if not evidence.available:
            return None
        try:
            if evidence.path:
                self.runner.set_executable(evidence.path)
            return convert_to_pdf(input_path, self.runner)
        except DocumentSkillsError:
            return None

    def try_render_to_image(self, input_path: Path) -> bytes | None:
        """Consult LibreOffice for DOCX/PPTX render. Returns image bytes."""
        evidence = self.detector.detect()
        if not evidence.available:
            return None
        try:
            if evidence.path:
                self.runner.set_executable(evidence.path)
            return render_to_image(input_path, self.runner)
        except DocumentSkillsError:
            return None

    def try_read_legacy(
        self, input_path: Path, target_format: str | None = None
    ) -> bytes | None:
        """Consult LibreOffice for legacy format read/convert. Returns file bytes."""
        evidence = self.detector.detect()
        if not evidence.available:
            return None
        try:
            if evidence.path:
                self.runner.set_executable(evidence.path)
            return read_or_convert_legacy(input_path, self.runner, target_format=target_format)
        except DocumentSkillsError:
            return None

    def _do_recalc(self, input_path: Path) -> dict[str, Any]:
        cached_values = recalculate_xlsx(input_path, self.runner)
        return _build_success(
            "libreoffice.recalc-xlsx",
            diagnostics={"cached_values": cached_values},
        )

    def _do_convert_pdf(self, input_path: Path) -> dict[str, Any]:
        pdf_bytes = convert_to_pdf(input_path, self.runner)
        return _build_success(
            "libreoffice.convert-pdf",
            diagnostics={"output_bytes": len(pdf_bytes)},
        )

    def _do_render(self, input_path: Path) -> dict[str, Any]:
        image_bytes = render_to_image(input_path, self.runner)
        return _build_success(
            "libreoffice.render-image",
            diagnostics={"output_bytes": len(image_bytes)},
        )

    def _do_legacy(self, input_path: Path, target_format: str | None) -> dict[str, Any]:
        legacy_bytes = read_or_convert_legacy(input_path, self.runner, target_format=target_format)
        return _build_success(
            "libreoffice.read-legacy",
            diagnostics={"output_bytes": len(legacy_bytes)},
        )


def _build_success(
    operation: str,
    *,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "success",
        "operation": operation,
        "provider_chain": [],
        "requested_fidelity": "enhanced",
        "achieved_fidelity": "enhanced",
        "degraded": False,
        "degradations": [],
        "artifacts": [],
        "validation": {"gates": []},
        "warnings": [],
        "errors": [],
        "diagnostics": {"libreoffice": diagnostics},
    }


def build_libreoffice_provider(
    project_root: Path,
    detector: LibreOfficeDetector | None = None,
    runner: LibreOfficeRunner | None = None,
) -> tuple[ProviderDefinition, LibreOfficeProvider]:
    """Build the callable LibreOffice provider definition + consultation object.

    The ProviderDefinition is registered in the catalog; the LibreOfficeProvider
    is passed to format services for consultation. Both detector and runner are
    injectable for mock-injected tests.
    """
    provider = LibreOfficeProvider(project_root, detector=detector, runner=runner)
    definition = ProviderDefinition(
        id=ProviderId.LIBREOFFICE,
        version=None,
        detect=provider.detect,
        execute=provider.execute,
        capabilities=[
            Capability("libreoffice.recalc-xlsx", "enhanced", validation_strength=1),
            Capability("libreoffice.convert-pdf", "enhanced", validation_strength=1),
            Capability("libreoffice.render-image", "enhanced", validation_strength=1),
            Capability("libreoffice.read-legacy", "enhanced", validation_strength=1),
            Capability("pptx.convert.pdf", "enhanced", validation_strength=3),
            Capability("pptx.render", "enhanced", validation_strength=3),
        ],
        diagnostics=provider.diagnostics,
        validators={"visual": provider.try_render_to_image},
        required=False,
    )
    return definition, provider
