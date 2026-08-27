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

@pytest.mark.parametrize(
    ("locale", "figure_label", "table_label"),
    [
        ("en-US", "Figure 1. Architecture", "Table 1. Results"),
        ("zh-CN", "图 1　系统架构", "表 1　实验结果"),
    ],
)
def test_public_academic_domain_profile_composes_generic_semantic_nodes(
    project_root: Path,
    tmp_path: Path,
    locale: str,
    figure_label: str,
    table_label: str,
) -> None:
    image = tmp_path / f"academic-{locale}.png"
    image.write_bytes(_PNG_16)
    output = tmp_path / f"academic-{locale}.docx"
    request = _request(
        tmp_path,
        f"create-academic-{locale}.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "document_spec": {
                    "version": "1.0",
                    "domain_profile": {
                        "id": "academic-paper",
                        "version": "1.0",
                        "locale": locale,
                    },
                    "style_profile": {
                        "id": "professional-generic",
                        "version": "1.0",
                    },
                    "header": "Reusable academic header",
                    "footer": "Reusable academic footer",
                    "sections": [{"orientation": "portrait"}],
                    "resources": {
                        "architecture": {"type": "image", "path": str(image)}
                    },
                    "nodes": [
                        {"id": "paper_title", "type": "title", "text": "Profiles"},
                        {
                            "id": "paper_subtitle",
                            "type": "subtitle",
                            "text": "A source-neutral demonstration",
                        },
                        {
                            "id": "paper_authors",
                            "type": "authors",
                            "items": ["Ada Lovelace", "Alan Turing"],
                        },
                        {
                            "id": "paper_affiliations",
                            "type": "affiliations",
                            "items": ["Elftia Research"],
                        },
                        {
                            "id": "paper_abstract",
                            "type": "abstract",
                            "text": "The domain profile validates structure without changing the emitter.",
                        },
                        {
                            "id": "paper_keywords",
                            "type": "keywords",
                            "items": ["DOCX", "agents", "profiles"],
                        },
                        {
                            "id": "introduction",
                            "type": "heading",
                            "level": 1,
                            "text": "Introduction",
                        },
                        {
                            "id": "body_primary",
                            "type": "paragraph",
                            "text": "Academic rules remain outside the general OOXML emitter.",
                        },
                        {
                            "id": "figure_architecture",
                            "type": "figure",
                            "resource": "architecture",
                            "alt_text": "Architecture diagram",
                        },
                        {
                            "id": "figure_architecture_caption",
                            "type": "figure_caption",
                            "target": "figure_architecture",
                            "text": "Architecture" if locale == "en-US" else "系统架构",
                        },
                        {
                            "id": "table_results",
                            "type": "table",
                            "rows": [["Metric", "Value"], ["Pass", "Yes"]],
                        },
                        {
                            "id": "table_results_caption",
                            "type": "table_caption",
                            "target": "table_results",
                            "text": "Results" if locale == "en-US" else "实验结果",
                        },
                    ],
                }
            },
        },
    )

    created = _public(project_root, "run", "--request", str(request))
    assert created["status"] == "success", created
    document = _read_document(project_root, tmp_path, output, f"read-{locale}.json")
    assert document["domain_profile"] == {
        "id": "academic-paper",
        "version": "1.0",
        "locale": locale,
    }
    body = next(story for story in document["stories"] if story["kind"] == "body")
    semantic = {
        item["node_id"]: item
        for item in body["paragraphs"]
        if item.get("node_id") is not None
    }
    assert semantic["paper_subtitle"]["style"] == "ElftiaSubtitle"
    assert semantic["paper_authors"]["style"] == "ElftiaAuthors"
    assert semantic["paper_abstract"]["style"] == "ElftiaAbstract"
    assert semantic["paper_keywords"]["style"] == "ElftiaKeywords"
    assert semantic["figure_architecture_caption"]["text"] == figure_label
    assert semantic["figure_architecture_caption"]["style"] == "ElftiaCaption"
    assert semantic["table_results_caption"]["text"] == table_label
    assert semantic["table_results_caption"]["style"] == "ElftiaCaption"


def test_public_academic_domain_profile_rejects_incomplete_structure(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "invalid-academic.docx"
    request = _request(
        tmp_path,
        "create-invalid-academic.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "document_spec": {
                    "version": "1.0",
                    "domain_profile": {
                        "id": "academic-paper",
                        "version": "1.0",
                        "locale": "en-US",
                    },
                    "style_profile": {
                        "id": "professional-generic",
                        "version": "1.0",
                    },
                    "nodes": [
                        {"id": "paper_title", "type": "title", "text": "Invalid"},
                        {
                            "id": "orphan_caption",
                            "type": "figure_caption",
                            "target": "missing_figure",
                            "text": "Missing target",
                        },
                    ],
                }
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)
    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert not output.exists()


def test_public_technical_report_domain_does_not_require_academic_front_matter(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "technical-domain.docx"
    request = _request(
        tmp_path,
        "create-technical-domain.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "document_spec": {
                    "version": "1.0",
                    "domain_profile": {
                        "id": "technical-report",
                        "version": "1.0",
                        "locale": "en-US",
                    },
                    "style_profile": {
                        "id": "professional-generic",
                        "version": "1.0",
                    },
                    "nodes": [
                        {
                            "id": "report_title",
                            "type": "title",
                            "text": "System Readiness",
                        },
                        {
                            "id": "executive_summary",
                            "type": "heading",
                            "level": 1,
                            "text": "Executive summary",
                        },
                        {
                            "id": "report_body",
                            "type": "paragraph",
                            "text": "The same generic emitter serves a non-academic domain.",
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
        "read-technical-domain.json",
    )
    assert document["domain_profile"] == {
        "id": "technical-report",
        "version": "1.0",
        "locale": "en-US",
    }
