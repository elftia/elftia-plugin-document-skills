"""DOCX contract tests split by operation family."""

from tests.support.docx_contracts import *  # noqa: F401,F403
from tests.support.docx_contracts import (
    _MAX_CREATE_CELLS,
    _MAX_CREATE_NODES,
    _MAX_CREATE_TEXT_BYTES,
    _request,
)

@pytest.mark.parametrize(
    "operation",
    [
        "docx.read",
        "docx.inspect.structure",
        "docx.create",
        "docx.convert.legacy",
        "docx.merge",
        "docx.edit.replace-text",
        "docx.template.apply",
    ],
)
def test_docx_operations_require_their_artifact_paths(operation: str) -> None:
    with pytest.raises(DocumentSkillsError) as captured:
        parse_docx_request(_request(operation))
    assert captured.value.code == ErrorCode.REQUEST_INVALID


def test_docx_read_rejects_unknown_arguments(tmp_path: Path) -> None:
    source = tmp_path / "input.docx"
    source.write_bytes(b"PK")
    with pytest.raises(DocumentSkillsError) as captured:
        parse_docx_request(
            _request(
                "docx.read",
                input=str(source),
                arguments={"not_supported": True},
            )
        )
    assert captured.value.code == ErrorCode.REQUEST_INVALID


def test_revisions_read_contract_is_closed_and_bounded(tmp_path: Path) -> None:
    source = tmp_path / "tracked.docx"
    parsed = parse_docx_request(
        _request(
            "docx.revisions.read",
            input=str(source),
            arguments={"max_revisions": 250},
        )
    )
    assert parsed.input_path == source.resolve()
    assert parsed.output_path is None
    assert parsed.arguments == {"max_revisions": 250}

    with pytest.raises(DocumentSkillsError) as unknown:
        parse_docx_request(
            _request(
                "docx.revisions.read",
                input=str(source),
                arguments={"include_raw_xml": True},
            )
        )
    assert unknown.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as unbounded:
        parse_docx_request(
            _request(
                "docx.revisions.read",
                input=str(source),
                arguments={"max_revisions": 10_001},
            )
        )
    assert unbounded.value.code == ErrorCode.REQUEST_INVALID


def test_revisions_contract_supports_bounded_filters_and_immutable_scopes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tracked.docx"
    output = tmp_path / "accepted.docx"
    parsed_read = parse_docx_request(
        _request(
            "docx.revisions.read",
            input=str(source),
            arguments={
                "max_revisions": 25,
                "filters": {
                    "authors": ["Alice", "Bob"],
                    "types": ["insertion", "deletion"],
                    "date_from": "2026-01-01T00:00:00Z",
                    "date_to": "2026-12-31T23:59:59Z",
                },
                "scope": {
                    "story": "body",
                    "range": "paragraph",
                    "paragraph_index": 3,
                    "expected_text": "Tracked paragraph",
                },
            },
        )
    )
    assert parsed_read.arguments == {
        "max_revisions": 25,
        "filters": {
            "authors": ["Alice", "Bob"],
            "types": ["insertion", "deletion"],
            "date_from": "2026-01-01T00:00:00Z",
            "date_to": "2026-12-31T23:59:59Z",
        },
        "scope": {
            "story": "body",
            "range": "paragraph",
            "paragraph_index": 3,
            "expected_text": "Tracked paragraph",
        },
    }

    parsed_apply = parse_docx_request(
        _request(
            "docx.revisions.apply",
            input=str(source),
            output=str(output),
            arguments={
                "action": "reject",
                "filters": {"authors": ["Alice"]},
                "scope": {
                    "story": "body",
                    "range": "table",
                    "table_index": 1,
                    "expected_table_sha256": "A" * 64,
                },
            },
        )
    )
    assert parsed_apply.arguments == {
        "action": "reject",
        "revision_ids": [],
        "filters": {"authors": ["Alice"]},
        "scope": {
            "story": "body",
            "range": "table",
            "table_index": 1,
            "expected_table_sha256": "a" * 64,
        },
    }

    for filters in (
        {"authors": ["Alice", "Alice"]},
        {"types": ["format-change"]},
        {"date_from": "2026-02-01T00:00:00Z", "date_to": "2026-01-01T00:00:00Z"},
    ):
        with pytest.raises(DocumentSkillsError) as rejected:
            parse_docx_request(
                _request(
                    "docx.revisions.read",
                    input=str(source),
                    arguments={"filters": filters},
                )
            )
        assert rejected.value.code == ErrorCode.REQUEST_INVALID


def test_revisions_apply_contract_requires_bounded_distinct_targets(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tracked.docx"
    output = tmp_path / "accepted.docx"
    parsed = parse_docx_request(
        _request(
            "docx.revisions.apply",
            input=str(source),
            output=str(output),
            arguments={"action": "accept", "revision_ids": ["7", "change-9"]},
        )
    )
    assert parsed.arguments == {
        "action": "accept",
        "revision_ids": ["7", "change-9"],
    }

    with pytest.raises(DocumentSkillsError) as action:
        parse_docx_request(
            _request(
                "docx.revisions.apply",
                input=str(source),
                output=str(output),
                arguments={"action": "delete"},
            )
        )
    assert action.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as duplicates:
        parse_docx_request(
            _request(
                "docx.revisions.apply",
                input=str(source),
                output=str(output),
                arguments={"action": "reject", "revision_ids": ["7", "7"]},
            )
        )
    assert duplicates.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as same:
        parse_docx_request(
            _request(
                "docx.revisions.apply",
                input=str(source),
                output=str(source),
                arguments={"action": "accept"},
            )
        )
    assert same.value.code == ErrorCode.OUTPUT_EQUALS_INPUT
