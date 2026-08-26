"""DOCX contract tests split by operation family."""

from tests.support.docx_contracts import *  # noqa: F401,F403
from tests.support.docx_contracts import (
    _MAX_CREATE_CELLS,
    _MAX_CREATE_NODES,
    _MAX_CREATE_TEXT_BYTES,
    _request,
)

def test_schema_validation_contract_is_read_only_and_bounded(tmp_path: Path) -> None:
    source = tmp_path / "document.docx"
    parsed = parse_docx_request(
        _request(
            "docx.validate.schema",
            input=str(source),
            arguments={"max_errors": 250},
        )
    )
    assert parsed.arguments == {"max_errors": 250}

    with pytest.raises(DocumentSkillsError) as output:
        parse_docx_request(
            _request(
                "docx.validate.schema",
                input=str(source),
                output=str(tmp_path / "report.json"),
                arguments={},
            )
        )
    assert output.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as unbounded:
        parse_docx_request(
            _request(
                "docx.validate.schema",
                input=str(source),
                arguments={"max_errors": 1_001},
            )
        )
    assert unbounded.value.code == ErrorCode.REQUEST_INVALID


def test_convert_pdf_contract_requires_distinct_pdf_output_and_byte_bound(
    tmp_path: Path,
) -> None:
    source = tmp_path / "document.docx"
    output = tmp_path / "document.pdf"
    parsed = parse_docx_request(
        _request(
            "docx.convert.pdf",
            input=str(source),
            output=str(output),
            options={"fidelity": "enhanced"},
            arguments={"max_output_bytes": 8 * 1024 * 1024},
        )
    )
    assert parsed.input_path == source.resolve()
    assert parsed.output_path == output.resolve()
    assert parsed.arguments == {"max_output_bytes": 8 * 1024 * 1024}

    for invalid_output in (source, tmp_path / "document.docx"):
        with pytest.raises(DocumentSkillsError) as captured:
            parse_docx_request(
                _request(
                    "docx.convert.pdf",
                    input=str(source),
                    output=str(invalid_output),
                    arguments={},
                )
            )
        assert captured.value.code in {
            ErrorCode.OUTPUT_EQUALS_INPUT,
            ErrorCode.REQUEST_INVALID,
        }

    with pytest.raises(DocumentSkillsError) as unbounded:
        parse_docx_request(
            _request(
                "docx.convert.pdf",
                input=str(source),
                output=str(output),
                arguments={"max_output_bytes": 128 * 1024 * 1024 + 1},
            )
        )
    assert unbounded.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as unknown:
        parse_docx_request(
            _request(
                "docx.convert.pdf",
                input=str(source),
                output=str(output),
                arguments={"rebuild": True},
            )
        )
    assert unknown.value.code == ErrorCode.REQUEST_INVALID


def test_convert_legacy_contract_requires_doc_input_and_matching_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "document.doc"
    for target_format in ("docx", "pdf"):
        output = tmp_path / f"converted.{target_format}"
        parsed = parse_docx_request(
            _request(
                "docx.convert.legacy",
                input=str(source),
                output=str(output),
                arguments={
                    "format": target_format,
                    "max_output_bytes": 8 * 1024 * 1024,
                },
            )
        )
        assert parsed.arguments["format"] == target_format

    with pytest.raises(DocumentSkillsError) as modern_input:
        parse_docx_request(
            _request(
                "docx.convert.legacy",
                input=str(tmp_path / "document.docx"),
                output=str(tmp_path / "converted.docx"),
                arguments={"format": "docx"},
            )
        )
    assert modern_input.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as mismatched_output:
        parse_docx_request(
            _request(
                "docx.convert.legacy",
                input=str(source),
                output=str(tmp_path / "converted.pdf"),
                arguments={"format": "docx"},
            )
        )
    assert mismatched_output.value.code == ErrorCode.REQUEST_INVALID


def test_docm_edit_contract_requires_explicit_keep_vba(tmp_path: Path) -> None:
    source = tmp_path / "macro.docm"
    output = tmp_path / "edited.docm"
    parsed = parse_docx_request(
        _request(
            "docx.edit",
            input=str(source),
            output=str(output),
            arguments={
                "keep_vba": True,
                "edits": [
                    {
                        "type": "paragraph_style",
                        "target": {
                            "story": "body",
                            "paragraph_index": 0,
                            "expected_text": "Macro",
                        },
                        "style": "Normal",
                    }
                ],
            },
        )
    )
    assert parsed.arguments["keep_vba"] is True

    with pytest.raises(DocumentSkillsError) as missing_opt_in:
        parse_docx_request(
            _request(
                "docx.edit",
                input=str(source),
                output=str(output),
                arguments={"edits": []},
            )
        )
    assert missing_opt_in.value.code == ErrorCode.REQUEST_INVALID


def test_render_contract_bounds_pdf_page_evidence(tmp_path: Path) -> None:
    source = tmp_path / "document.docx"
    output = tmp_path / "rendered.pdf"
    parsed = parse_docx_request(
        _request(
            "docx.render",
            input=str(source),
            output=str(output),
            options={"fidelity": "enhanced"},
            arguments={
                "format": "pdf",
                "page_range": {"start": 2, "end": 4},
                "dpi": None,
                "max_pages": 3,
                "max_total_bytes": 8 * 1024 * 1024,
            },
        )
    )
    assert parsed.arguments == {
        "format": "pdf",
        "page_range": {"start": 2, "end": 4},
        "dpi": None,
        "include_page_pngs": False,
        "layout_profile": "professional-v1",
        "max_pages": 3,
        "max_page_bytes": 4 * 1024 * 1024,
        "max_png_total_bytes": 512 * 1024,
        "max_total_bytes": 8 * 1024 * 1024,
    }

    bounded_png = parse_docx_request(
        _request(
            "docx.render",
            input=str(source),
            output=str(output),
            arguments={
                "include_page_pngs": True,
                "dpi": 96,
                "max_png_total_bytes": 1_000_000,
            },
        )
    )
    assert bounded_png.arguments["max_png_total_bytes"] == 1_000_000

    with pytest.raises(DocumentSkillsError) as oversized_public_result:
        parse_docx_request(
            _request(
                "docx.render",
                input=str(source),
                output=str(output),
                arguments={
                    "include_page_pngs": True,
                    "dpi": 96,
                    "max_png_total_bytes": 1_000_001,
                },
            )
        )
    assert oversized_public_result.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as too_many_pages:
        parse_docx_request(
            _request(
                "docx.render",
                input=str(source),
                output=str(output),
                arguments={
                    "format": "pdf",
                    "page_range": {"start": 1, "end": 4},
                    "max_pages": 3,
                },
            )
        )
    assert too_many_pages.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as png:
        parse_docx_request(
            _request(
                "docx.render",
                input=str(source),
                output=str(output),
                arguments={"format": "png", "dpi": 144},
            )
        )
    assert png.value.code == ErrorCode.ENHANCEMENT_REQUIRED
