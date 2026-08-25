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


def test_parse_edit_accepts_hash_bound_page_insert():
    source = str(Path("insert.pdf").resolve())
    parsed = parse_pdf_request({
        "schema_version": "1.0",
        "operation": "pdf.edit",
        "input": "in.pdf",
        "output": "out.pdf",
        "arguments": {
            "primitives": [{
                "type": "page_insert",
                "input": source,
                "source_sha256": "0" * 64,
                "at": 2,
                "pages": [3, 1],
            }],
        },
    })

    assert parsed.arguments["primitives"][0] == {
        "type": "page_insert",
        "input": source,
        "source_sha256": "0" * 64,
        "at": 2,
        "pages": [3, 1],
    }


def test_parse_edit_page_insert_requires_source_hash():
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": "in.pdf",
            "output": "out.pdf",
            "arguments": {
                "primitives": [{
                    "type": "page_insert",
                    "input": "insert.pdf",
                    "at": 1,
                }],
            },
        })

    assert exc.value.details["field"] == "primitives.0.source_sha256"


def test_parse_edit_accepts_hash_bound_merge_inputs():
    primary = str(Path("primary.pdf").resolve())
    donor = str(Path("donor.pdf").resolve())
    parsed = parse_pdf_request({
        "schema_version": "1.0",
        "operation": "pdf.edit",
        "input": primary,
        "output": "out.pdf",
        "arguments": {
            "primitives": [{
                "type": "merge",
                "inputs": [
                    {"input": primary, "source_sha256": "A" * 64},
                    {"input": donor, "source_sha256": "b" * 64},
                ],
            }],
        },
    })

    assert parsed.arguments["primitives"][0]["inputs"] == [
        {"input": primary, "source_sha256": "a" * 64},
        {"input": donor, "source_sha256": "b" * 64},
    ]


@pytest.mark.parametrize(
    "inputs, field",
    [
        (["primary.pdf", "donor.pdf"], "primitives.0.inputs.0"),
        (
            [
                {"input": "primary.pdf", "source_sha256": "0" * 64},
                {"input": "donor.pdf"},
            ],
            "primitives.0.inputs.1.source_sha256",
        ),
        (
            [
                {"input": "primary.pdf", "source_sha256": "0" * 64},
                {"input": "donor.pdf", "source_sha256": "bad"},
            ],
            "primitives.0.inputs.1.source_sha256",
        ),
    ],
)
def test_parse_edit_rejects_unbound_merge_inputs(inputs, field):
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": "primary.pdf",
            "output": "out.pdf",
            "arguments": {"primitives": [{"type": "merge", "inputs": inputs}]},
        })

    assert exc.value.details["field"] == field


def test_parse_edit_rejects_merge_primary_path_mismatch():
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": "primary.pdf",
            "output": "out.pdf",
            "arguments": {
                "primitives": [{
                    "type": "merge",
                    "inputs": [
                        {"input": "other.pdf", "source_sha256": "0" * 64},
                        {"input": "donor.pdf", "source_sha256": "1" * 64},
                    ],
                }],
            },
        })

    assert exc.value.details["field"] == "primitives.0.inputs.0.input"


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
                "source_sha256": "0" * 64,
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
            "arguments": {
                "source_sha256": "0" * 64,
                "blocks": [],
                "rewrites": [],
            },
        })


def test_parse_rewrite_requires_source_sha256():
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": "in.pdf",
            "output": "out.pdf",
            "arguments": {
                "blocks": [{
                    "page": 1,
                    "bbox": [0, 0, 100, 20],
                    "text": "x",
                    "font": "F1",
                    "size": 12,
                    "color": None,
                }],
                "rewrites": [{"block_index": 0, "text": "y"}],
            },
        })

    assert exc.value.details["field"] == "source_sha256"


@pytest.mark.parametrize("source_sha256", ["", "0" * 63, "g" * 64, 0])
def test_parse_rewrite_rejects_malformed_source_sha256(source_sha256):
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": "in.pdf",
            "output": "out.pdf",
            "arguments": {
                "source_sha256": source_sha256,
                "blocks": [{
                    "page": 1,
                    "bbox": [0, 0, 100, 20],
                    "text": "x",
                    "font": "F1",
                    "size": 12,
                    "color": None,
                }],
                "rewrites": [{"block_index": 0, "text": "y"}],
            },
        })

    assert exc.value.details["field"] == "source_sha256"


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


def test_parse_read_accepts_bounded_column_and_bbox_selection():
    parsed = parse_pdf_request({
        "schema_version": "1.0",
        "operation": "pdf.read",
        "input": "test.pdf",
        "arguments": {
            "pages": [2, 1],
            "bbox": [10, 20, 300, 400],
            "reading_order": "columns",
            "column_count": 2,
        },
    })

    assert parsed.arguments["pages"] == [2, 1]
    assert parsed.arguments["bbox"] == [10.0, 20.0, 300.0, 400.0]
    assert parsed.arguments["reading_order"] == "columns"
    assert parsed.arguments["column_count"] == 2


def test_parse_inspect_defaults():
    parsed = parse_pdf_request({
        "schema_version": "1.0",
        "operation": "pdf.inspect.structure",
        "input": "test.pdf",
        "arguments": {},
    })
    assert parsed.arguments["include_hashes"] is True
    assert parsed.arguments["max_objects"] >= 1


def test_parse_render_accepts_bound_visual_comparison(tmp_path: Path):
    reference = tmp_path / "reference.pdf"
    parsed = parse_pdf_request({
        "schema_version": "1.0",
        "operation": "pdf.render",
        "input": "test.pdf",
        "output": "render.zip",
        "arguments": {
            "pages": [1],
            "compare_to": str(reference),
            "reference_sha256": "a" * 64,
            "expected_change_regions": [
                {"page": 1, "bbox": [10, 20, 30, 40]}
            ],
            "channel_tolerance": 3,
            "max_unexpected_change_ratio": 0.01,
            "minimum_expected_change_ratio": 0.2,
        },
    })

    assert parsed.arguments["compare_to"] == str(reference.resolve())
    assert parsed.arguments["reference_sha256"] == "a" * 64
    assert parsed.arguments["expected_change_regions"][0]["bbox"] == [
        10.0,
        20.0,
        30.0,
        40.0,
    ]


@pytest.mark.parametrize(
    "arguments,field",
    [
        ({"compare_to": "reference.pdf"}, "reference_sha256"),
        ({"reference_sha256": "a" * 64}, "compare_to"),
        (
            {
                "compare_to": "reference.pdf",
                "reference_sha256": "a" * 64,
                "minimum_expected_change_ratio": 0.1,
            },
            "expected_change_regions",
        ),
    ],
)
def test_parse_render_rejects_unbound_comparison(arguments: dict, field: str):
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.render",
            "input": "test.pdf",
            "output": "render.zip",
            "arguments": arguments,
        })

    assert exc.value.details["field"] == field


def test_parse_encrypt_accepts_only_strong_bounded_distinct_secrets():
    parsed = parse_pdf_request({
        "schema_version": "1.0",
        "operation": "pdf.encrypt",
        "input": "in.pdf",
        "output": "out.pdf",
        "secrets": {
            "user_password": "reader-secret",
            "owner_password": "owner-secret",
        },
        "arguments": {
            "algorithm": "AES-256-R5",
            "permissions": ["print", "extract"],
            "encrypt_metadata": True,
        },
    })

    assert parsed.arguments["algorithm"] == "AES-256-R5"
    assert parsed.arguments["permissions"] == ["extract", "print"]

    for secrets in (
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
                "secrets": secrets,
                "arguments": {},
            })
        assert exc.value.code.value == "DS_REQUEST_INVALID"

    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.encrypt",
            "input": "in.pdf",
            "output": "out.pdf",
            "arguments": {
                "user_password": "legacy-reader-secret",
                "owner_password": "legacy-owner-secret",
            },
        })
    assert exc.value.code.value == "DS_REQUEST_INVALID"
    assert exc.value.details["field"] == "arguments"


def test_parse_encrypt_rejects_weak_algorithm_before_output():
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pdf_request({
            "schema_version": "1.0",
            "operation": "pdf.encrypt",
            "input": "in.pdf",
            "output": "out.pdf",
            "secrets": {
                "user_password": "reader-secret",
                "owner_password": "owner-secret",
            },
            "arguments": {
                "algorithm": "RC4-128",
            },
        })

    assert exc.value.code.value == "DS_ENHANCEMENT_REQUIRED"


@pytest.mark.parametrize("mode", ["balanced", "aggressive"])
def test_parse_compress_accepts_evidence_backed_image_modes(mode: str):
    parsed = parse_pdf_request({
        "schema_version": "1.0",
        "operation": "pdf.compress",
        "input": "in.pdf",
        "output": "out.pdf",
        "arguments": {"mode": mode},
    })

    assert parsed.arguments == {"mode": mode}
