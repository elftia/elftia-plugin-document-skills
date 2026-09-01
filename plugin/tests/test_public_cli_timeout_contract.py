"""Contract coverage for real public CLI subprocess wall-clock budgets."""

from __future__ import annotations

import ast
from pathlib import Path

from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS

_PRODUCT_MAX_PUBLIC_AGGREGATE_TIMEOUT_SECONDS = 270
_EXPECTED_PUBLIC_CLI_CALLERS = {
    "fixtures/recipes/docx_fixtures.py",
    "support/docx_public.py",
    "test_docx_accessibility_public.py",
    "test_docx_complex_public.py",
    "test_docx_docm_public.py",
    "test_docx_dotnet_real.py",
    "test_docx_legacy_public.py",
    "test_docx_merge_comments_public.py",
    "test_docx_merge_content_controls_public.py",
    "test_docx_merge_fields_public.py",
    "test_docx_merge_notes_public.py",
    "test_docx_merge_public.py",
    "test_docx_merge_revisions_inline_public.py",
    "test_html_pptx_public.py",
    "test_pdf_annotation_safety.py",
    "test_pdf_form_appearance_binding.py",
    "test_pdf_form_flatten.py",
    "test_pdf_form_reconciliation.py",
    "test_pdf_image_decode.py",
    "test_pdf_image_extraction_limits.py",
    "test_pdf_inline_images.py",
    "test_pdf_jpeg_creation.py",
    "test_pdf_merge_split_catalog.py",
    "test_pdf_nested_images.py",
    "test_pdf_page_tree_catalog_preservation.py",
    "test_pdf_public.py",
    "test_pdf_review_edit_regressions.py",
    "test_pdf_review_rewrite_regressions.py",
    "test_pdf_rewrite_font_encoding.py",
    "test_pdf_table_lattice.py",
    "test_pdf_unicode.py",
    "test_pdf_watermark_fonts.py",
    "test_pptx_equation_public.py",
    "test_pptx_macro.py",
    "test_pptx_public.py",
    "test_pptx_scene_export_chart_strict.py",
    "test_pptx_scene_export_depth.py",
    "test_pptx_svg_public.py",
    "test_pptx_template_b2.py",
    "test_pptx_template_b2_hardening.py",
    "test_pptx_template_b4.py",
    "test_pptx_template_sanitize.py",
    "test_runtime_without_consumer_dev.py",
    "test_strategy2.py",
    "test_truthful_results.py",
    "test_xlsx_core_only.py",
    "test_xlsx_pivot_public.py",
    "test_xlsx_public.py",
}
_AFFECTED_PUBLIC_CLI_CALLERS = _EXPECTED_PUBLIC_CLI_CALLERS - {
    "test_docx_dotnet_real.py",
    "test_html_pptx_public.py",
    "test_pdf_public.py",
    "test_pptx_public.py",
    "test_strategy2.py",
    "test_xlsx_pivot_public.py",
    "test_xlsx_public.py",
}

_REAL_PROVIDER_TESTS = {
    "test_consumer_validation.py": {
        "test_installed_office_real_safe_open_is_mandatory",
        "test_real_consumer_timeout_kills_descendant_and_preserves_file",
    },
    "test_docx_comparison_public.py": {
        "test_public_reference_visual_compare_uses_explicit_fixed_page_pairing",
    },
    "test_docx_legacy_public.py": {
        "test_public_legacy_doc_conversion_is_explicit_and_provider_gated",
    },
    "test_docx_render_compare_public.py": {
        "test_public_create_output_converts_through_real_libreoffice",
        "test_public_render_output_through_real_libreoffice",
        "test_public_render_returns_bounded_png_and_layout_evidence",
        "test_public_layout_repair_runs_bounded_improvement_loop",
    },
    "test_docx_template_pack_remediation.py": {
        "test_academic_pack_emits_strict_geometry_typography_layout_and_fields",
    },
    "test_html_browser_provider.py": {
        "test_real_detector_is_truthful_and_bounded",
    },
    "test_html_capture.py": {
        "test_real_capture_uses_fixed_canvas_transform_pseudo_and_browser_paint_evidence",
        "test_real_capture_binds_transparent_wrappers_and_positioned_pseudo_geometry",
        "test_real_capture_classifies_css_layout_text_flow_media_and_svg",
        "test_real_capture_reports_each_forbidden_resource_reason",
        "test_real_capture_counts_resource_occurrences_beyond_sample_limit",
    },
    "test_html_pptx_fixtures.py": {
        "test_real_browser_classifies_repository_fallback_fixture",
        "test_real_browser_keeps_uniform_styled_image_native",
        "test_real_browser_keeps_adversarial_fixture_static_and_blocks_resources",
    },
    "test_html_pptx_public.py": {
        "test_public_html_conversion_creates_native_editable_shapes",
        "test_public_fixture_reopens_with_editable_counts_and_repeats_exact_hash",
        "test_public_nested_wrappers_shape_fallback_and_pseudo_layers_are_truthful",
    },
    "test_libreoffice_provider.py": {
        "test_real_libreoffice_recalculation_mechanism_updates_stale_xlsx_cache",
        "test_real_libreoffice_xlsx_render_provider_operation_reopens_pdf",
        "test_real_libreoffice_legacy_xls_conversion_mechanism",
    },
    "test_pdf_provider_profiles.py": {
        "test_core_only_profile_runs_real_public_smokes",
        "test_full_profile_runs_available_pypdf_smokes_before_reporting_unavailable",
    },
    "test_pptx_equation_libreoffice.py": {
        "test_real_libreoffice_observes_equation_deck_without_editability_claim",
    },
    "test_pptx_equation_powerpoint.py": {
        "test_powerpoint_recognizes_every_generated_equation_as_editable_math_zone",
    },
    "test_private_workspace_identity.py": {
        "test_timed_out_worker_removes_only_its_owned_operation_root",
    },
}
_REAL_PROVIDER_MODULES = {
    "test_docx_dotnet_real.py",
    "test_dotnet_xlsx_schema_real.py",
    "test_pdf_form_flatten.py",
}


def _is_real_public_entrypoint(command: ast.AST) -> bool:
    strings = {
        node.value
        for node in ast.walk(command)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    return any("run.py" in value for value in strings) and any(
        "skill" in value for value in strings
    )


def _timeout_nodes() -> dict[str, ast.AST]:
    tests_root = Path(__file__).resolve().parent
    found: dict[str, ast.AST] = {}
    for path in sorted(tests_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if ast.unparse(node.func) != "subprocess.run":
                continue
            if not _is_real_public_entrypoint(node.args[0]):
                continue
            relative = path.relative_to(tests_root).as_posix()
            assert relative not in found, f"multiple public CLI callers in {relative}"
            timeout = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "timeout"),
                None,
            )
            assert timeout is not None, f"missing public CLI timeout in {relative}"
            found[relative] = timeout
    return found


def _resolved_timeout(timeout: ast.AST) -> float:
    if isinstance(timeout, ast.Name):
        assert timeout.id == "PUBLIC_CLI_TEST_TIMEOUT_SECONDS"
        return float(PUBLIC_CLI_TEST_TIMEOUT_SECONDS)
    assert isinstance(timeout, ast.Constant)
    assert isinstance(timeout.value, (int, float))
    return float(timeout.value)


def _is_slow_marker(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "slow"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
    )


def _slow_decorated(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_is_slow_marker(decorator) for decorator in function.decorator_list)


def _module_marked_slow(module: ast.Module) -> bool:
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in node.targets
        ):
            continue
        value = node.value
        marks = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
        if any(_is_slow_marker(mark) for mark in marks):
            return True
    return False


def test_real_public_cli_harness_timeouts_cover_product_aggregate() -> None:
    assert PUBLIC_CLI_TEST_TIMEOUT_SECONDS == 270 + 30 == 300
    assert (
        PUBLIC_CLI_TEST_TIMEOUT_SECONDS
        >= _PRODUCT_MAX_PUBLIC_AGGREGATE_TIMEOUT_SECONDS
    )

    timeouts = _timeout_nodes()
    assert set(timeouts) == _EXPECTED_PUBLIC_CLI_CALLERS
    for path, timeout in timeouts.items():
        assert (
            _resolved_timeout(timeout)
            >= _PRODUCT_MAX_PUBLIC_AGGREGATE_TIMEOUT_SECONDS
        ), path
        if path in _AFFECTED_PUBLIC_CLI_CALLERS:
            assert isinstance(timeout, ast.Name)
            assert timeout.id == "PUBLIC_CLI_TEST_TIMEOUT_SECONDS"

    equation_timeout = timeouts["test_pptx_equation_public.py"]
    assert isinstance(equation_timeout, ast.Name)
    assert _resolved_timeout(equation_timeout) == 300


def test_real_provider_tests_are_explicitly_marked_slow() -> None:
    tests_root = Path(__file__).resolve().parent
    for filename, expected_names in _REAL_PROVIDER_TESTS.items():
        source = (tests_root / filename).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=filename)
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert set(expected_names) <= set(functions), filename
        for name in expected_names:
            assert _slow_decorated(functions[name]), f"{filename}:{name}"
    for filename in sorted(_REAL_PROVIDER_MODULES):
        source = (tests_root / filename).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=filename)
        assert _module_marked_slow(tree), filename
