"""DOCX contract tests split by operation family."""

from tests.support.docx_contracts import *  # noqa: F401,F403
from tests.support.docx_contracts import (
    _MAX_CREATE_CELLS,
    _MAX_CREATE_NODES,
    _MAX_CREATE_TEXT_BYTES,
    _request,
)

def test_typed_edit_contract_accepts_stable_formatting_selectors(
    tmp_path: Path,
) -> None:
    source = tmp_path / "document.docx"
    output = tmp_path / "edited.docx"
    first = {
        "story": "body",
        "paragraph_index": 0,
        "expected_text": "Quarterly report",
    }
    second = {
        "story": "body",
        "paragraph_index": 1,
        "expected_text": "Quarterly total",
    }
    edits = [
        {"type": "paragraph_delete", "target": first},
        {
            "type": "paragraph_insert",
            "target": second,
            "position": "after",
            "text": "Reviewed total",
            "style": "Normal",
        },
        {"type": "paragraph_style", "target": second, "style": "Heading2"},
        {
            "type": "run_style",
            "target": second,
            "match": {"text": "Quarterly total", "expected_matches": 1},
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

    parsed = parse_docx_request(
        _request(
            "docx.edit",
            input=str(source),
            output=str(output),
            arguments={"edits": edits},
        )
    )

    assert parsed.arguments == {"edits": edits}


def test_replace_rejects_empty_rules(tmp_path: Path) -> None:
    source = tmp_path / "input.docx"
    with pytest.raises(DocumentSkillsError) as captured:
        parse_docx_request(
            _request(
                "docx.edit.replace-text",
                input=str(source),
                output=str(tmp_path / "output.docx"),
                arguments={"replacements": []},
            )
        )
    assert captured.value.code == ErrorCode.REQUEST_INVALID


def test_docx_paths_require_extension_and_distinct_non_in_place_output(
    tmp_path: Path,
) -> None:
    with pytest.raises(DocumentSkillsError) as wrong_extension:
        parse_docx_request(
            _request(
                "docx.read",
                input=str(tmp_path / "input.zip"),
            )
        )
    assert wrong_extension.value.code == ErrorCode.REQUEST_INVALID

    source = tmp_path / "same.docx"
    with pytest.raises(DocumentSkillsError) as same:
        parse_docx_request(
            _request(
                "docx.template.apply",
                input=str(source),
                output=str(source),
                arguments={"variables": {}},
            )
        )
    assert same.value.code == ErrorCode.OUTPUT_EQUALS_INPUT

    with pytest.raises(DocumentSkillsError) as in_place:
        parse_docx_request(
            _request(
                "docx.edit.replace-text",
                input=str(tmp_path / "input.docx"),
                output=str(tmp_path / "output.docx"),
                options={"in_place": True},
                arguments={
                    "replacements": [{"search": "a", "replace": "b"}]
                },
            )
        )
    assert in_place.value.code == ErrorCode.OUTPUT_EQUALS_INPUT


def test_dotx_is_accepted_only_as_template_apply_input(tmp_path: Path) -> None:
    template = tmp_path / "base.dotx"
    parsed = parse_docx_request(
        _request(
            "docx.template.apply",
            input=str(template),
            output=str(tmp_path / "rendered.docx"),
            arguments={"variables": {}},
        )
    )
    assert parsed.input_path == template.resolve()

    with pytest.raises(DocumentSkillsError) as read_dotx:
        parse_docx_request(_request("docx.read", input=str(template)))
    assert read_dotx.value.code == ErrorCode.REQUEST_INVALID

    with pytest.raises(DocumentSkillsError) as dotx_output:
        parse_docx_request(
            _request(
                "docx.template.apply",
                input=str(template),
                output=str(tmp_path / "rendered.dotx"),
                arguments={"variables": {}},
            )
        )
    assert dotx_output.value.code == ErrorCode.REQUEST_INVALID


def test_template_contract_accepts_only_bounded_declarative_paragraph_regions(
    tmp_path: Path,
) -> None:
    template = tmp_path / "base.docx"
    output = tmp_path / "rendered.docx"
    target = {
        "story": "body",
        "range": "paragraph",
        "paragraph_index": 2,
        "expected_text": "Customer {customer.name} in {region}",
    }
    parsed = parse_docx_request(
        _request(
            "docx.template.apply",
            input=str(template),
            output=str(output),
            arguments={
                "variables": {"title": "Accounts"},
                "regions": [
                    {
                        "type": "paragraph_repeat",
                        "target": target,
                        "items": [
                            {"customer.name": "Ada", "region": "APAC"},
                            {"customer.name": "Grace", "region": True},
                        ],
                    },
                    {
                        "type": "paragraph_condition",
                        "target": {
                            **target,
                            "paragraph_index": 3,
                            "expected_text": "Optional paragraph",
                        },
                        "include": False,
                    },
                ],
            },
        )
    )

    assert parsed.arguments["regions"] == [
        {
            "type": "paragraph_repeat",
            "target": target,
            "items": [
                {"customer.name": "Ada", "region": "APAC"},
                {"customer.name": "Grace", "region": "true"},
            ],
        },
        {
            "type": "paragraph_condition",
            "target": {
                **target,
                "paragraph_index": 3,
                "expected_text": "Optional paragraph",
            },
            "include": False,
        },
    ]

    with pytest.raises(DocumentSkillsError) as expression:
        parse_docx_request(
            _request(
                "docx.template.apply",
                input=str(template),
                output=str(output),
                arguments={
                    "variables": {},
                    "regions": [
                        {
                            "type": "paragraph_condition",
                            "target": target,
                            "include": {"expression": "customer.active"},
                        }
                    ],
                },
            )
        )
    assert expression.value.code == ErrorCode.REQUEST_INVALID
