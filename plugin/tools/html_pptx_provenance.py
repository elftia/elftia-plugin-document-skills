"""Truthful provenance profiles for the HTML-to-editable-PPTX subsystem."""

from pathlib import Path

HTML_PPTX_REQUIREMENT = "Rasen html-to-editable-pptx"
SHARED_PROVENANCE_REQUIREMENT = (
    "Rasen html-to-editable-pptx + "
    "document-skills-consumer-gates-and-truthful-contracts"
)
_SHARED_MODULES = {
    "src/document_skills_core/core/capabilities/catalog.py",
    "src/document_skills_core/core/capabilities/registry.py",
    "src/document_skills_core/core/contracts/models.py",
    "src/document_skills_core/formats/pptx/contracts.py",
    "src/document_skills_core/formats/pptx/service.py",
    "src/document_skills_core/formats/pptx/validation.py",
    "src/document_skills_core/providers/defaults.py",
    "src/document_skills_core/public_cli/supervisor.py",
    "tests/test_pptx_contracts.py",
    "tests/test_runtime.py",
    "tests/test_supply_chain.py",
    "tools/html_pptx_provenance.py",
    "tools/provenance_records.py",
    "tools/regenerate_provenance.py",
    "tools/supply_chain.py",
}


def html_pptx_module_profile(path: str) -> tuple[str, list[str]] | None:
    capture_tests = [
        "tests/node/html_asset_server.test.mjs",
        "tests/node/html_browser_policy.test.mjs",
        "tests/node/html_scene_capture.test.mjs",
        "tests/test_html_browser_provider.py",
        "tests/test_html_capture.py",
    ]
    emitter_tests = [
        "tests/test_html_scene.py",
        "tests/test_html_scene_emitter.py",
        "tests/test_html_scene_opc_safety.py",
        "tests/test_html_visual_validation.py",
    ]
    if path.startswith("runtime/node/html_") or path.startswith(
        "src/document_skills_core/providers/html_browser/"
    ):
        return (
            "Contained system-browser detection, local-asset serving, DOM capture, and private scene transport for editable HTML-to-PPTX conversion.",
            capture_tests,
        )
    if path.startswith("src/document_skills_core/formats/pptx/") and Path(path).name in {
        "html_capture.py", "html_contracts.py", "png_compare.py", "scene.py",
        "scene_emitter.py", "scene_normalizer.py", "scene_opc_validation.py",
        "visual_validation.py",
    }:
        return (
            "Bounded HTML request/capture contracts, scene normalization, editable OOXML emission, and semantic/visual validation.",
            emitter_tests,
        )
    if path == "tests/fixtures/recipes/html_pptx_fixtures.py":
        return (
            "Deterministic repository-authored HTML, image, scene, and editable-PPTX fixture recipe.",
            ["tests/test_html_pptx_fixtures.py", "tests/test_html_scene_emitter.py"],
        )
    if path.startswith(("tests/node/html_", "tests/test_html_")):
        return (
            "Regression and adversarial coverage for the bounded HTML-to-editable-PPTX capability.",
            [path],
        )
    if path == "tools/regenerate_provenance.py":
        return (
            "Shared exact provenance generation for HTML-to-editable-PPTX and independent consumer-gate Strategy-4 release evidence.",
            [
                "tests/test_html_provenance.py",
                "tests/test_html_pptx_public.py",
                "tests/test_strategy3.py",
                "tests/test_supply_chain.py",
            ],
        )
    if path in _SHARED_MODULES:
        return (
            "Additive public operation, provider dispatch, managed runtime, supply-chain, and exact provenance support for HTML-to-editable-PPTX.",
            [
                "tests/test_pptx_contracts.py",
                "tests/test_html_pptx_public.py",
                "tests/test_runtime.py",
                "tests/test_supply_chain.py",
            ],
        )
    return None


def html_pptx_data_profile(path: str) -> tuple[str, list[str]] | None:
    if path.startswith("tests/fixtures/html-") or path.startswith("tests/fixtures/asset-"):
        return (
            "Deterministic repository-authored HTML-to-PPTX fixture bytes generated and hash-bound by the checked-in recipe.",
            ["tests/test_html_pptx_fixtures.py", "tests/test_supply_chain.py"],
        )
    if path in {
        "package.json", "package-lock.json", "THIRD_PARTY_NOTICES.md", "sbom.cdx.json",
        "provenance/dependency-allowlist.json", "provenance/dependency-licenses.json",
        "provenance/reviews/playwright-core-1.62.1-adoption.md",
    }:
        return (
            "Exact playwright-core dependency lock, adoption, license, notice, and SBOM evidence for contained browser capture.",
            ["tests/test_runtime.py", "tests/test_supply_chain.py"],
        )
    if path.startswith("skills/document-pptx/") or path == "README.md":
        return (
            "Capability-probed consumer guidance for bounded HTML-to-editable-PPTX conversion and truthful fidelity diagnostics.",
            ["tests/test_html_pptx_public.py", "tests/test_supply_chain.py"],
        )
    return None
