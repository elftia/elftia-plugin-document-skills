"""Optional callable Poppler and Poppler-plus-Tesseract providers."""

from pathlib import Path

from document_skills_core.core.capabilities import Capability, Provider, ProviderId

from .detector import PdfToolDetector
from .service import PdfToolService


def build_pdf_tool_providers(project_root: Path) -> tuple[Provider, Provider]:
    render_detector = PdfToolDetector(project_root, require_tesseract=False)
    ocr_detector = PdfToolDetector(project_root, require_tesseract=True)
    render_service = PdfToolService(
        project_root,
        operation="pdf.render",
        detector=render_detector,
    )
    ocr_service = PdfToolService(
        project_root,
        operation="pdf.ocr",
        detector=ocr_detector,
    )
    return (
        Provider(
            id=ProviderId.POPPLER,
            version=None,
            detect=render_detector.detect,
            execute=render_service.execute,
            diagnostics=render_detector.diagnostics,
            capabilities=[
                Capability("pdf.render", "enhanced", validation_strength=3)
            ],
            startup_cost=2,
            risk=2,
            required=False,
        ),
        Provider(
            id=ProviderId.TESSERACT_OCR,
            version=None,
            detect=ocr_detector.detect,
            execute=ocr_service.execute,
            diagnostics=ocr_detector.diagnostics,
            capabilities=[
                Capability("pdf.ocr", "enhanced", validation_strength=3)
            ],
            startup_cost=3,
            risk=2,
            required=False,
        ),
    )


__all__ = ["build_pdf_tool_providers"]
