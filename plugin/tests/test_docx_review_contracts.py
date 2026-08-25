"""DOCX contract tests split by operation family."""

from tests.support.docx_contracts import *  # noqa: F401,F403
from tests.support.docx_contracts import (
    _MAX_CREATE_CELLS,
    _MAX_CREATE_NODES,
    _MAX_CREATE_TEXT_BYTES,
    _request,
)

def test_comments_read_contract_is_closed_and_bounded(tmp_path: Path) -> None:
    source = tmp_path / "commented.docx"
    parsed = parse_docx_request(
        _request(
            "docx.comments.read",
            input=str(source),
            arguments={"max_comments": 500},
        )
    )
    assert parsed.arguments == {"max_comments": 500}

    with pytest.raises(DocumentSkillsError) as unknown:
        parse_docx_request(
            _request(
                "docx.comments.read",
                input=str(source),
                arguments={"include_raw_xml": True},
            )
        )
    assert unknown.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as unbounded:
        parse_docx_request(
            _request(
                "docx.comments.read",
                input=str(source),
                arguments={"max_comments": 10_001},
            )
        )
    assert unbounded.value.code == ErrorCode.REQUEST_INVALID


def test_comments_add_contract_requires_explicit_paragraph_anchor(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.docx"
    output = tmp_path / "commented.docx"
    parsed = parse_docx_request(
        _request(
            "docx.comments.add",
            input=str(source),
            output=str(output),
            arguments={
                "author": "Reviewer",
                "text": "Please clarify this paragraph.",
                "anchor": {
                    "story": "body",
                    "paragraph_index": 2,
                    "expected_text": "The paragraph under review.",
                    "range": "paragraph",
                },
            },
        )
    )
    assert parsed.arguments["anchor"] == {
        "story": "body",
        "paragraph_index": 2,
        "expected_text": "The paragraph under review.",
        "range": "paragraph",
    }
    assert parsed.arguments["parent_comment_id"] is None

    reply = parse_docx_request(
        _request(
            "docx.comments.add",
            input=str(source),
            output=str(output),
            arguments={
                "author": "Reviewer",
                "text": "Reply",
                "parent_comment_id": "7",
            },
        )
    )
    assert reply.arguments == {
        "author": "Reviewer",
        "text": "Reply",
        "anchor": None,
        "parent_comment_id": "7",
    }

    with pytest.raises(DocumentSkillsError) as ambiguous:
        parse_docx_request(
            _request(
                "docx.comments.add",
                input=str(source),
                output=str(output),
                arguments={
                    "author": "Reviewer",
                    "text": "Reply",
                    "parent_comment_id": "7",
                    "anchor": {
                        "story": "body",
                        "paragraph_index": 2,
                        "expected_text": "Paragraph",
                        "range": "paragraph",
                    },
                },
            )
        )
    assert ambiguous.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as missing_target:
        parse_docx_request(
            _request(
                "docx.comments.add",
                input=str(source),
                output=str(output),
                arguments={"author": "Reviewer", "text": "Comment"},
            )
        )
    assert missing_target.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as implicit_range:
        parse_docx_request(
            _request(
                "docx.comments.add",
                input=str(source),
                output=str(output),
                arguments={
                    "author": "Reviewer",
                    "text": "Comment",
                    "anchor": {
                        "story": "body",
                        "paragraph_index": 2,
                        "expected_text": "Paragraph",
                    },
                },
            )
        )
    assert implicit_range.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as empty_author:
        parse_docx_request(
            _request(
                "docx.comments.add",
                input=str(source),
                output=str(output),
                arguments={
                    "author": "",
                    "text": "Comment",
                    "anchor": {
                        "story": "body",
                        "paragraph_index": 2,
                        "expected_text": "Paragraph",
                        "range": "paragraph",
                    },
                },
            )
        )
    assert empty_author.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as same:
        parse_docx_request(
            _request(
                "docx.comments.add",
                input=str(source),
                output=str(source),
                arguments={
                    "author": "Reviewer",
                    "text": "Comment",
                    "anchor": {
                        "story": "body",
                        "paragraph_index": 2,
                        "expected_text": "Paragraph",
                        "range": "paragraph",
                    },
                },
            )
        )
    assert same.value.code == ErrorCode.OUTPUT_EQUALS_INPUT


def test_comments_resolve_contract_is_closed_and_distinct(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    output = tmp_path / "resolved.docx"
    parsed = parse_docx_request(
        _request(
            "docx.comments.resolve",
            input=str(source),
            output=str(output),
            arguments={"comment_id": "7", "resolved": True},
        )
    )
    assert parsed.arguments == {"comment_id": "7", "resolved": True}

    with pytest.raises(DocumentSkillsError) as non_boolean:
        parse_docx_request(
            _request(
                "docx.comments.resolve",
                input=str(source),
                output=str(output),
                arguments={"comment_id": "7", "resolved": 1},
            )
        )
    assert non_boolean.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as invalid_id:
        parse_docx_request(
            _request(
                "docx.comments.resolve",
                input=str(source),
                output=str(output),
                arguments={"comment_id": "reply-7", "resolved": False},
            )
        )
    assert invalid_id.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as same:
        parse_docx_request(
            _request(
                "docx.comments.resolve",
                input=str(source),
                output=str(source),
                arguments={"comment_id": "7", "resolved": False},
            )
        )
    assert same.value.code == ErrorCode.OUTPUT_EQUALS_INPUT
