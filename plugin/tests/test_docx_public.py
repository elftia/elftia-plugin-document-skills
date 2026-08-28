"""DOCX public-boundary tests split by operation family."""

from tests.support.docx_public import *  # noqa: F401,F403
from tests.support.docx_public import (
    _GIF,
    _PNG,
    _PNG_16,
    _public,
    _read_document,
    _report,
    _request,
    _table_values,
)


def test_docx_libreoffice_operations_have_a_private_worker_budget(
    project_root: Path,
    tmp_path: Path,
) -> None:
    convert_request = _request(
        tmp_path,
        "convert-budget.json",
        {"operation": "docx.convert.pdf"},
    )
    legacy_request = _request(
        tmp_path,
        "legacy-convert-budget.json",
        {"operation": "docx.convert.legacy"},
    )
    normal_request = _request(
        tmp_path,
        "read-budget.json",
        {"operation": "docx.read"},
    )
    render_request = _request(
        tmp_path,
        "render-budget.json",
        {"operation": "docx.render"},
    )
    supervisor = PublicCommandSupervisor(project_root, timeout_seconds=8.0)

    assert supervisor._command_limits(
        PublicCommand("run", ("run", "--request", str(convert_request))),
        tmp_path,
    ) == (90.0, 2_097_152)
    assert supervisor._command_limits(
        PublicCommand("run", ("run", "--request", str(legacy_request))),
        tmp_path,
    ) == (90.0, 2_097_152)
    assert supervisor._command_limits(
        PublicCommand("run", ("run", "--request", str(render_request))),
        tmp_path,
    ) == (90.0, 2_097_152)
    assert supervisor._command_limits(
        PublicCommand("run", ("run", "--request", str(normal_request))),
        tmp_path,
    ) == (8.0, 2_097_152)


def test_docx_dotnet_operations_have_a_private_worker_budget(
    project_root: Path,
    tmp_path: Path,
) -> None:
    supervisor = PublicCommandSupervisor(project_root, timeout_seconds=8.0)
    for operation in (
        "docx.comments.add",
        "docx.comments.read",
        "docx.comments.resolve",
        "docx.revisions.apply",
        "docx.revisions.read",
        "docx.validate.schema",
    ):
        request = _request(
            tmp_path,
            f"{operation}.json",
            {"operation": operation},
        )
        assert supervisor._command_limits(
            PublicCommand("run", ("run", "--request", str(request))),
            tmp_path,
        ) == (90.0, 2_097_152)
