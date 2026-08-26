"""Foundation providers; optional descriptors register no unimplemented operations."""

import os
from pathlib import Path

from document_skills_core import __version__
from document_skills_core.core.capabilities import (
    Capability,
    DetectionEvidence,
    Provider,
    ProviderCatalog,
    ProviderId,
)
from document_skills_core.core.capabilities.detectors import RuntimeDetectors
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.docx.service import build_docx_service
from document_skills_core.formats.pdf.service import build_pdf_service
from document_skills_core.formats.pptx.service import build_pptx_service
from document_skills_core.formats.xlsx.service import build_xlsx_service
from document_skills_core.providers.dotnet import build_dotnet_provider
from document_skills_core.providers.libreoffice import build_libreoffice_provider
from document_skills_core.providers.html_browser.provider import build_html_browser_provider

_XLSX_CORE_ONLY_ENV = "DOCUMENT_SKILLS_XLSX_CORE_ONLY"
_PROVIDER_PROFILE_ENV = "DOCUMENT_SKILLS_PROVIDER_PROFILE"
_CORE_ONLY_PROFILE = "core-only"


class _DisabledOptionalDetector:
    """Return explicit unavailable evidence without probing the host machine."""

    def __init__(self, provider_id: str) -> None:
        self._provider_id = provider_id

    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(
            available=False,
            reason=(
                f"{self._provider_id} is disabled by "
                f"{_PROVIDER_PROFILE_ENV}={_CORE_ONLY_PROFILE}"
            ),
        )


def _provider_core_only_enabled() -> bool:
    value = os.environ.get(_PROVIDER_PROFILE_ENV)
    if value is None:
        return False
    if value == _CORE_ONLY_PROFILE:
        return True
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        f"{_PROVIDER_PROFILE_ENV} must be unset or '{_CORE_ONLY_PROFILE}'.",
        status="invalid_request",
        details={
            "setting": _PROVIDER_PROFILE_ENV,
            "allowed_values": [_CORE_ONLY_PROFILE],
        },
    )


def _optional_detector(provider_id: str) -> _DisabledOptionalDetector | None:
    if _provider_core_only_enabled():
        return _DisabledOptionalDetector(provider_id)
    return None


def _xlsx_core_only_enabled() -> bool:
    value = os.environ.get(_XLSX_CORE_ONLY_ENV)
    if value is None or value == "0":
        return False
    if value == "1":
        return True
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        f"{_XLSX_CORE_ONLY_ENV} must be unset, '0', or '1'.",
        status="invalid_request",
        details={
            "setting": _XLSX_CORE_ONLY_ENV,
            "allowed_values": ["0", "1"],
        },
    )


def _build_composite_execute(docx_service, xlsx_service, pptx_service, pdf_service):
    """Dispatch to the correct format service based on the operation identifier."""
    def execute(operation: str, request: dict) -> dict:
        if operation.startswith("pdf."):
            return pdf_service(operation, request)
        if operation.startswith("xlsx."):
            return xlsx_service(operation, request)
        if operation.startswith("pptx."):
            return pptx_service(operation, request)
        return docx_service(operation, request)
    return execute


def _build_optional_execute(docx_service, provider_execute):
    """Route public DOCX operations through the format service."""

    def execute(operation: str, request: dict) -> dict:
        if operation.startswith("docx."):
            return docx_service(operation, request)
        return provider_execute(operation, request)

    return execute


def build_default_registry(project_root: Path) -> ProviderCatalog:
    xlsx_core_only = _xlsx_core_only_enabled()
    provider_core_only = _provider_core_only_enabled()
    detectors = RuntimeDetectors(project_root)
    registry = ProviderCatalog()
    libreoffice_def, libreoffice_provider = build_libreoffice_provider(
        project_root,
        detector=_optional_detector("libreoffice"),
    )
    dotnet_def, dotnet_provider = build_dotnet_provider(
        project_root,
        detector=_optional_detector("dotnet-openxml"),
    )
    html_browser_provider = build_html_browser_provider(
        project_root,
        libreoffice=libreoffice_provider,
        dotnet=dotnet_provider,
    )
    docx_service = build_docx_service(
        project_root, libreoffice=libreoffice_provider, dotnet=dotnet_provider,
    )
    if libreoffice_def.execute is None or dotnet_def.execute is None:
        raise RuntimeError("Optional provider definitions must be executable.")
    libreoffice_def.execute = _build_optional_execute(
        docx_service,
        libreoffice_def.execute,
    )
    libreoffice_def.capabilities = [*libreoffice_def.capabilities,
        Capability("docx.convert.legacy", "enhanced", validation_strength=3),
        Capability("docx.convert.pdf", "enhanced", validation_strength=3),
        Capability("docx.render", "enhanced", validation_strength=3),
        Capability("docx.layout.repair", "enhanced", validation_strength=3),
        Capability("docx.compare.visual", "enhanced", validation_strength=3),
    ]
    dotnet_def.execute = _build_optional_execute(docx_service, dotnet_def.execute)
    dotnet_def.capabilities = [*dotnet_def.capabilities,
        Capability("docx.revisions.read", "enhanced", validation_strength=2),
        Capability("docx.revisions.apply", "enhanced", validation_strength=2),
        Capability("docx.comments.read", "enhanced", validation_strength=2),
        Capability("docx.comments.add", "enhanced", validation_strength=2),
        Capability("docx.comments.resolve", "enhanced", validation_strength=2),
        Capability("docx.validate.schema", "enhanced", validation_strength=3),
    ]
    xlsx_service = build_xlsx_service(
        project_root,
        libreoffice=(
            None if xlsx_core_only or provider_core_only else libreoffice_provider
        ),
    )
    pptx_service = build_pptx_service(
        project_root,
        libreoffice=libreoffice_provider,
        dotnet=dotnet_provider,
    )
    pdf_service = build_pdf_service(project_root, libreoffice=libreoffice_provider)
    composite_execute = _build_composite_execute(docx_service, xlsx_service, pptx_service, pdf_service)
    registry.register_provider(
        Provider(
            id=ProviderId.CORE_PYTHON,
            version=__version__,
            detect=lambda: DetectionEvidence(True, version=__version__),
            execute=composite_execute,
            capabilities=[
                Capability("docx.read", "core", validation_strength=2),
                Capability(
                    "docx.inspect.accessibility",
                    "core",
                    validation_strength=2,
                ),
                Capability("docx.inspect.structure", "core", validation_strength=2),
                Capability("docx.compare.semantic", "core", validation_strength=2),
                Capability("docx.create", "core", validation_strength=2),
                Capability("docx.edit", "core", validation_strength=2),
                Capability("docx.edit.replace-text", "core", validation_strength=2),
                Capability("docx.merge", "core", validation_strength=2),
                Capability("xlsx.read", "core", validation_strength=2),
                Capability("xlsx.inspect.structure", "core", validation_strength=2),
                Capability("xlsx.create", "core", validation_strength=2),
                Capability("xlsx.edit", "core", validation_strength=2),
                Capability("xlsx.recalculate", "core", validation_strength=2),
                Capability("xlsx.convert", "core", validation_strength=2),
                Capability("xlsx.template.instantiate", "core", validation_strength=2),
                Capability("xlsx.summary.aggregate", "core", validation_strength=2),
                Capability("xlsx.pivot.create", "core", validation_strength=2),
                Capability("pptx.read", "core", validation_strength=2),
                Capability("pptx.inspect.structure", "core", validation_strength=2),
                Capability("pptx.outline.create", "core", validation_strength=2),
                Capability("pptx.create", "core", validation_strength=2),
                Capability("pptx.create.from-markdown", "core", validation_strength=2),
                Capability("pptx.create.from-svg", "core", validation_strength=3),
                Capability("pptx.create.from-template", "core", validation_strength=3),
                Capability("pptx.scene.export", "core", validation_strength=3),
                Capability("pptx.template.inspect", "core", validation_strength=2),
                Capability("pptx.template.sanitize", "core", validation_strength=3),
                Capability("pptx.edit", "core", validation_strength=2),
                Capability("pdf.read", "core", validation_strength=2),
                Capability("pdf.inspect.structure", "core", validation_strength=2),
                Capability("pdf.create", "core", validation_strength=2),
                Capability("pdf.edit", "core", validation_strength=2),
                Capability("pdf.rewrite.apply", "core", validation_strength=2),
            ],
            required=True,
        )
    )
    registry.register_provider(
        Provider(
            id=ProviderId.CORE_NODE,
            version=None,
            detect=detectors.detect_node_provider,
            execute=docx_service,
            capabilities=[
                Capability("docx.template.apply", "core", validation_strength=2)
            ],
            startup_cost=1,
            required=True,
        )
    )
    registry.register_provider(libreoffice_def)
    registry.register_provider(dotnet_def)
    registry.register_provider(html_browser_provider)
    return registry
