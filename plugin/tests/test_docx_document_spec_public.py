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

def test_public_create_document_spec_round_trips_semantic_node_ids(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "semantic-figure.png"
    image.write_bytes(_PNG_16)
    output = tmp_path / "semantic-document.docx"
    request = _request(
        tmp_path,
        "create-document-spec.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "document_spec": {
                    "version": "1.0",
                    "metadata": {"title": "Source-neutral document"},
                    "resources": {
                        "result_plot": {
                            "type": "image",
                            "path": str(image),
                        }
                    },
                    "nodes": [
                        {
                            "id": "document_title",
                            "type": "title",
                            "text": "Source-neutral document",
                        },
                        {
                            "id": "section_intro",
                            "type": "heading",
                            "level": 1,
                            "text": "Introduction",
                        },
                        {
                            "id": "paragraph_summary",
                            "type": "paragraph",
                            "text": "The document spec is independent of Markdown.",
                        },
                        {
                            "id": "figure_result",
                            "type": "figure",
                            "resource": "result_plot",
                            "alt_text": "Result plot",
                            "width_inches": 2,
                        },
                        {
                            "id": "table_result",
                            "type": "table",
                            "rows": [["Metric", "Value"], ["Accuracy", "98%"]],
                        },
                    ],
                }
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))
    assert result["status"] == "success", result
    document = _read_document(
        project_root,
        tmp_path,
        output,
        "read-document-spec.json",
    )
    body = next(story for story in document["stories"] if story["kind"] == "body")

    semantic_paragraphs = [
        (item["node_id"], item["node_type"], item["text"], item["style"])
        for item in body["paragraphs"]
        if item.get("node_id") is not None
    ]
    assert semantic_paragraphs == [
        (
            "document_title",
            "title",
            "Source-neutral document",
            "Title",
        ),
        ("section_intro", "heading", "Introduction", "Heading1"),
        (
            "paragraph_summary",
            "paragraph",
            "The document spec is independent of Markdown.",
            "Normal",
        ),
        ("figure_result", "figure", "", None),
    ]
    assert [
        (item["node_id"], item["node_type"], item["alt_text"])
        for item in document["images"]
    ] == [("figure_result", "figure", "Result plot")]
    assert [
        (item["node_id"], item["node_type"], _table_values(item))
        for item in body["tables"]
    ] == [
        (
            "table_result",
            "table",
            [["Metric", "Value"], ["Accuracy", "98%"]],
        )
    ]
    schema_request = _request(
        tmp_path,
        "validate-document-spec.json",
        {
            "schema_version": "1.0",
            "operation": "docx.validate.schema",
            "input": str(output),
            "options": {"fidelity": "enhanced"},
            "arguments": {"max_errors": 100},
        },
    )
    schema_result = _public(
        project_root,
        "run",
        "--request",
        str(schema_request),
        check=False,
    )
    if schema_result["status"] == "success":
        assert schema_result["diagnostics"]["operation_result"]["schema"][
            "valid"
        ] is True
    else:
        assert schema_result["status"] == "unavailable"
        assert schema_result["errors"][0]["code"] == "DS_PROVIDER_UNAVAILABLE"


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "document_spec": {
                "version": "1.0",
                "nodes": [
                    {"id": "duplicate", "type": "paragraph", "text": "First"},
                    {"id": "duplicate", "type": "paragraph", "text": "Second"},
                ],
            }
        },
        {
            "document_spec": {
                "version": "1.0",
                "nodes": [
                    {
                        "id": "missing_figure",
                        "type": "figure",
                        "resource": "unknown_image",
                    }
                ],
            }
        },
        {
            "document_spec": {
                "version": "1.0",
                "nodes": [
                    {"id": "semantic_node", "type": "paragraph", "text": "Body"}
                ],
            },
            "report": {"blocks": [{"type": "paragraph", "text": "Ambiguous"}]},
        },
    ],
    ids=("duplicate-node-id", "missing-resource", "ambiguous-create-contract"),
)
def test_public_create_document_spec_fails_closed(
    project_root: Path,
    tmp_path: Path,
    arguments: dict[str, object],
) -> None:
    output = tmp_path / "must-not-exist.docx"
    request = _request(
        tmp_path,
        "invalid-document-spec.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": arguments,
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )
    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert not output.exists()


@pytest.mark.parametrize(
    ("fixture_name", "title", "heading"),
    [
        ("academic-paper", "A Reusable Profile", "Introduction"),
        ("technical-report", "System Readiness", "Executive summary"),
    ],
)
def test_public_professional_profile_is_reusable_across_document_domains(
    project_root: Path,
    tmp_path: Path,
    fixture_name: str,
    title: str,
    heading: str,
) -> None:
    output = tmp_path / f"{fixture_name}.docx"
    request = _request(
        tmp_path,
        f"create-{fixture_name}.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "document_spec": {
                    "version": "1.0",
                    "style_profile": {
                        "id": "professional-generic",
                        "version": "1.0",
                    },
                    "nodes": [
                        {"id": "document_title", "type": "title", "text": title},
                        {
                            "id": "section_primary",
                            "type": "heading",
                            "level": 1,
                            "text": heading,
                        },
                        {
                            "id": "paragraph_primary",
                            "type": "paragraph",
                            "text": "The same profile module formats this document.",
                        },
                        {
                            "id": "table_primary",
                            "type": "table",
                            "rows": [["Item", "Status"], ["Profile", "Ready"]],
                        },
                    ],
                }
            },
        },
    )

    created = _public(project_root, "run", "--request", str(request))
    assert created["status"] == "success", created
    document = _read_document(
        project_root,
        tmp_path,
        output,
        f"read-{fixture_name}.json",
    )
    body = next(story for story in document["stories"] if story["kind"] == "body")
    semantic = {
        item["node_id"]: item
        for item in body["paragraphs"]
        if item.get("node_id") is not None
    }
    assert semantic["document_title"]["style"] == "ElftiaTitle"
    assert semantic["section_primary"]["style"] == "ElftiaHeading1"
    assert semantic["paragraph_primary"]["style"] == "ElftiaBody"
    assert body["tables"][0]["style"] == "ElftiaTable"

    formatting = document["formatting"]
    assert formatting["style_profile"] == {
        "id": "professional-generic",
        "version": "1.0",
    }
    styles = {style["id"]: style for style in formatting["styles"]}
    assert styles["ElftiaTitle"]["paragraph_format"] == {
        "alignment": "center",
        "keep_with_next": True,
        "space_after_twips": 240,
    }
    assert styles["ElftiaTitle"]["run_format"] == {
        "bold": True,
        "font_ascii": "Arial",
        "font_east_asia": "Microsoft YaHei",
        "font_size_pt": 24.0,
    }
    assert styles["ElftiaBody"]["paragraph_format"] == {
        "line_rule": "auto",
        "line_twips": 276,
        "space_after_twips": 120,
    }
    assert styles["ElftiaBody"]["run_format"] == {
        "font_ascii": "Arial",
        "font_east_asia": "Microsoft YaHei",
        "font_size_pt": 11.0,
    }
    assert formatting["normalization_report"]["status"] == "clean"
    assert styles["ElftiaCaption"]["paragraph_format"] == {
        "alignment": "center",
        "keep_lines": True,
        "space_after_twips": 120,
    }

    with zipfile.ZipFile(output) as archive:
        settings = fromstring(archive.read("word/settings.xml"))
    compatibility = settings.find(
        f"./{qn('w', 'compat')}/{qn('w', 'compatSetting')}"
    )
    assert compatibility is not None
    assert compatibility.attrib == {
        qn("w", "name"): "compatibilityMode",
        qn("w", "uri"): "http://schemas.microsoft.com/office/word",
        qn("w", "val"): "15",
    }


def test_public_document_spec_maps_semantic_roles_to_hashed_template_styles(
    project_root: Path,
    tmp_path: Path,
) -> None:
    style_source = tmp_path / "style-source.docx"
    source_request = _request(
        tmp_path,
        "create-style-source.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(style_source),
            "arguments": {
                "document_spec": {
                    "version": "1.0",
                    "style_profile": {
                        "id": "professional-generic",
                        "version": "1.0",
                    },
                    "nodes": [
                        {"id": "source_title", "type": "title", "text": "Styles"},
                        {
                            "id": "source_heading",
                            "type": "heading",
                            "level": 1,
                            "text": "Source",
                        },
                    ],
                }
            },
        },
    )
    source_result = _public(
        project_root,
        "run",
        "--request",
        str(source_request),
    )
    assert source_result["status"] == "success", source_result

    output = tmp_path / "template-mapped.docx"
    request = _request(
        tmp_path,
        "create-template-mapped.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "document_spec": {
                    "version": "1.0",
                    "style_profile": {
                        "id": "template-mapped",
                        "version": "1.0",
                        "source": str(style_source),
                        "expected_source_sha256": sha256_file(style_source),
                        "role_styles": {
                            "title": "ElftiaTitle",
                            "heading.1": "ElftiaHeading1",
                            "paragraph": "ElftiaBody",
                            "table": "ElftiaTable",
                        },
                    },
                    "nodes": [
                        {"id": "mapped_title", "type": "title", "text": "Mapped"},
                        {
                            "id": "mapped_heading",
                            "type": "heading",
                            "level": 1,
                            "text": "Template styles",
                        },
                        {
                            "id": "mapped_body",
                            "type": "paragraph",
                            "text": "Semantic roles select template-owned style ids.",
                        },
                        {
                            "id": "mapped_table",
                            "type": "table",
                            "rows": [["Role", "Style"], ["Body", "Mapped"]],
                        },
                    ],
                }
            },
        },
    )

    created = _public(project_root, "run", "--request", str(request))
    assert created["status"] == "success", created
    document = _read_document(
        project_root,
        tmp_path,
        output,
        "read-template-mapped.json",
    )
    body = next(story for story in document["stories"] if story["kind"] == "body")
    semantic = {
        item["node_id"]: item
        for item in body["paragraphs"]
        if item.get("node_id") is not None
    }
    assert semantic["mapped_title"]["style"] == "ElftiaTitle"
    assert semantic["mapped_heading"]["style"] == "ElftiaHeading1"
    assert semantic["mapped_body"]["style"] == "ElftiaBody"
    assert body["tables"][0]["style"] == "ElftiaTable"
    assert {item["id"] for item in document["formatting"]["styles"]} >= {
        "ElftiaTitle",
        "ElftiaHeading1",
        "ElftiaBody",
        "ElftiaTable",
    }
