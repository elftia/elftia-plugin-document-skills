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
