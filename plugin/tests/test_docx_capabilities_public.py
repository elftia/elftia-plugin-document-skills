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

def test_public_capabilities_are_callable_not_detection_inferred(
    project_root: Path,
) -> None:
    report = _public(project_root, "capabilities", "--json")
    operations = {item["operation"]: item for item in report["operations"]}
    assert set(operations) == {
        "docx.create",
        "docx.comments.add",
        "docx.comments.read",
        "docx.comments.resolve",
        "docx.compare.semantic",
        "docx.compare.visual",
        "docx.convert.legacy",
        "docx.convert.pdf",
        "docx.edit",
        "docx.edit.replace-text",
        "docx.inspect.accessibility",
        "docx.inspect.structure",
        "docx.layout.repair",
        "docx.merge",
        "docx.read",
        "docx.render",
        "docx.revisions.apply",
        "docx.revisions.read",
        "docx.template.apply",
        "docx.validate.schema",
    }
    assert operations["docx.template.apply"]["providers"] == ["core-node"]
    for operation in (
        "docx.create",
        "docx.compare.semantic",
        "docx.edit",
        "docx.edit.replace-text",
        "docx.inspect.accessibility",
        "docx.inspect.structure",
        "docx.merge",
        "docx.read",
        "docx.template.apply",
    ):
        assert operations[operation]["available"] is True
    dotnet_available = next(
        provider["available"]
        for provider in report["providers"]
        if provider["id"] == "dotnet-openxml"
    )
    for operation in (
        "docx.comments.add",
        "docx.comments.read",
        "docx.comments.resolve",
        "docx.revisions.apply",
        "docx.revisions.read",
        "docx.validate.schema",
    ):
        assert operations[operation]["available"] is dotnet_available
        assert operations[operation]["providers"] == (
            ["dotnet-openxml"] if dotnet_available else []
        )
    assert report["validation"]["schema"] == (
        "available" if dotnet_available else "unavailable"
    )
    libreoffice_available = next(
        provider["available"]
        for provider in report["providers"]
        if provider["id"] == "libreoffice"
    )
    for operation in (
        "docx.compare.visual",
        "docx.convert.legacy",
        "docx.convert.pdf",
        "docx.layout.repair",
        "docx.render",
    ):
        assert operations[operation]["available"] is libreoffice_available
        assert operations[operation]["providers"] == (
            ["libreoffice"] if libreoffice_available else []
        )
    assert report["validation"]["visual"] == "unavailable"
    skill_text = (project_root / "skills/document-docx/SKILL.md").read_text(
        encoding="utf-8"
    )
    for operation in operations:
        assert f"`{operation}`" in skill_text
