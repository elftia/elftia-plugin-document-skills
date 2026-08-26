"""Truthful provenance profiles for the HTML-to-editable-PPTX subsystem."""

from pathlib import Path

HTML_PPTX_REQUIREMENT = "Rasen html-to-editable-pptx"
CORE_PPTX_REQUIREMENT = "Rasen document-skills-core-pptx"
COMBINED_PPTX_REQUIREMENT = (
    "Rasen html-to-editable-pptx + document-skills-core-pptx"
)
SHARED_PROVENANCE_REQUIREMENT = (
    "Rasen html-to-editable-pptx + document-skills-core-pptx + "
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


def core_pptx_module_profile(path: str) -> tuple[str, list[str]] | None:
    core_tests = [
        "tests/test_pptx_design.py",
        "tests/test_pptx_operations.py",
        "tests/test_pptx_schema_validation.py",
        "tests/test_pptx_public.py",
    ]
    if path == "src/document_skills_core/formats/pptx/create.py":
        return (
            "Schema-ordered native PresentationML creation, including valid body "
            "shape properties and presentation-namespace graphic-frame transforms.",
            core_tests,
        )
    if path == "src/document_skills_core/formats/pptx/scaffold.py":
        return (
            "Office-valid shared PresentationML theme scaffolding with required "
            "gradient stops for typed and scene-emitted PPTX output.",
            core_tests,
        )
    if path == "src/document_skills_core/public_cli/supervisor.py":
        return (
            "Operation-scoped public worker budgets for Core PPTX create, "
            "create-from-markdown, and edit without relaxing unrelated commands.",
            ["tests/test_html_pptx_public.py", "tests/test_pptx_public.py"],
        )
    if path in {
        "tests/test_pptx_design.py",
        "tests/test_pptx_operations.py",
    }:
        return (
            "Direct Core PPTX regression coverage for schema-valid native "
            "PresentationML creation.",
            [path],
        )
    if path == "tests/test_html_pptx_public.py":
        return (
            "Direct public-supervisor regression coverage for operation-scoped "
            "Core PPTX mutation budgets alongside HTML provider budgets.",
            [path],
        )
    if path in {
        "tests/test_html_provenance.py",
        "tools/html_pptx_provenance.py",
        "tools/regenerate_provenance.py",
    }:
        return (
            "Exact Core PPTX/OpenXML provenance classification and regression "
            "evidence combined with shared HTML-to-PPTX release records.",
            [
                "tests/test_html_provenance.py",
                "tests/test_strategy3.py",
                "tests/test_supply_chain.py",
            ],
        )
    return None


def pptx_module_profile(path: str) -> tuple[str, list[str], str] | None:
    html_profile = html_pptx_module_profile(path)
    core_profile = core_pptx_module_profile(path)
    if html_profile is None and core_profile is None:
        return None
    profiles = [profile for profile in (html_profile, core_profile) if profile]
    modifications = " ".join(profile[0] for profile in profiles)
    tests = list(dict.fromkeys(test for profile in profiles for test in profile[1]))
    requirement = (
        COMBINED_PPTX_REQUIREMENT
        if len(profiles) == 2
        else HTML_PPTX_REQUIREMENT
        if html_profile
        else CORE_PPTX_REQUIREMENT
    )
    if path == "tools/regenerate_provenance.py":
        requirement = SHARED_PROVENANCE_REQUIREMENT
    return modifications, tests, requirement


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
    if path == "src/document_skills_core/formats/pptx/scaffold.py":
        return (
            "Shared Office-valid PresentationML scaffold vocabulary (theme, slide "
            "master, slide layout, root relationships, document properties) common "
            "to typed pptx.create and HTML scene emission.",
            [
                "tests/test_html_scene_opc_safety.py",
                "tests/test_pptx_operations.py",
            ],
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
