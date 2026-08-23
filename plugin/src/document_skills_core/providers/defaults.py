"""Foundation providers; optional descriptors register no unimplemented operations."""

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
from document_skills_core.formats.docx.service import build_docx_service
from document_skills_core.formats.pdf.service import build_pdf_service
from document_skills_core.formats.pptx.service import build_pptx_service
from document_skills_core.formats.xlsx.service import build_xlsx_service
from document_skills_core.providers.dotnet import build_dotnet_provider
from document_skills_core.providers.libreoffice import build_libreoffice_provider
from document_skills_core.providers.html_browser.provider import build_html_browser_provider


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
    detectors = RuntimeDetectors(project_root)
    registry = ProviderCatalog()
    libreoffice_def, libreoffice_provider = build_libreoffice_provider(project_root)
    dotnet_def, dotnet_provider = build_dotnet_provider(project_root)
    html_browser_provider = build_html_browser_provider(
        project_root,
        libreoffice=libreoffice_provider,
        dotnet=dotnet_provider,
    )
    docx_service = build_docx_service(
        project_root, libreoffice=libreoffice_provider, dotnet=dotnet_provider,
    )
    xlsx_service = build_xlsx_service(project_root, libreoffice=libreoffice_provider)
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
                Capability("docx.inspect.structure", "core", validation_strength=2),
                Capability("docx.create", "core", validation_strength=2),
                Capability("docx.edit.replace-text", "core", validation_strength=2),
                Capability("xlsx.read", "core", validation_strength=2),
                Capability("xlsx.inspect.structure", "core", validation_strength=2),
                Capability("xlsx.create", "core", validation_strength=2),
                Capability("xlsx.edit", "core", validation_strength=2),
                Capability("pptx.read", "core", validation_strength=2),
                Capability("pptx.inspect.structure", "core", validation_strength=2),
                Capability("pptx.outline.create", "core", validation_strength=2),
                Capability("pptx.create", "core", validation_strength=2),
                Capability("pptx.create.from-markdown", "core", validation_strength=2),
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
