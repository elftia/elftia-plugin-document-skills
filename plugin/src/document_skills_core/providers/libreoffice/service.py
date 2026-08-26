"""LibreOffice provider dispatcher and injectable factory.

Exposes ``build_libreoffice_provider(...)`` returning a
``(ProviderDefinition, LibreOfficeProvider)`` pair. The ProviderDefinition is
registered in the catalog; the LibreOfficeProvider is the consultation object
passed to format services.

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
from ...core.process import ProcessPolicy
from ...formats.pptx.render_operations import execute_pptx_libreoffice_operation
from ...formats.xlsx.render_operation import execute_render
from .constants import TIMEOUT_RECALC_OPTIONAL, TIMEOUT_RECALC_REQUIRED
from .convert import convert_snapshot_to_pdf, convert_to_pdf
from .detector import LibreOfficeDetector
from .legacy import read_or_convert_legacy
from .quota import HardQuotaBackend
from .recalc import (
    RecalculatedXlsx,
    recalculate_xlsx,
    recalculate_xlsx_artifact,
    recalculate_xlsx_snapshot_artifact,
)
from .render import render_to_image
from .runner import LibreOfficeRunner


class LibreOfficeProvider:
    """Wraps detector + runner; provides consultation methods for format services."""

    def __init__(
        self,
        project_root: Path,
        detector: LibreOfficeDetector | None = None,
        runner: LibreOfficeRunner | None = None,
        *,
        quota_backend: HardQuotaBackend | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.detector = detector or LibreOfficeDetector(
            project_root,
            quota_backend=quota_backend,
        )
        self.runner = runner or LibreOfficeRunner(
            project_root,
            quota_backend=quota_backend,
        )

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

    def _detect_for_operation(self) -> DetectionEvidence:
        if isinstance(self.detector, LibreOfficeDetector):
            return self.detector.detect_and_authorize(self.runner.set_executable)
        evidence = self.detector.detect()
        if evidence.available and evidence.path:
            self.runner.set_executable(evidence.path)
        return evidence

    def execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a provider-execute call to the appropriate operation."""
        try:
            return self._dispatch(operation, request)
        except DocumentSkillsError as error:
            options = request.get("options", {})
            requested_fidelity = (
                options.get("fidelity", "core")
                if type(options) is dict
                else "unknown"
            )
            return make_error_result(
                operation,
                error,
                requested_fidelity=requested_fidelity,
            )

    def _dispatch(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        evidence = self._detect_for_operation()
        if not evidence.available:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "LibreOffice is not callable.",
            )
        if operation == "libreoffice.recalc-xlsx":
            return self._do_recalc(Path(request["input"]))
        if operation == "libreoffice.convert-pdf":
            return self._do_convert_pdf(Path(request["input"]))
        if operation == "libreoffice.render-image":
            return self._do_render(Path(request["input"]))
        if operation == "libreoffice.read-legacy":
            return self._do_legacy(Path(request["input"]), request.get("target_format"))
        if operation == "xlsx.render":
            return self._do_xlsx_render(request)
        if operation in {"pptx.convert.legacy", "pptx.convert.pdf", "pptx.render"}:
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
        try:
            evidence = self._detect_for_operation()
            if not evidence.available:
                return None
            return recalculate_xlsx(
                input_path,
                self.runner,
                timeout_seconds=TIMEOUT_RECALC_OPTIONAL,
            )
        except DocumentSkillsError:
            return None

    def recalculate_xlsx_artifact(
        self,
        input_path: Path,
        *,
        policy: str,
    ) -> RecalculatedXlsx:
        """Require a callable provider and return its isolated recalculated artifact."""

        evidence = self._detect_for_operation()
        if not evidence.available:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "LibreOffice recalculation is unavailable.",
                status="unavailable",
                details={"reason": evidence.reason or "unavailable"},
            )
        return recalculate_xlsx_artifact(
            input_path,
            self.runner,
            timeout_seconds=_recalculation_timeout(policy),
        )

    def recalculate_screened_xlsx_artifact(
        self,
        input_snapshot: Path,
        *,
        policy: str,
    ) -> RecalculatedXlsx:
        """Recalculate the caller's already screened private XLSX snapshot."""

        evidence = self._detect_for_operation()
        if not evidence.available:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "LibreOffice recalculation is unavailable.",
                status="unavailable",
                details={"reason": evidence.reason or "unavailable"},
            )
        return recalculate_xlsx_snapshot_artifact(
            input_snapshot,
            self.runner,
            timeout_seconds=_recalculation_timeout(policy),
        )

    def try_convert_to_pdf(self, input_path: Path) -> bytes | None:
        """Consult LibreOffice for Office-to-PDF conversion. Returns PDF bytes."""
        try:
            return self.convert_pdf(input_path)
        except DocumentSkillsError:
            return None

    def convert_pdf(
        self,
        input_path: Path,
        max_output_bytes: int = 64 * 1024 * 1024,
    ) -> bytes:
        """Strict conversion path used by public format services."""

        evidence = self._detect_for_operation()
        if not evidence.available:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "LibreOffice is not callable.",
                status="unavailable",
            )
        return convert_to_pdf(
            input_path,
            self.runner,
            max_output_bytes=max_output_bytes,
        )

    def try_render_to_image(self, input_path: Path) -> bytes | None:
        """Consult LibreOffice for DOCX/PPTX render. Returns image bytes."""
        try:
            evidence = self._detect_for_operation()
            if not evidence.available:
                return None
            return render_to_image(input_path, self.runner)
        except DocumentSkillsError:
            return None

    def try_read_legacy(
        self, input_path: Path, target_format: str | None = None
    ) -> bytes | None:
        """Consult LibreOffice for legacy format read/convert. Returns file bytes."""
        try:
            evidence = self._detect_for_operation()
            if not evidence.available:
                return None
            return read_or_convert_legacy(input_path, self.runner, target_format=target_format)
        except DocumentSkillsError:
            return None

    def convert_legacy_required(
        self,
        input_path: Path,
        *,
        target_format: str,
    ) -> bytes:
        """Require LibreOffice for a legacy conversion and preserve typed failures."""

        evidence = self._detect_for_operation()
        if not evidence.available:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "LibreOffice legacy conversion is unavailable.",
                status="unavailable",
                details={"reason": evidence.reason or "unavailable"},
            )
        return read_or_convert_legacy(
            input_path,
            self.runner,
            target_format=target_format,
        )

    def convert_legacy(
        self,
        input_path: Path,
        target_format: str,
        max_output_bytes: int = 64 * 1024 * 1024,
    ) -> bytes:
        """Strict legacy DOC conversion used by the public DOCX service."""

        evidence = self._detect_for_operation()
        if not evidence.available:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "LibreOffice is not callable.",
                status="unavailable",
            )
        return read_or_convert_legacy(
            input_path,
            self.runner,
            target_format=target_format,
            max_output_bytes=max_output_bytes,
        )

    def _do_recalc(self, input_path: Path) -> dict[str, Any]:
        cached_values = recalculate_xlsx(
            input_path,
            self.runner,
            timeout_seconds=TIMEOUT_RECALC_REQUIRED,
        )
        return _build_success(
            "libreoffice.recalc-xlsx",
            diagnostics={"cached_values": cached_values},
        )

    def _do_convert_pdf(self, input_path: Path) -> dict[str, Any]:
        pdf_bytes = self.convert_pdf(input_path)
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

    def _do_xlsx_render(self, request: dict[str, Any]) -> dict[str, Any]:
        return execute_render(
            request,
            project_root=self.project_root,
            converter=lambda path: convert_snapshot_to_pdf(path, self.runner),
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


def _recalculation_timeout(policy: str) -> float:
    if policy == "auto":
        return TIMEOUT_RECALC_OPTIONAL
    if policy == "required":
        return TIMEOUT_RECALC_REQUIRED
    raise ValueError("Recalculation provider policy must be auto or required.")


def build_libreoffice_provider(
    project_root: Path,
    detector: LibreOfficeDetector | None = None,
    runner: LibreOfficeRunner | None = None,
    *,
    quota_backend: HardQuotaBackend | None = None,
) -> tuple[ProviderDefinition, LibreOfficeProvider]:
    """Build the callable LibreOffice provider definition + consultation object.

    The ProviderDefinition is registered in the catalog; the LibreOfficeProvider
    is passed to format services for consultation. Both detector and runner are
    injectable for mock-injected tests.
    """
    policy = ProcessPolicy(project_root.resolve())
    provider = LibreOfficeProvider(
        project_root,
        detector=detector
        or LibreOfficeDetector(
            project_root,
            policy=policy,
            quota_backend=quota_backend,
        ),
        runner=runner
        or LibreOfficeRunner(
            project_root,
            policy=policy,
            quota_backend=quota_backend,
        ),
        quota_backend=quota_backend,
    )
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
            Capability("xlsx.render", "enhanced", validation_strength=3),
            Capability("pptx.convert.pdf", "enhanced", validation_strength=3),
            Capability("pptx.convert.legacy", "enhanced", validation_strength=3),
            Capability("pptx.render", "enhanced", validation_strength=3),
        ],
        diagnostics=provider.diagnostics,
        validators={"visual": provider.try_render_to_image},
        required=False,
    )
    return definition, provider
