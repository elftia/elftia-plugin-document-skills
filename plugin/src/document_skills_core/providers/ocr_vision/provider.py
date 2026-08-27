"""Unavailable-by-default OCR/vision provider definition."""

from pathlib import Path
from typing import Any, Protocol

from document_skills_core.core.capabilities import (
    Capability,
    DetectionEvidence,
    Provider,
    ProviderId,
)
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pptx.reconstruction_service import (
    build_reconstruction_service,
)


class ObservationAdapter(Protocol):
    def detect(self) -> DetectionEvidence | dict[str, Any]: ...

    def observe(self, source: Path) -> dict[str, Any]: ...


class _UnavailableObservationAdapter:
    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(False, reason="ocr-vision adapter is not configured")

    def observe(self, source: Path) -> dict[str, Any]:
        del source
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "OCR/vision provider is unavailable.",
            status="unavailable",
        )


def build_ocr_vision_provider(
    project_root: Path,
    adapter: ObservationAdapter | None = None,
    *,
    dotnet: Any = None,
) -> Provider:
    effective = adapter or _UnavailableObservationAdapter()
    execute = build_reconstruction_service(
        project_root,
        effective,
        dotnet=dotnet,
    )

    return Provider(
        id=ProviderId.OCR_VISION,
        version=None,
        detect=effective.detect,
        execute=execute,
        capabilities=[
            Capability(
                "pptx.reconstruct.from-image",
                "core",
                validation_strength=3,
            )
        ],
        startup_cost=2,
        risk=2,
        required=False,
    )
