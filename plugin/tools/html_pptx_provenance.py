"""Truthful provenance profiles for the HTML-to-editable-PPTX subsystem."""

from pathlib import Path

HTML_PPTX_REQUIREMENT = "Rasen html-to-editable-pptx"
CORE_PPTX_REQUIREMENT = "Rasen document-skills-core-pptx"
PPTX_TEMPLATE_B2_REQUIREMENT = "Rasen pptx-ecosystem-phase-bc-b2"
PPTX_TEMPLATE_B4_REQUIREMENT = "Rasen pptx-ecosystem-phase-bc-b4"
PPTX_SVG_B5_REQUIREMENT = "Rasen pptx-ecosystem-phase-bc-b5"
COMBINED_PPTX_REQUIREMENT = (
    "Rasen html-to-editable-pptx + document-skills-core-pptx"
)
COMBINED_PPTX_TEMPLATE_B2_REQUIREMENT = (
    COMBINED_PPTX_REQUIREMENT + " + pptx-ecosystem-phase-bc-b2"
)
SHARED_PROVENANCE_REQUIREMENT = (
    "Rasen html-to-editable-pptx + document-skills-core-pptx + "
    "document-skills-consumer-gates-and-truthful-contracts"
)
SHARED_PROVENANCE_TEMPLATE_B2_REQUIREMENT = (
    SHARED_PROVENANCE_REQUIREMENT + " + pptx-ecosystem-phase-bc-b2"
)
SHARED_PROVENANCE_TEMPLATE_B2_B4_REQUIREMENT = (
    SHARED_PROVENANCE_TEMPLATE_B2_REQUIREMENT + " + pptx-ecosystem-phase-bc-b4"
)
SHARED_PROVENANCE_TEMPLATE_B2_B4_B5_REQUIREMENT = (
    SHARED_PROVENANCE_TEMPLATE_B2_B4_REQUIREMENT
    + " + pptx-ecosystem-phase-bc-b5"
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
_PPTX_TEMPLATE_B2_MODULES = {
    "src/document_skills_core/cli.py",
    "src/document_skills_core/core/contracts/errors.py",
    "src/document_skills_core/formats/pptx/template_binding.py",
    "src/document_skills_core/formats/pptx/template_content_lint.py",
    "src/document_skills_core/formats/pptx/template_contracts.py",
    "src/document_skills_core/formats/pptx/template_descriptor.py",
    "src/document_skills_core/formats/pptx/template_inspect.py",
    "src/document_skills_core/formats/pptx/template_materialize.py",
    "src/document_skills_core/formats/pptx/template_purge.py",
    "src/document_skills_core/formats/pptx/template_service.py",
    "src/document_skills_core/formats/pptx/contracts.py",
    "src/document_skills_core/formats/pptx/package.py",
    "src/document_skills_core/formats/pptx/results.py",
    "src/document_skills_core/formats/pptx/service.py",
    "src/document_skills_core/formats/pptx/slide_graph.py",
    "src/document_skills_core/providers/defaults.py",
    "src/document_skills_core/public_cli/supervisor.py",
    "tests/fixtures/pptx/ecosystem_bc/generate.py",
    "tests/support/pptx_template_fixture.py",
    "tests/test_pptx_contracts.py",
    "tests/test_pptx_ecosystem_fixtures.py",
    "tests/test_pptx_public.py",
    "tests/test_pptx_template_b2.py",
    "tests/test_html_pptx_public.py",
    "tests/test_runtime.py",
    "tools/html_pptx_provenance.py",
    "tools/provenance_records.py",
    "tools/regenerate_provenance.py",
}
_PPTX_TEMPLATE_B2_TESTS = [
    "tests/test_pptx_template_b2.py",
    "tests/test_pptx_template_b2_hardening.py",
    "tests/test_pptx_ecosystem_fixtures.py",
    "tests/test_html_pptx_public.py",
    "tests/test_pptx_contracts.py",
    "tests/test_pptx_public.py",
    "tests/test_runtime.py",
    "tests/test_supply_chain.py",
]
_PPTX_TEMPLATE_B4_MODULES = {
    "src/document_skills_core/formats/pptx/results.py",
    "src/document_skills_core/formats/pptx/template_content_analysis.py",
    "src/document_skills_core/formats/pptx/template_content_fonts.py",
    "src/document_skills_core/formats/pptx/template_content_lint.py",
    "src/document_skills_core/formats/pptx/template_content_metrics.py",
    "src/document_skills_core/formats/pptx/template_inspect.py",
    "src/document_skills_core/formats/pptx/template_materialize.py",
    "src/document_skills_core/formats/pptx/template_service.py",
    "tests/fixtures/pptx/ecosystem_bc/generate.py",
    "tests/test_html_provenance.py",
    "tests/test_pptx_template_b4.py",
    "tests/test_pptx_template_b4_fonts.py",
    "tests/test_pptx_template_b4_hardening.py",
    "tools/html_pptx_provenance.py",
    "tools/regenerate_provenance.py",
}
_PPTX_TEMPLATE_B4_TESTS = [
    "tests/test_pptx_template_b4.py",
    "tests/test_pptx_template_b4_fonts.py",
    "tests/test_pptx_template_b4_hardening.py",
    "tests/test_pptx_ecosystem_fixtures.py",
    "tests/test_html_provenance.py",
    "tests/test_runtime.py",
    "tests/test_supply_chain.py",
]
_PPTX_SVG_B5_MODULES = {
    "src/document_skills_core/core/io/directory_promotion.py",
    "src/document_skills_core/core/io/parent_anchor.py",
    "src/document_skills_core/core/io/parent_anchor_windows.py",
    "src/document_skills_core/formats/pptx/contracts.py",
    "src/document_skills_core/formats/pptx/mapping.py",
    "src/document_skills_core/formats/pptx/presentation_contracts.py",
    "src/document_skills_core/formats/pptx/scene_custom_geometry.py",
    "src/document_skills_core/formats/pptx/scene_emitter.py",
    "src/document_skills_core/formats/pptx/scene_export.py",
    "src/document_skills_core/formats/pptx/scene_export_geometry.py",
    "src/document_skills_core/formats/pptx/scene_export_models.py",
    "src/document_skills_core/formats/pptx/scene_export_objects.py",
    "src/document_skills_core/formats/pptx/scene_export_svg.py",
    "src/document_skills_core/formats/pptx/scene_group_emitter.py",
    "src/document_skills_core/formats/pptx/scene_opc_validation.py",
    "src/document_skills_core/formats/pptx/service.py",
    "src/document_skills_core/formats/pptx/svg_assets.py",
    "src/document_skills_core/formats/pptx/svg_contracts.py",
    "src/document_skills_core/formats/pptx/svg_geometry.py",
    "src/document_skills_core/formats/pptx/svg_parser.py",
    "src/document_skills_core/formats/pptx/svg_profile.py",
    "src/document_skills_core/formats/pptx/svg_semantics.py",
    "src/document_skills_core/formats/pptx/svg_service.py",
    "src/document_skills_core/formats/pptx/svg_values.py",
    "src/document_skills_core/formats/pptx/validation.py",
    "src/document_skills_core/providers/defaults.py",
    "src/document_skills_core/public_cli/supervisor.py",
    "tests/fixtures/pptx/ecosystem_bc/generate.py",
    "tests/support/pptx_svg_consumer_evidence.py",
    "tests/support/pptx_svg_fixture.py",
    "tests/test_directory_promotion.py",
    "tests/test_html_provenance.py",
    "tests/test_pptx_contracts.py",
    "tests/test_pptx_public.py",
    "tests/test_pptx_scene_export.py",
    "tests/test_pptx_svg_contracts.py",
    "tests/test_pptx_svg_fixtures.py",
    "tests/test_pptx_svg_public.py",
    "tests/test_pptx_svg_scene.py",
    "tests/test_pptx_svg_service.py",
    "tests/test_strategy2.py",
    "tests/test_strategy3.py",
    "tools/html_pptx_provenance.py",
    "tools/provenance_records.py",
    "tools/regenerate_provenance.py",
}
_PPTX_SVG_B5_TESTS = [
    "tests/test_directory_promotion.py",
    "tests/test_pptx_scene_export.py",
    "tests/test_pptx_svg_contracts.py",
    "tests/test_pptx_svg_fixtures.py",
    "tests/test_pptx_svg_public.py",
    "tests/test_pptx_svg_scene.py",
    "tests/test_pptx_svg_service.py",
    "tests/test_pptx_contracts.py",
    "tests/test_pptx_public.py",
    "tests/test_pptx_ecosystem_fixtures.py",
    "tests/test_html_provenance.py",
    "tests/test_runtime.py",
    "tests/test_strategy2.py",
    "tests/test_strategy3.py",
    "tests/test_supply_chain.py",
]


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
    template_profile = template_b2_module_profile(path)
    template_b4_profile = template_b4_module_profile(path)
    svg_b5_profile = svg_b5_module_profile(path)
    if all(
        profile is None
        for profile in (
            html_profile,
            core_profile,
            template_profile,
            template_b4_profile,
            svg_b5_profile,
        )
    ):
        return None
    profiles = [
        profile
        for profile in (
            html_profile,
            core_profile,
            template_profile,
            template_b4_profile,
            svg_b5_profile,
        )
        if profile
    ]
    modifications = " ".join(profile[0] for profile in profiles)
    tests = list(dict.fromkeys(test for profile in profiles for test in profile[1]))
    requirements = [
        requirement
        for profile, requirement in (
            (html_profile, HTML_PPTX_REQUIREMENT),
            (core_profile, CORE_PPTX_REQUIREMENT),
            (template_profile, PPTX_TEMPLATE_B2_REQUIREMENT),
            (template_b4_profile, PPTX_TEMPLATE_B4_REQUIREMENT),
            (svg_b5_profile, PPTX_SVG_B5_REQUIREMENT),
        )
        if profile is not None
    ]
    if path == "tools/regenerate_provenance.py":
        requirements = [
            SHARED_PROVENANCE_REQUIREMENT,
            *(
                [PPTX_TEMPLATE_B2_REQUIREMENT]
                if template_profile is not None
                else []
            ),
            *(
                [PPTX_TEMPLATE_B4_REQUIREMENT]
                if template_b4_profile is not None
                else []
            ),
            *(
                [PPTX_SVG_B5_REQUIREMENT]
                if svg_b5_profile is not None
                else []
            ),
        ]
    requirement = "Rasen " + " + ".join(
        dict.fromkeys(item.removeprefix("Rasen ") for item in requirements)
    )
    return modifications, tests, requirement


def template_b2_module_profile(path: str) -> tuple[str, list[str]] | None:
    if (
        path in _PPTX_TEMPLATE_B2_MODULES
        or path == "src/document_skills_core/formats/pptx/contact_sheet.py"
        or path.startswith("tests/test_pptx_template_b2")
    ):
        return (
            "Descriptor-bound structural and semantic template inspection, optional "
            "contact-sheet evidence, stable-slot materialization, content lint, and "
            "physical purge with truthful public and supply-chain evidence.",
            _PPTX_TEMPLATE_B2_TESTS,
        )
    return None


def template_b4_module_profile(path: str) -> tuple[str, list[str]] | None:
    if path in _PPTX_TEMPLATE_B4_MODULES:
        return (
            "Bounded CJK capacity, placeholder, ellipsis, speaker-note leak, and "
            "type-scale content lint shared by inert template inspection and "
            "fail-closed template materialization.",
            _PPTX_TEMPLATE_B4_TESTS,
        )
    return None


def svg_b5_module_profile(path: str) -> tuple[str, list[str]] | None:
    if path in _PPTX_SVG_B5_MODULES:
        return (
            "Bounded constrained-SVG parsing and native DrawingML compilation, "
            "A-Contract scene export and round trip, directory no-replace atomic "
            "promotion, and real PowerPoint consumer evidence.",
            _PPTX_SVG_B5_TESTS,
        )
    return None


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


def template_b2_data_profile(path: str) -> tuple[str, list[str]] | None:
    if (
        path.startswith("tests/fixtures/pptx/ecosystem_bc/")
        or path in {
            "provenance/runtime-source-allowlist.json",
            "skills/document-pptx/SKILL.md",
            "skills/document-pptx/references/template-inspect-and-fill.md",
            "tests/fixtures/manifest.json",
        }
    ):
        return (
            "Elftia-authored semantic-template guidance, deterministic fixtures, "
            "hash-bound metadata, and exact runtime-source policy for PPTX B2.",
            _PPTX_TEMPLATE_B2_TESTS,
        )
    return None


def template_b4_data_profile(path: str) -> tuple[str, list[str]] | None:
    if path in {
        "provenance/runtime-source-allowlist.json",
        "skills/document-pptx/SKILL.md",
        "skills/document-pptx/references/template-inspect-and-fill.md",
        "tests/fixtures/manifest.json",
        "tests/fixtures/pptx/ecosystem_bc/README.md",
        "tests/fixtures/pptx/ecosystem_bc/templates/cjk-capacity.pptx",
        "tests/fixtures/pptx/ecosystem_bc/templates/cjk-capacity.pptx.manifest.json",
    }:
        return (
            "B4 template-content guidance, deterministic CJK fixture bytes, "
            "hash-bound metadata, and exact runtime-source policy.",
            _PPTX_TEMPLATE_B4_TESTS,
        )
    return None


def svg_b5_data_profile(path: str) -> tuple[str, list[str]] | None:
    if (
        path.startswith("tests/fixtures/pptx/ecosystem_bc/svg/")
        or path.startswith("tests/fixtures/pptx/ecosystem_bc/expected/scene/")
        or path.startswith("tests/fixtures/pptx/ecosystem_bc/expected/visual/")
        or path
        in {
            "provenance/runtime-source-allowlist.json",
            "skills/document-pptx/SKILL.md",
            "skills/document-pptx/references/svg-and-scene.md",
            "tests/fixtures/manifest.json",
            "tests/fixtures/pptx/ecosystem_bc/README.md",
        }
    ):
        return (
            "B5 constrained-SVG and scene guidance, deterministic fixtures, "
            "hash-bound semantic and real-consumer evidence, and exact "
            "runtime-source policy.",
            _PPTX_SVG_B5_TESTS,
        )
    return None
