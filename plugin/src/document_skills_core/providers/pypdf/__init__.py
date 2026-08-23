"""Accepted pypdf provider definition."""

from pathlib import Path

from document_skills_core.core.capabilities import Capability, Provider, ProviderId

from .detector import (
    EXPECTED_PYPDF_VERSION,
    detect_pypdf,
    pypdf_diagnostics,
)
from .service import build_pypdf_service


def build_pypdf_provider(project_root: Path) -> Provider:
    return Provider(
        id=ProviderId.PYPDF,
        version=EXPECTED_PYPDF_VERSION,
        detect=detect_pypdf,
        execute=build_pypdf_service(project_root),
        diagnostics=pypdf_diagnostics,
        capabilities=[
            Capability("pdf.encrypt", "enhanced", validation_strength=3),
            Capability("pdf.decrypt", "enhanced", validation_strength=3),
            Capability("pdf.compress", "enhanced", validation_strength=3),
        ],
        startup_cost=1,
        risk=1,
        required=False,
    )


__all__ = ["build_pypdf_provider"]
