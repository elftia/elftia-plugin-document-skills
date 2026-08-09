from pathlib import Path

import pytest

from document_skills_core.cli import execute_request
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.formats.docx.contracts import parse_docx_request

_MAX_CREATE_CELLS = 8_192
_MAX_CREATE_NODES = 10_000
_MAX_CREATE_TEXT_BYTES = 524_288


def _request(operation: str, **values: object) -> dict[str, object]:
    request: dict[str, object] = {
        "schema_version": "1.0",
        "operation": operation,
        "arguments": {},
    }
    request.update(values)
    return request


@pytest.mark.parametrize(
    "operation",
    [
        "docx.read",
        "docx.inspect.structure",
        "docx.create",
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


def test_create_accepts_blocks_alone_and_defaults_the_rest(tmp_path: Path) -> None:
    """Nothing but `blocks` is required, and nothing else is fabricated."""

    parsed = parse_docx_request(
        _request(
            "docx.create",
            output=str(tmp_path / "output.docx"),
            arguments={
                "report": {"blocks": [{"type": "paragraph", "text": "Body"}]}
            },
        )
    )
    report = parsed.arguments["report"]
    assert report["image"] is None
    assert report["header"] is None
    assert report["footer"] is None
    assert report["sections"] == [{"orientation": "portrait", "title": None}]
    assert report["blocks"] == [
        {"type": "paragraph", "text": "Body", "style": None}
    ]


@pytest.mark.parametrize(
    "report",
    [
        {"blocks": [{"type": "paragraph", "text": "Body"}], "header": ""},
        {"blocks": [{"type": "paragraph", "text": "Body"}], "footer": ""},
        {"blocks": [{"type": "paragraph", "text": "Body"}], "image": None},
        {
            "blocks": [{"type": "heading", "text": "Only a heading"}],
            "sections": [{"orientation": "landscape"}],
        },
    ],
)
def test_create_treats_report_members_as_opt_in(
    tmp_path: Path,
    report: dict[str, object],
) -> None:
    parsed = parse_docx_request(
        _request(
            "docx.create",
            output=str(tmp_path / "output.docx"),
            arguments={"report": report},
        )
    )
    parsed_report = parsed.arguments["report"]
    assert parsed_report["image"] is None
    assert parsed_report["header"] is None
    assert parsed_report["footer"] is None
    assert 1 <= len(parsed_report["sections"]) <= 32


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5, 6])
def test_create_accepts_every_supported_heading_level(
    tmp_path: Path,
    level: int,
) -> None:
    """A 1.1.1-style outline must not have to be flattened to fit the contract."""

    parsed = parse_docx_request(
        _request(
            "docx.create",
            output=str(tmp_path / "output.docx"),
            arguments={
                "report": {
                    "blocks": [{"type": "heading", "text": "H", "level": level}]
                }
            },
        )
    )
    assert parsed.arguments["report"]["blocks"][0]["level"] == level


@pytest.mark.parametrize("level", [0, 7, 99, -1])
def test_create_rejects_heading_levels_outside_the_style_set(
    tmp_path: Path,
    level: int,
) -> None:
    with pytest.raises(DocumentSkillsError) as captured:
        parse_docx_request(
            _request(
                "docx.create",
                output=str(tmp_path / "output.docx"),
                arguments={
                    "report": {
                        "blocks": [{"type": "heading", "text": "H", "level": level}]
                    }
                },
            )
        )
    assert captured.value.code == ErrorCode.REQUEST_INVALID


def test_create_accepts_positioned_image_blocks(tmp_path: Path) -> None:
    parsed = parse_docx_request(
        _request(
            "docx.create",
            output=str(tmp_path / "output.docx"),
            arguments={
                "report": {
                    "blocks": [
                        {"type": "paragraph", "text": "Before"},
                        {
                            "type": "image",
                            "path": str(tmp_path / "pixel.png"),
                            "alt_text": "Figure",
                            "width_inches": 2,
                        },
                    ]
                }
            },
        )
    )
    block = parsed.arguments["report"]["blocks"][1]
    assert block["type"] == "image"
    assert block["alt_text"] == "Figure"
    assert block["width_inches"] == 2.0
    assert block["path"] == (tmp_path / "pixel.png").resolve()


@pytest.mark.parametrize(
    "block",
    [
        {"type": "image", "path": "https://example.invalid/image.png"},
        {"type": "image", "path": "pixel.png", "width_inches": 0},
        {"type": "image", "path": "pixel.png", "unknown": True},
    ],
)
def test_create_image_blocks_keep_the_local_bounded_guarantees(
    tmp_path: Path,
    block: dict[str, object],
) -> None:
    with pytest.raises(DocumentSkillsError) as captured:
        parse_docx_request(
            _request(
                "docx.create",
                output=str(tmp_path / "output.docx"),
                arguments={"report": {"blocks": [block]}},
            )
        )
    assert captured.value.code == ErrorCode.REQUEST_INVALID


def test_create_rejects_remote_image_before_file_access(tmp_path: Path) -> None:
    with pytest.raises(DocumentSkillsError) as captured:
        parse_docx_request(
            _request(
                "docx.create",
                output=str(tmp_path / "output.docx"),
                arguments={
                    "report": {
                        "blocks": [
                            {"type": "heading", "text": "Heading"},
                            {"type": "paragraph", "text": "Paragraph"},
                            {
                                "type": "table",
                                "rows": [["Key", "Value"]],
                            },
                        ],
                        "image": {"path": "https://example.invalid/image.png"},
                        "header": "Header",
                        "footer": "Footer",
                        "sections": [{}, {}],
                    }
                },
            )
        )
    assert captured.value.code == ErrorCode.REQUEST_INVALID


def test_create_rejects_unimplemented_style_references(tmp_path: Path) -> None:
    image = tmp_path / "pixel.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(DocumentSkillsError) as captured:
        parse_docx_request(
            _request(
                "docx.create",
                output=str(tmp_path / "output.docx"),
                arguments={
                    "report": {
                        "blocks": [
                            {"type": "heading", "text": "Heading"},
                            {
                                "type": "paragraph",
                                "text": "Paragraph",
                                "style": "UnregisteredStyle",
                            },
                            {
                                "type": "table",
                                "rows": [["Key", "Value"]],
                            },
                        ],
                        "image": {"path": str(image)},
                        "header": "Header",
                        "footer": "Footer",
                        "sections": [{}, {}],
                    }
                },
            )
        )
    assert captured.value.code == ErrorCode.REQUEST_INVALID


def test_public_dispatch_rejects_docx_arguments_before_provider_selection(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def unexpected_registry(_project_root: Path) -> object:
        raise AssertionError("provider selection must not run")

    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        unexpected_registry,
    )
    result = execute_request(
        _request(
            "docx.read",
            input=str(tmp_path / "input.docx"),
            arguments={"unknown": True},
        ),
        project_root,
        SchemaCatalog(project_root),
    )
    assert result["status"] == "invalid_request"
    assert result["provider_chain"] == []
    assert result["errors"][0]["code"] == ErrorCode.REQUEST_INVALID


def _large_create_report(
    tmp_path: Path,
    blocks: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "blocks": [
            {"type": "heading", "text": "Heading"},
            {"type": "paragraph", "text": "Paragraph"},
            *blocks,
        ],
        "image": {"path": str(tmp_path / "image.png")},
        "header": "Header",
        "footer": "Footer",
        "sections": [{}, {}],
    }


def test_create_accepts_cell_budget_boundary_and_rejects_boundary_plus_one(
    tmp_path: Path,
) -> None:
    at_boundary = _large_create_report(
        tmp_path,
        [
            {
                "type": "table",
                "rows": [
                    ["x"] * 64
                    for _ in range(_MAX_CREATE_CELLS // 64)
                ],
            }
        ],
    )
    parsed = parse_docx_request(
        _request(
            "docx.create",
            output=str(tmp_path / "boundary.docx"),
            arguments={"report": at_boundary},
        )
    )
    assert len(parsed.arguments["report"]["blocks"][-1]["rows"]) == 128

    over_limit = _large_create_report(
        tmp_path,
        [
            {
                "type": "table",
                "rows": [
                    ["x"] * 64
                    for _ in range((_MAX_CREATE_CELLS // 64) + 1)
                ],
            }
        ],
    )
    with pytest.raises(DocumentSkillsError) as captured:
        parse_docx_request(
            _request(
                "docx.create",
                output=str(tmp_path / "over-cells.docx"),
                arguments={"report": over_limit},
            )
        )
    assert captured.value.code == ErrorCode.REQUEST_INVALID
    assert captured.value.details["budget"] == "report.total_cells"


def test_create_rejects_aggregate_nodes_and_text_before_provider_selection(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def unexpected_registry(_project_root: Path) -> object:
        raise AssertionError("provider selection must not run")

    monkeypatch.setattr(
        "document_skills_core.cli.build_default_registry",
        unexpected_registry,
    )
    node_heavy_tables = [
        {"type": "table", "rows": [["x"] for _ in range(800)]}
        for _ in range(7)
    ]
    node_heavy = execute_request(
        _request(
            "docx.create",
            output=str(tmp_path / "over-nodes.docx"),
            arguments={
                "report": _large_create_report(tmp_path, node_heavy_tables)
            },
        ),
        project_root,
        SchemaCatalog(project_root),
    )
    assert node_heavy["status"] == "invalid_request"
    assert node_heavy["provider_chain"] == []
    assert node_heavy["errors"][0]["details"]["budget"] == "report.total_nodes"
    assert not (tmp_path / "over-nodes.docx").exists()

    full_chunks, remainder = divmod(_MAX_CREATE_TEXT_BYTES + 1, 64_000)
    text_blocks = [
        {"type": "paragraph", "text": "x" * 64_000}
        for _ in range(full_chunks)
    ]
    if remainder:
        text_blocks.append({"type": "paragraph", "text": "x" * remainder})
    text_blocks.append({"type": "table", "rows": [["x"]]})
    text_heavy = execute_request(
        _request(
            "docx.create",
            output=str(tmp_path / "over-text.docx"),
            arguments={
                "report": _large_create_report(tmp_path, text_blocks)
            },
        ),
        project_root,
        SchemaCatalog(project_root),
    )
    assert text_heavy["status"] == "invalid_request"
    assert text_heavy["provider_chain"] == []
    assert text_heavy["errors"][0]["details"]["budget"] == (
        "report.total_text_bytes"
    )
    assert not (tmp_path / "over-text.docx").exists()
