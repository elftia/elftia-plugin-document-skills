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

def test_public_create_emits_a_complete_table_grid(public_created: Path) -> None:
    with zipfile.ZipFile(public_created) as archive:
        document = fromstring(archive.read("word/document.xml"))

    table = document.find(f".//{qn('w', 'tbl')}")
    assert table is not None
    grid = table.find(qn("w", "tblGrid"))
    assert grid is not None
    first_row = table.find(qn("w", "tr"))
    assert first_row is not None
    assert len(grid.findall(qn("w", "gridCol"))) == len(
        first_row.findall(qn("w", "tc"))
    )


def test_public_convert_pdf_validates_and_promotes_provider_output(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-rich.docx"
    source_sha256 = sha256_file(source)
    output = tmp_path / "converted.pdf"
    provider_pdf = tmp_path / "provider.pdf"
    create_pdf(
        provider_pdf,
        {
            "metadata": {"title": "Converted", "author": "", "subject": ""},
            "page_size": "Letter",
            "pages": [{"blocks": []}],
        },
    )

    class ControlledLibreOffice:
        def convert_pdf(self, input_path: Path, max_output_bytes: int) -> bytes:
            assert input_path == source
            assert max_output_bytes == 8 * 1024 * 1024
            return provider_pdf.read_bytes()

    service = DocxService(project_root, libreoffice=ControlledLibreOffice())
    registry = ProviderCatalog()
    registry.register_provider(
        Provider(
            id=ProviderId.LIBREOFFICE,
            version="26.2.5.2",
            detect=lambda: DetectionEvidence(True, version="26.2.5.2"),
            execute=service.execute,
            capabilities=[Capability("docx.convert.pdf", "enhanced")],
        )
    )
    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        lambda _project_root: registry,
    )
    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.convert.pdf",
            "input": str(source),
            "output": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {"max_output_bytes": 8 * 1024 * 1024},
        },
        project_root,
        SchemaCatalog(project_root),
    )

    assert result["status"] == "success"
    assert result["provider_chain"] == ["libreoffice"]
    assert result["achieved_fidelity"] == "enhanced"
    assert result["diagnostics"]["operation_result"]["conversion"] == {
        "format": "pdf",
        "output_bytes": output.stat().st_size,
        "pages": 1,
        "visual_comparison": "unavailable",
    }
    assert output.read_bytes().startswith(b"%PDF-")
    assert sha256_file(source) == source_sha256


def test_public_convert_pdf_preserves_destination_on_invalid_provider_output(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-rich.docx"
    source_sha256 = sha256_file(source)
    output = tmp_path / "existing.pdf"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)

    class InvalidLibreOffice:
        def convert_pdf(self, input_path: Path, max_output_bytes: int) -> bytes:
            return b"not a PDF"

    service = DocxService(project_root, libreoffice=InvalidLibreOffice())
    registry = ProviderCatalog()
    registry.register_provider(
        Provider(
            id=ProviderId.LIBREOFFICE,
            version="controlled",
            detect=lambda: DetectionEvidence(True, version="controlled"),
            execute=service.execute,
            capabilities=[Capability("docx.convert.pdf", "enhanced")],
        )
    )
    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        lambda _project_root: registry,
    )
    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.convert.pdf",
            "input": str(source),
            "output": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {},
        },
        project_root,
        SchemaCatalog(project_root),
    )

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert output.read_bytes() == original_destination
    assert sha256_file(source) == source_sha256


def test_public_render_generates_bounded_pdf_page_evidence(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-rich.docx"
    source_sha256 = sha256_file(source)
    output = tmp_path / "rendered.pdf"
    provider_pdf = tmp_path / "provider-render.pdf"
    create_pdf(
        provider_pdf,
        {
            "metadata": {"title": "Rendered", "author": "", "subject": ""},
            "page_size": "Letter",
            "pages": [{"blocks": []}, {"blocks": []}, {"blocks": []}],
        },
    )

    class ControlledLibreOffice:
        def convert_pdf(self, input_path: Path, max_output_bytes: int) -> bytes:
            assert input_path == source
            return provider_pdf.read_bytes()

    service = DocxService(project_root, libreoffice=ControlledLibreOffice())
    registry = ProviderCatalog()
    registry.register_provider(
        Provider(
            id=ProviderId.LIBREOFFICE,
            version="controlled",
            detect=lambda: DetectionEvidence(True, version="controlled"),
            execute=service.execute,
            capabilities=[Capability("docx.render", "enhanced")],
        )
    )
    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        lambda _project_root: registry,
    )
    result = execute_request(
        {
            "schema_version": "1.0",
            "operation": "docx.render",
            "input": str(source),
            "output": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "format": "pdf",
                "page_range": {"start": 2, "end": 3},
                "dpi": None,
                "max_pages": 2,
                "max_total_bytes": 8 * 1024 * 1024,
            },
        },
        project_root,
        SchemaCatalog(project_root),
    )

    assert result["status"] == "success", result
    assert result["provider_chain"] == ["libreoffice"]
    render = result["diagnostics"]["operation_result"]["render"]
    assert render == {
        "format": "pdf",
        "page_range": {"start": 2, "end": 3},
        "dpi": None,
        "conversion_succeeded": True,
        "pages_generated": True,
        "page_count": 2,
        "total_bytes": output.stat().st_size,
        "visual_comparison": "unavailable",
    }
    gates = {gate["id"]: gate for gate in result["validation"]["gates"]}
    assert gates["operation.docx-render-pages"]["outcome"] == "pass"
    assert gates["visual.render"]["outcome"] == "unavailable"
    assert sha256_file(source) == source_sha256


def test_public_typed_edit_applies_body_formatting_transaction(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    output = tmp_path / "public-edited.docx"
    first = {
        "story": "body",
        "paragraph_index": 0,
        "expected_text": "Public DOCX",
    }
    second = {
        "story": "body",
        "paragraph_index": 1,
        "expected_text": "Hello {name}",
    }
    request = _request(
        tmp_path,
        "typed-edit.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"type": "paragraph_delete", "target": first},
                    {
                        "type": "paragraph_insert",
                        "target": second,
                        "position": "after",
                        "text": "Reviewed total",
                        "style": "Normal",
                    },
                    {
                        "type": "paragraph_style",
                        "target": second,
                        "style": "Heading2",
                    },
                    {
                        "type": "run_style",
                        "target": second,
                        "match": {
                            "text": "Hello {name}",
                            "expected_matches": 1,
                        },
                        "style": {
                            "font_family": "Aptos",
                            "font_size_pt": 12.5,
                            "bold": True,
                            "italic": False,
                            "underline": True,
                            "color": "1A2B3C",
                            "highlight": "yellow",
                        },
                    },
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    assert result["provider_chain"] == ["core-python"]
    assert result["diagnostics"]["operation_result"]["edit"] == {
        "applied": 4,
        "primitive_counts": {
            "paragraph_delete": 1,
            "paragraph_insert": 1,
            "paragraph_style": 1,
            "run_style": 1,
        },
        "selector_policy": "immutable-input-body-paragraph",
    }
    with zipfile.ZipFile(output) as archive:
        document = fromstring(archive.read("word/document.xml"))
    body = document.find(qn("w", "body"))
    assert body is not None
    paragraphs = [child for child in body if child.tag == qn("w", "p")]
    assert ["".join(node.itertext()) for node in paragraphs[:2]] == [
        "Hello {name}",
        "Reviewed total",
    ]
    style = paragraphs[0].find(f"./{qn('w', 'pPr')}/{qn('w', 'pStyle')}")
    assert style is not None and style.attrib[qn("w", "val")] == "Heading2"
    properties = paragraphs[0].find(f"./{qn('w', 'r')}/{qn('w', 'rPr')}")
    assert properties is not None
    fonts = properties.find(qn("w", "rFonts"))
    assert fonts is not None and fonts.attrib[qn("w", "ascii")] == "Aptos"
    assert properties.find(qn("w", "b")) is not None
    italic = properties.find(qn("w", "i"))
    assert italic is not None and italic.attrib[qn("w", "val")] == "0"
    underline = properties.find(qn("w", "u"))
    assert underline is not None and underline.attrib[qn("w", "val")] == "single"
    color = properties.find(qn("w", "color"))
    assert color is not None and color.attrib[qn("w", "val")] == "1A2B3C"
    highlight = properties.find(qn("w", "highlight"))
    assert highlight is not None and highlight.attrib[qn("w", "val")] == "yellow"
    size = properties.find(qn("w", "sz"))
    assert size is not None and size.attrib[qn("w", "val")] == "25"
    assert sha256_file(public_created) == source_sha256


def test_public_typed_edit_formats_table_cell_and_header_story(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    document = _read_document(
        project_root,
        tmp_path,
        public_created,
        "formatting-scopes-read.json",
    )
    body = next(story for story in document["stories"] if story["kind"] == "body")
    header = next(
        story for story in document["stories"] if story["kind"] == "header"
    )
    table_cell = next(
        paragraph for paragraph in body["paragraphs"] if paragraph["text"] == "PUBLIC"
    )
    header_paragraph = header["paragraphs"][0]
    output = tmp_path / "formatting-scopes.docx"
    request = _request(
        tmp_path,
        "formatting-scopes-edit.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "paragraph_style",
                        "target": {
                            "story": "body",
                            "part": body["part"],
                            "paragraph_index": table_cell["index"],
                            "expected_text": table_cell["text"],
                        },
                        "style": "Heading2",
                    },
                    {
                        "type": "run_style",
                        "target": {
                            "story": "header",
                            "part": header["part"],
                            "paragraph_index": header_paragraph["index"],
                            "expected_text": header_paragraph["text"],
                        },
                        "match": {
                            "text": header_paragraph["text"],
                            "expected_matches": 1,
                        },
                        "style": {"bold": True, "color": "1A2B3C"},
                    },
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    edit = result["diagnostics"]["operation_result"]["edit"]
    assert edit["selector_policy"] == "immutable-input-story-part-paragraph"
    preservation = result["diagnostics"]["operation_result"]["preservation"]
    assert set(preservation["changed_parts"]) == {
        body["part"],
        header["part"],
    }
    edited = _read_document(
        project_root,
        tmp_path,
        output,
        "formatting-scopes-result.json",
    )
    edited_body = next(
        story for story in edited["stories"] if story["kind"] == "body"
    )
    edited_header = next(
        story
        for story in edited["stories"]
        if story["part"] == header["part"]
    )
    assert edited_body["paragraphs"][table_cell["index"]]["style"] == "Heading2"
    assert edited_header["paragraphs"][header_paragraph["index"]]["runs"][0][
        "bold"
    ] is True
    assert sha256_file(public_created) == source_sha256


def test_public_typed_edit_reports_bounded_structural_diff(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "structure-diff.docx"
    request = _request(
        tmp_path,
        "structure-diff.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "paragraph_insert",
                        "target": {
                            "story": "body",
                            "paragraph_index": 1,
                            "expected_text": "Hello {name}",
                        },
                        "position": "after",
                        "text": "Inserted for structural diff",
                        "style": "Normal",
                    }
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    structural = result["diagnostics"]["operation_result"]["structure_diff"]
    assert structural["counts"]["paragraphs"]["delta"] == 1
    for name in ("tables", "images", "sections", "relationships", "parts"):
        assert structural["counts"][name]["delta"] == 0
    assert structural["changed_parts"] == ["word/document.xml"]
    assert structural["added_parts"] == []
    assert structural["removed_parts"] == []
