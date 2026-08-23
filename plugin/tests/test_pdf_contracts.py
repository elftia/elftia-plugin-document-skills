"""PDF operation argument contract tests.

Module provenance: original Elftia-authored test suite.
"""

from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pdf.contracts import (
    PDF_OPERATIONS,
    parse_pdf_request,
)


def test_pdf_operations_set_includes_provider_security_and_optimization():
    assert PDF_OPERATIONS == frozenset(
        {
            "pdf.read",
            "pdf.inspect.structure",
            "pdf.create",
            "pdf.edit",
            "pdf.rewrite.apply",
            "pdf.images.extract",
            "pdf.encrypt",
            "pdf.decrypt",
            "pdf.compress",
            "pdf.render",
            "pdf.ocr",
            "pdf.table.extract",
        }
    )


def test_parse_read_rejects_unknown_argument():
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": "test.pdf",
            "arguments": {"unknown": True},
        })
    assert exc.value.code.value == "DS_REQUEST_INVALID"


def test_parse_read_requires_input():
    with pytest.raises(DocumentSkillsError):
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.read",
            "arguments": {},
        })


def test_parse_read_rejects_output():
    with pytest.raises(DocumentSkillsError):
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": "test.pdf",
            "output": "out.pdf",
            "arguments": {},
        })


def test_parse_create_requires_output():
    with pytest.raises(DocumentSkillsError):
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.create",
            "arguments": {"document": {"metadata": {}, "page_size": "A4", "pages": []}},
        })


def test_parse_create_rejects_input():
    with pytest.raises(DocumentSkillsError):
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.create",
            "input": "in.pdf",
            "output": "out.pdf",
            "arguments": {"document": {"metadata": {}, "page_size": "A4", "pages": []}},
        })


def test_parse_edit_requires_distinct_paths():
    same = str(Path("same.pdf").resolve())
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": same,
            "output": same,
            "arguments": {"primitives": [{"type": "rotate", "pages": [1], "degrees": 90}]},
        })
    assert exc.value.code.value == "DS_OUTPUT_EQUALS_INPUT"


def test_parse_edit_requires_primitives():
    with pytest.raises(DocumentSkillsError):
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": "in.pdf",
            "output": "out.pdf",
            "arguments": {"primitives": []},
        })


def test_parse_edit_rejects_unknown_primitive_type():
    with pytest.raises(DocumentSkillsError):
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": "in.pdf",
            "output": "out.pdf",
            "arguments": {"primitives": [{"type": "invalid"}]},
        })


def test_parse_input_must_have_pdf_extension():
    with pytest.raises(DocumentSkillsError):
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": "test.docx",
            "arguments": {},
        })


def test_parse_rewrite_requires_distinct_paths():
    same = str(Path("same.pdf").resolve())
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": same,
            "output": same,
            "arguments": {
                "blocks": [{"page": 1, "bbox": [0, 0, 100, 20], "text": "x", "font": "F1", "size": 12, "color": None}],
                "rewrites": [{"block_index": 0, "text": "y"}],
            },
        })
    assert exc.value.code.value == "DS_OUTPUT_EQUALS_INPUT"


def test_parse_rewrite_requires_blocks():
    with pytest.raises(DocumentSkillsError):
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": "in.pdf",
            "output": "out.pdf",
            "arguments": {"blocks": [], "rewrites": []},
        })


def test_parse_create_accepts_one_nonblank_page():
    parsed = parse_pdf_request({
        "schema_version": "1.0",
        "operation": "pdf.create",
        "output": "out.pdf",
        "arguments": {
            "document": {
                "metadata": {"title": "T", "author": "A", "subject": ""},
                "page_size": "A4",
                "pages": [
                    {
                        "blocks": [
                            {
                                "type": "paragraph",
                                "text": "Text",
                                "style": None,
                                "table": None,
                                "image": None,
                                "shape": None,
                            }
                        ],
                        "metadata": None,
                    }
                ],
            }
        },
    })

    assert len(parsed.arguments["document"]["pages"]) == 1


def test_parse_create_rejects_implicit_blank_page():
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": "out.pdf",
            "arguments": {
                "document": {
                    "metadata": {"title": "T", "author": "A", "subject": ""},
                    "page_size": "A4",
                    "pages": [{"blocks": [], "metadata": None}],
                }
            },
        })

    assert exc.value.details["field"] == "pages.0.allow_blank"


def test_parse_create_accepts_explicit_blank_page():
    parsed = parse_pdf_request({
        "schema_version": "1.0",
        "operation": "pdf.create",
        "output": "out.pdf",
        "arguments": {
            "document": {
                "metadata": {"title": "T", "author": "A", "subject": ""},
                "page_size": "A4",
                "pages": [
                    {"blocks": [], "metadata": None, "allow_blank": True}
                ],
            }
        },
    })

    assert parsed.arguments["document"]["pages"][0]["allow_blank"] is True


def test_parse_read_defaults():
    parsed = parse_pdf_request({
        "schema_version": "1.0",
        "operation": "pdf.read",
        "input": "test.pdf",
        "arguments": {},
    })
    assert parsed.arguments["include_annotations"] is True
    assert parsed.arguments["include_forms"] is True
    assert parsed.arguments["max_pages"] >= 1


def test_parse_inspect_defaults():
    parsed = parse_pdf_request({
        "schema_version": "1.0",
        "operation": "pdf.inspect.structure",
        "input": "test.pdf",
        "arguments": {},
    })
    assert parsed.arguments["include_hashes"] is True
    assert parsed.arguments["max_objects"] >= 1


def test_parse_encrypt_accepts_only_strong_bounded_distinct_secrets():
    parsed = parse_pdf_request({
        "schema_version": "1.0",
        "operation": "pdf.encrypt",
        "input": "in.pdf",
        "output": "out.pdf",
        "arguments": {
            "user_password": "reader-secret",
            "owner_password": "owner-secret",
            "algorithm": "AES-256-R5",
            "permissions": ["print", "extract"],
            "encrypt_metadata": True,
        },
    })

    assert parsed.arguments["algorithm"] == "AES-256-R5"
    assert parsed.arguments["permissions"] == ["extract", "print"]

    for arguments in (
        {
            "user_password": "same-secret",
            "owner_password": "same-secret",
        },
        {
            "user_password": "u" * 128,
            "owner_password": "owner-secret",
        },
    ):
        with pytest.raises(DocumentSkillsError) as exc:
            parse_pdf_request({
                "schema_version": "1.0",
                "operation": "pdf.encrypt",
                "input": "in.pdf",
                "output": "out.pdf",
                "arguments": arguments,
            })
        assert exc.value.code.value == "DS_REQUEST_INVALID"


def test_parse_encrypt_rejects_weak_algorithm_before_output():
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.encrypt",
            "input": "in.pdf",
            "output": "out.pdf",
            "arguments": {
                "user_password": "reader-secret",
                "owner_password": "owner-secret",
                "algorithm": "RC4-128",
            },
        })

    assert exc.value.code.value == "DS_ENHANCEMENT_REQUIRED"


@pytest.mark.parametrize("mode", ["balanced", "aggressive"])
def test_parse_compress_keeps_unimplemented_lossy_modes_honest(mode: str):
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.compress",
            "input": "in.pdf",
            "output": "out.pdf",
            "arguments": {"mode": mode},
        })

    assert exc.value.code.value == "DS_ENHANCEMENT_REQUIRED"
