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

def test_public_document_spec_emits_bounded_stable_cross_references(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "cross-references.docx"
    request = _request(
        tmp_path,
        "create-cross-references.json",
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
                        {"id": "document_title", "type": "title", "text": "Links"},
                        {
                            "id": "section_methods",
                            "type": "heading",
                            "level": 1,
                            "text": "Methods",
                        },
                        {
                            "id": "reference_methods",
                            "type": "reference",
                            "target": "section_methods",
                            "text": "Methods",
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
        "read-cross-references.json",
    )
    assert document["references"]["status"] == "update_required"
    assert len(document["references"]["targets"]) == 1
    target = document["references"]["targets"][0]
    assert target["node_id"] == "section_methods"
    assert target["node_type"] == "heading"
    assert target["bookmark"].startswith("_Elftia_")
    assert document["references"]["bindings"] == [
        {
            "node_id": "reference_methods",
            "target_bookmark": target["bookmark"],
            "display_text": "Methods",
            "update_required": True,
        }
    ]
    assert document["fields"] == [
        {
            "index": 0,
            "story": "body",
            "part": "word/document.xml",
            "paragraph_index": 2,
            "field_type": "simple",
            "instruction": f"REF {target['bookmark']} \\h",
            "kind": "REF",
            "safe": True,
            "update_pending": True,
        }
    ]


def test_public_document_spec_rejects_missing_reference_target(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "missing-reference.docx"
    request = _request(
        tmp_path,
        "create-missing-reference.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "document_spec": {
                    "version": "1.0",
                    "nodes": [
                        {"id": "document_title", "type": "title", "text": "Links"},
                        {
                            "id": "missing_reference",
                            "type": "reference",
                            "target": "absent_heading",
                            "text": "Missing",
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


@pytest.mark.parametrize(
    ("citation_style", "citation_text", "entry_prefix"),
    [
        ("author-year", "(Lovelace, 1843)", "Lovelace, Ada. (1843)."),
        ("numeric", "[1]", "[1] Ada Lovelace. 1843."),
    ],
)
def test_public_academic_profile_emits_editable_equation_and_citations(
    project_root: Path,
    tmp_path: Path,
    citation_style: str,
    citation_text: str,
    entry_prefix: str,
) -> None:
    output = tmp_path / f"academic-{citation_style}.docx"
    request = _request(
        tmp_path,
        f"create-academic-{citation_style}.json",
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
                        "citation_style": citation_style,
                    },
                    "style_profile": {
                        "id": "professional-generic",
                        "version": "1.0",
                    },
                    "nodes": [
                        {"id": "paper_title", "type": "title", "text": "Evidence"},
                        {
                            "id": "paper_authors",
                            "type": "authors",
                            "items": ["Ada Lovelace"],
                        },
                        {
                            "id": "paper_abstract",
                            "type": "abstract",
                            "text": "A closed semantic subset.",
                        },
                        {
                            "id": "paper_keywords",
                            "type": "keywords",
                            "items": ["equations", "citations"],
                        },
                        {
                            "id": "section_results",
                            "type": "heading",
                            "level": 1,
                            "text": "Results",
                        },
                        {
                            "id": "equation_energy",
                            "type": "equation",
                            "linear": "E = mc²",
                        },
                        {
                            "id": "equation_energy_caption",
                            "type": "equation_caption",
                            "target": "equation_energy",
                            "text": "Mass-energy equivalence",
                        },
                        {
                            "id": "citation_notes",
                            "type": "citation",
                            "keys": ["lovelace1843"],
                        },
                        {"id": "references", "type": "bibliography"},
                        {
                            "id": "reference_lovelace",
                            "type": "bibliography_entry",
                            "key": "lovelace1843",
                            "authors": ["Ada Lovelace"],
                            "year": 1843,
                            "title": "Notes",
                            "container": "Scientific Memoirs",
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
        f"read-academic-{citation_style}.json",
    )
    assert document["equations"] == [
        {
            "node_id": "equation_energy",
            "node_type": "equation",
            "linear": "E = mc²",
            "editable_omml": True,
        }
    ]
    body = next(story for story in document["stories"] if story["kind"] == "body")
    semantic = {
        item["node_id"]: item
        for item in body["paragraphs"]
        if item.get("node_id") is not None
    }
    assert semantic["citation_notes"]["text"] == citation_text
    assert semantic["references"]["text"] == "References"
    assert semantic["reference_lovelace"]["text"].startswith(entry_prefix)
    assert semantic["equation_energy_caption"]["text"] == (
        "Equation (1). Mass-energy equivalence"
    )


def test_public_document_spec_rejects_unknown_citation_and_latex_commands(
    project_root: Path,
    tmp_path: Path,
) -> None:
    for name, extra_nodes in (
        (
            "unknown-citation",
            [
                {"id": "citation_missing", "type": "citation", "keys": ["missing"]},
                {"id": "references", "type": "bibliography"},
            ],
        ),
        (
            "latex-command",
            [
                {
                    "id": "equation_unsafe",
                    "type": "equation",
                    "linear": "\\frac{a}{b}",
                }
            ],
        ),
    ):
        output = tmp_path / f"{name}.docx"
        request = _request(
            tmp_path,
            f"create-{name}.json",
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
                        "nodes": [
                            {"id": "paper_title", "type": "title", "text": "Invalid"},
                            {
                                "id": "paper_authors",
                                "type": "authors",
                                "items": ["Ada Lovelace"],
                            },
                            {
                                "id": "paper_abstract",
                                "type": "abstract",
                                "text": "Invalid semantic data.",
                            },
                            {
                                "id": "paper_keywords",
                                "type": "keywords",
                                "items": ["invalid"],
                            },
                            {
                                "id": "section_body",
                                "type": "heading",
                                "level": 1,
                                "text": "Body",
                            },
                            *extra_nodes,
                        ],
                    }
                },
            },
        )

        result = _public(project_root, "run", "--request", str(request), check=False)
        assert result["status"] == "invalid_request"
        assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
        assert not output.exists()
