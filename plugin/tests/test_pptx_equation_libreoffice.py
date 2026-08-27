"""Real isolated LibreOffice render observation for B6 editable equations."""

from pathlib import Path

import pytest

from document_skills_core.formats.pdf.validation import reopen_pdf
from document_skills_core.formats.pptx.create import create_pptx
from document_skills_core.formats.pptx.read import read_pptx
from document_skills_core.providers.libreoffice import build_libreoffice_provider
from tests.test_pptx_equation import _supported_deck


def test_real_libreoffice_observes_equation_deck_without_editability_claim(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "libreoffice-equations.pptx"
    output = tmp_path / "libreoffice-equations.pdf"
    create_pptx(source, _supported_deck())
    _definition, provider = build_libreoffice_provider(project_root)
    evidence = provider.detect()
    if not evidence.available:
        pytest.skip(evidence.reason or "LibreOffice is unavailable")

    result = provider.execute(
        "pptx.convert.pdf",
        {
            "schema_version": "1.0",
            "operation": "pptx.convert.pdf",
            "input": str(source),
            "output": str(output),
            "arguments": {},
            "options": {"fidelity": "enhanced"},
        },
    )

    assert result["status"] in {"failed", "success"}
    if result["status"] == "success":
        assert reopen_pdf(output)["pages"] == 1
    else:
        assert not output.exists()
        assert result["errors"]
    projected, warnings = read_pptx(source, {})
    equations = [
        shape["equation"]
        for shape in projected["slides"][0]["shapes"]
        if shape["type"] == "equation"
    ]
    assert warnings == []
    assert len(equations) == 6
    assert all(
        equation["consumer_compatibility"]["libreoffice"] == {"status": "not_run"}
        for equation in equations
    )
