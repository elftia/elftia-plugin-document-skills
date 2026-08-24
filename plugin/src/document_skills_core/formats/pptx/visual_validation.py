"""Optional thresholded browser-source versus LibreOffice slide validation."""

from pathlib import Path
from typing import Any
from document_skills_core.core.contracts.models import gate_record

from .package import OpcPackage
from .png_compare import compare_png, visual_thresholds
from .scene_normalizer import NormalizedScene
from .slide_render import write_single_slide_candidate


def validate_scene_visuals(
    candidate: Path,
    scene: NormalizedScene,
    provider: Any,
    private_root: Path,
) -> dict[str, Any]:
    evidence = _detection_evidence(provider)
    version = _evidence_version(evidence)
    if evidence is None or evidence.available is not True:
        return _visual_gate(
            "unavailable",
            scene=scene,
            reason="LibreOffice visual validation is unavailable.",
            version=version,
        )
    if not scene.visual_sources:
        return _visual_gate(
            "unavailable",
            scene=scene,
            reason="Browser source screenshots are unavailable.",
            version=version,
        )
    try:
        render_to_image = provider.try_render_to_image
    except AttributeError:
        return _visual_gate(
            "unavailable",
            scene=scene,
            reason="LibreOffice render consultation is unavailable.",
            version=version,
        )
    visual_root = private_root.resolve() / "visual-validation"
    visual_root.mkdir(parents=True, exist_ok=True)
    package = OpcPackage.open(candidate)
    comparisons: list[dict[str, Any]] = []
    try:
        for source in scene.visual_sources:
            slide = source["slide"]
            rendered_candidate = write_single_slide_candidate(
                package,
                slide,
                visual_root / f"slide-{slide}.pptx",
            )
            rendered = render_to_image(rendered_candidate)
            if type(rendered) is not bytes or not rendered:
                return _visual_gate(
                    "fail",
                    scene=scene,
                    reason="libreoffice-render-failed",
                    version=version,
                    comparisons=comparisons,
                )
            asset = scene.assets[source["asset_id"]]
            comparison = compare_png(asset["path"].read_bytes(), rendered)
            comparisons.append({"slide": slide, **comparison})
    except Exception as error:
        return _visual_gate(
            "fail",
            scene=scene,
            reason="visual-comparison-failed",
            version=version,
            comparisons=comparisons,
            reason_category=type(error).__name__,
        )
    passed = all(item["within_thresholds"] is True for item in comparisons)
    return _visual_gate(
        "pass" if passed else "fail",
        scene=scene,
        reason=None if passed else "visual-threshold-exceeded",
        version=version,
        comparisons=comparisons,
    )


def with_visual_gate(
    validation: dict[str, Any],
    visual_gate: dict[str, Any],
) -> dict[str, Any]:
    gates = [
        visual_gate if gate["id"] == "visual.render" else gate
        for gate in validation["gates"]
    ]
    return {**validation, "gates": gates}


def _detection_evidence(provider: Any) -> Any:
    if provider is None:
        return None
    try:
        return provider.detect()
    except Exception:
        return None


def _evidence_version(evidence: Any) -> str | None:
    if evidence is None:
        return None
    try:
        version = evidence.version
    except Exception:
        return None
    return version if type(version) is str else None


def _visual_gate(
    outcome: str,
    *,
    scene: NormalizedScene,
    reason: str | None,
    version: str | None,
    comparisons: list[dict[str, Any]] | None = None,
    reason_category: str | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "slides_compared": len(comparisons or []),
        "thresholds": visual_thresholds(),
        "comparisons": comparisons or [],
        "context": _scene_context(scene),
        "exemptions": [],
        "exemption_policy": "No automatic visual exemptions; context is explanatory only.",
    }
    if reason is not None:
        evidence["reason"] = reason
    if reason_category is not None:
        evidence["reason_category"] = reason_category
    warnings = [] if outcome == "pass" else [
        "Optional visual parity was not established."
    ]
    return gate_record(
        "visual.render",
        outcome,
        required=False,
        validator="libreoffice",
        version=version,
        evidence=evidence,
        warnings=warnings,
    )


def _scene_context(scene: NormalizedScene) -> dict[str, Any]:
    font = scene.diagnostics.get("font_evidence", {})
    rasterized = scene.diagnostics.get("fidelity", {}).get("rasterized", {})
    font_samples = font.get("samples", [])
    return {
        "font_substitutions": int(font.get("substitutions", 0)),
        "font_substitution_samples": [
            sample for sample in font_samples
            if sample.get("substitution") is not None
        ],
        "fallback_elements": int(rasterized.get("count", 0)),
        "fallback_area": float(rasterized.get("area", 0.0)),
        "fallback_samples": list(rasterized.get("samples", [])),
        "fallback_samples_truncated": int(rasterized.get("truncated", 0)),
    }
