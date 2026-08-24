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


def build_default_registry(project_root: Path) -> ProviderCatalog:
    xlsx_core_only = _xlsx_core_only_enabled()
    detectors = RuntimeDetectors(project_root)
    registry = ProviderCatalog()
    libreoffice_def, libreoffice_provider = build_libreoffice_provider(project_root)
    dotnet_def, dotnet_provider = build_dotnet_provider(project_root)
    html_browser_provider = build_html_browser_provider(
        project_root,
        libreoffice=libreoffice_provider,
    )
    docx_service = build_docx_service(
        project_root, libreoffice=libreoffice_provider, dotnet=dotnet_provider,
    )
    xlsx_service = build_xlsx_service(
        project_root,
        libreoffice=None if xlsx_core_only else libreoffice_provider,
    )
    pptx_service = build_pptx_service(project_root, libreoffice=libreoffice_provider)
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
                Capability("docx.inspect.structure", "core", validation_strength=2),
                Capability("docx.create", "core", validation_strength=2),
                Capability("docx.edit.replace-text", "core", validation_strength=2),
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
                Capability("pptx.create", "core", validation_strength=2),
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
