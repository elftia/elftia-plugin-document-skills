"""Provider definition for the optional browser-backed PPTX operation."""

from pathlib import Path

from document_skills_core.core.capabilities import Capability, Provider, ProviderId
from document_skills_core.formats.pptx.service import build_html_pptx_service

from .detector import HtmlBrowserDetector


def build_html_browser_provider(
    project_root: Path,
    libreoffice=None,
    dotnet=None,
) -> Provider:
    detector = HtmlBrowserDetector(project_root)
    return Provider(
        id=ProviderId.HTML_BROWSER,
        version=None,
        detect=detector.detect,
        execute=build_html_pptx_service(
            project_root,
            detector,
            libreoffice=libreoffice,
            dotnet=dotnet,
        ),
        capabilities=[
            Capability(
                "pptx.create.from-html",
                "core",
                validation_strength=2,
            )
        ],
        startup_cost=2,
        risk=1,
        required=False,
    )
