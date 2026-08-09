import base64
import json
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

import pytest

from document_skills_core.cli import execute_request
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import ArtifactRecord
import document_skills_core.formats.docx.service as service_module
import document_skills_core.formats.docx.transaction as transaction_module
from document_skills_core.formats.docx.constants import qn
from document_skills_core.formats.docx.content_types import parse_content_types
from document_skills_core.formats.docx.mapping import (
    Story,
    document_stories,
    map_paragraph,
    paragraph_style,
)
from document_skills_core.formats.docx.package import OpcPackage
from document_skills_core.formats.docx.projection import (
    project_images,
    project_sections,
    project_tables,
)
from document_skills_core.formats.docx.replace import (
    apply_replacement_plan,
    changed_story_parts,
    plan_replacements,
)
from document_skills_core.formats.docx.service import DocxService

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _run(project_root: Path, request: dict[str, object]) -> dict[str, object]:
    return execute_request(request, project_root, SchemaCatalog(project_root))


def _report(image: Path, paragraph_text: str = "Hello world") -> dict[str, object]:
    return {
        "metadata": {"title": "Core report", "creator": "Elftia"},
        "blocks": [
            {"type": "heading", "text": "Core DOCX", "level": 1},
            {"type": "paragraph", "text": paragraph_text},
            {
                "type": "table",
                "style": "TableGrid",
                "rows": [["Name", "Value"], ["Status", "Ready"]],
            },
        ],
        "image": {"path": str(image), "alt_text": "One pixel", "width_inches": 1},
        "header": "Header marker",
        "footer": "Footer marker",
        "sections": [
            {"orientation": "portrait"},
            {"orientation": "landscape"},
        ],
    }


@pytest.fixture
def created_docx(project_root: Path, tmp_path: Path) -> Path:
    image = tmp_path / "pixel.png"
    image.write_bytes(_PNG)
    output = tmp_path / "created.docx"
    result = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {"report": _report(image)},
        },
    )
    assert result["status"] == "success", result
    assert result["provider_chain"] == ["core-python"]
    return output


def test_create_read_and_inspect_roundtrip(project_root: Path, created_docx: Path) -> None:
    read = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(created_docx),
            "arguments": {},
        },
    )
    assert read["status"] == "success", read
    operation = read["diagnostics"]["operation_result"]
    assert len(operation["document"]["sections"]) == 2
    assert operation["document"]["images"][0]["alt_text"] == "One pixel"
    assert {story["kind"] for story in operation["document"]["stories"]} == {
        "body",
        "footer",
        "header",
    }
    inspection = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.inspect.structure",
            "input": str(created_docx),
            "arguments": {},
        },
    )
    assert inspection["status"] == "success", inspection
    inventory = inspection["diagnostics"]["operation_result"]
    assert inventory["mutation_authorized"] is False
    assert inventory["word_features"]["sections"] == 2


def test_create_writes_only_the_requested_blocks(
    project_root: Path,
    tmp_path: Path,
) -> None:
    """Prose-only requests must not acquire a filler table, image, or story."""

    output = tmp_path / "prose.docx"
    result = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "report": {
                    "blocks": [
                        {"type": "heading", "text": "Chapter 1", "level": 1},
                        {"type": "paragraph", "text": "Body text."},
                    ]
                }
            },
        },
    )
    assert result["status"] == "success", result
    package = OpcPackage.open(output)
    assert not [name for name in package.parts if name.startswith("word/media/")]
    assert "word/header1.xml" not in package.parts
    assert "word/footer1.xml" not in package.parts
    body = document_stories(package, include_headers_footers=False)[0]
    tables, _ = project_tables(body.root, table_limit=10, row_limit=10)
    assert tables == []
    assert project_images(package, body) == []
    assert [story.kind for story in document_stories(package)] == ["body"]
    assert len(project_sections(package)) == 1
    assert project_sections(package)[0]["references"] == []


def test_create_carries_a_deep_heading_outline(
    project_root: Path,
    tmp_path: Path,
) -> None:
    """A thesis outline (1 / 1.1 / 1.1.1 ...) keeps its real heading levels."""

    output = tmp_path / "thesis.docx"
    blocks = [
        {"type": "heading", "text": f"level {level}", "level": level}
        for level in range(1, 7)
    ]
    result = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {"report": {"blocks": blocks}},
        },
    )
    assert result["status"] == "success", result
    package = OpcPackage.open(output)
    body = document_stories(package, include_headers_footers=False)[0]
    assert [
        paragraph_style(paragraph) for paragraph in body.root.iter(qn("w", "p"))
    ][:6] == [f"Heading{level}" for level in range(1, 7)]
    styles = package.xml("word/styles.xml")
    style_ids = {
        item.attrib.get(qn("w", "styleId")) for item in styles.findall(qn("w", "style"))
    }
    assert {f"Heading{level}" for level in range(1, 7)} <= style_ids


def test_create_ships_only_the_heading_styles_it_needs(
    project_root: Path,
    tmp_path: Path,
) -> None:
    """A shallow document keeps the historical Heading1/Heading2 style pair."""

    output = tmp_path / "shallow.docx"
    result = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "report": {"blocks": [{"type": "heading", "text": "Only H1"}]}
            },
        },
    )
    assert result["status"] == "success", result
    styles = OpcPackage.open(output).xml("word/styles.xml")
    style_ids = {
        item.attrib.get(qn("w", "styleId")) for item in styles.findall(qn("w", "style"))
    }
    assert style_ids == {"Normal", "Heading1", "Heading2", "TableGrid"}


def test_create_places_image_blocks_where_the_caller_put_them(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "pixel.png"
    image.write_bytes(_PNG)
    output = tmp_path / "illustrated.docx"
    result = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "report": {
                    "blocks": [
                        {"type": "paragraph", "text": "Before"},
                        {
                            "type": "image",
                            "path": str(image),
                            "alt_text": "Figure 1",
                            "width_inches": 2,
                        },
                        {"type": "paragraph", "text": "After"},
                        {
                            "type": "image",
                            "path": str(image),
                            "alt_text": "Figure 2",
                        },
                    ],
                    "footer": "Footer only",
                }
            },
        },
    )
    assert result["status"] == "success", result
    package = OpcPackage.open(output)
    body = document_stories(package, include_headers_footers=False)[0]
    assert [image["alt_text"] for image in project_images(package, body)] == [
        "Figure 1",
        "Figure 2",
    ]
    assert sorted(
        name for name in package.parts if name.startswith("word/media/")
    ) == ["word/media/image1.png", "word/media/image2.png"]
    assert "word/header1.xml" not in package.parts
    assert {
        reference["kind"]
        for section in project_sections(package)
        for reference in section["references"]
    } == {"footer"}
    order = [
        "".join(group.text for group in map_paragraph(paragraph).groups)
        for paragraph in body.root.iter(qn("w", "p"))
    ]
    assert order.index("Before") < order.index("After")
    creation = result["diagnostics"]["operation_result"]["creation"]
    assert [
        (item["alt_text"], item["content_type"], item["extension"], item["bytes"])
        for item in creation["images"]
    ] == [
        ("Figure 1", "image/png", "png", len(_PNG)),
        ("Figure 2", "image/png", "png", len(_PNG)),
    ]
    # Same source file twice, so the payload oracle agrees.
    assert len({item["sha256"] for item in creation["images"]}) == 1
    assert creation["image"] == creation["images"][0]


def test_read_limits_bound_projected_runs_and_table_text(
    project_root: Path,
    created_docx: Path,
) -> None:
    result = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(created_docx),
            "arguments": {"max_text_chars": 4},
        },
    )
    assert result["status"] == "success"
    operation = result["diagnostics"]["operation_result"]
    projected_run_text = sum(
        len(run["text"])
        for story in operation["document"]["stories"]
        for paragraph in story["paragraphs"]
        for run in paragraph["runs"]
    )
    projected_table_text = sum(
        len(paragraph["text"])
        for story in operation["document"]["stories"]
        for table in story["tables"]
        for row in table["rows"]
        for cell in row["cells"]
        for paragraph in cell["paragraphs"]
    )
    assert projected_run_text <= 4
    assert projected_table_text <= 4
    assert result["warnings"][0]["code"] == "DS_READ_TRUNCATED"


def test_replace_preserves_source_and_reports_story_counts(
    project_root: Path,
    created_docx: Path,
    tmp_path: Path,
) -> None:
    before = created_docx.read_bytes()
    output = tmp_path / "replaced.docx"
    result = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.edit.replace-text",
            "input": str(created_docx),
            "output": str(output),
            "arguments": {
                "replacements": [
                    {"search": "marker", "replace": "value", "expected_matches": 2}
                ]
            },
        },
    )
    assert result["status"] == "success", result
    assert created_docx.read_bytes() == before
    counts = result["diagnostics"]["operation_result"]["replacement"]["counts_by_story"]
    assert counts["header:word/header1.xml"] == [1]
    assert counts["footer:word/footer1.xml"] == [1]


def test_template_uses_private_core_node_provider(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "pixel.png"
    image.write_bytes(_PNG)
    template = tmp_path / "template.docx"
    create = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(template),
            "arguments": {"report": _report(image, "Customer: {customer.name}")},
        },
    )
    assert create["status"] == "success", create
    output = tmp_path / "rendered.docx"
    template_request = {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(template),
            "output": str(output),
            "arguments": {
                "variables": {
                    "customer": {"name": "Alice & Bob"},
                    "unused": "warning",
                }
            },
        }
    direct_output = tmp_path / "rendered-direct.docx"
    direct_request = {**template_request, "output": str(direct_output)}
    direct = DocxService(project_root).execute("docx.template.apply", direct_request)
    assert direct["status"] == "success"
    rendered = _run(project_root, template_request)
    assert rendered["status"] == "success", json.dumps(rendered, indent=2)
    assert rendered["provider_chain"] == ["core-node"]
    template_result = rendered["diagnostics"]["operation_result"]["template"]
    assert template_result["used"] == ["customer.name"]
    assert template_result["unused"] == ["unused"]
    assert template_result["occurrence_counts"] == {"customer.name": 1}
    assert rendered["warnings"][0]["code"] == "DS_TEMPLATE_UNUSED_VARIABLES"
    assert direct_output.read_bytes() == output.read_bytes()
    rendered_package = OpcPackage.open(output)
    rendered_text = "\n".join(
        group.text
        for story in document_stories(rendered_package)
        for paragraph in story.root.iter(qn("w", "p"))
        for group in map_paragraph(paragraph).groups
    )
    assert "Customer: Alice & Bob" in rendered_text


def test_template_split_run_value_keeps_first_affected_run_formatting(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "pixel.png"
    image.write_bytes(_PNG)
    seed = tmp_path / "seed.docx"
    created = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(seed),
            "arguments": {
                "report": _report(image, "Customer: {customer.name}")
            },
        },
    )
    assert created["status"] == "success", created
    package = OpcPackage.open(seed)
    body = document_stories(package, include_headers_footers=False)[0]
    target = next(
        paragraph
        for paragraph in body.root.iter(qn("w", "p"))
        if any(
            "{customer.name}" in group.text
            for group in map_paragraph(paragraph).groups
        )
    )
    original_text = next(
        node
        for node in target.iter(qn("w", "t"))
        if node.text == "Customer: {customer.name}"
    )
    original_text.text = "Customer: "
    first_token_run = SubElement(target, qn("w", "r"))
    properties = SubElement(first_token_run, qn("w", "rPr"))
    SubElement(properties, qn("w", "b"))
    SubElement(first_token_run, qn("w", "t")).text = "{customer."
    second_token_run = SubElement(target, qn("w", "r"))
    SubElement(second_token_run, qn("w", "t")).text = "name}"
    template = tmp_path / "split-template.docx"
    package.write_copy(
        template,
        changed_parts={
            body.part: tostring(
                body.root,
                encoding="utf-8",
                xml_declaration=True,
            )
        },
    )

    output = tmp_path / "split-rendered.docx"
    result = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(template),
            "output": str(output),
            "arguments": {"variables": {"customer": {"name": "Alice"}}},
        },
    )
    assert result["status"] == "success", result
    rendered = OpcPackage.open(output)
    rendered_group = next(
        group
        for story in document_stories(rendered)
        for paragraph in story.root.iter(qn("w", "p"))
        for group in map_paragraph(paragraph).groups
        if group.text == "Customer: Alice"
    )
    value_start = rendered_group.text.index("Alice")
    anchor = next(
        reference
        for reference in rendered_group.refs
        if reference.start <= value_start < reference.end
    )
    assert anchor.run.find(f"./{qn('w', 'rPr')}/{qn('w', 'b')}") is not None


def test_template_rejects_structurally_valid_backend_output_with_wrong_semantics(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image = tmp_path / "pixel.png"
    image.write_bytes(_PNG)
    template = tmp_path / "template.docx"
    created = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(template),
            "arguments": {
                "report": _report(image, "Customer: {customer.name}")
            },
        },
    )
    assert created["status"] == "success", created

    def unchanged_backend(
        _project_root: Path,
        source: Path,
        destination: Path,
        *,
        variables: dict[str, str],
        plan: object,
    ) -> tuple[object, dict[str, object]]:
        del variables
        source_package = OpcPackage.open(source)
        stories = document_stories(source_package)
        wrong_plan = plan_replacements(
            stories,
            [
                {
                    "search": "{customer.name}",
                    "replace": "Mallory",
                    "expected_matches": 1,
                }
            ],
            case_sensitive=True,
        )
        apply_replacement_plan(wrong_plan)
        manifest = source_package.write_copy(
            destination,
            changed_parts=changed_story_parts(stories, wrong_plan),
        )
        return manifest, {"backend": "injected", "version": "test"}

    monkeypatch.setattr(
        service_module,
        "apply_template_with_node",
        unchanged_backend,
    )
    output = tmp_path / "must-not-exist.docx"
    result = DocxService(project_root).execute(
        "docx.template.apply",
        {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(template),
            "output": str(output),
            "arguments": {"variables": {"customer": {"name": "Alice"}}},
        },
    )
    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == ErrorCode.VALIDATION_FAILED
    assert not output.exists()


def test_template_rejects_backend_corrupting_unrelated_same_part_content(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image = tmp_path / "pixel.png"
    image.write_bytes(_PNG)
    template = tmp_path / "template.docx"
    created = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(template),
            "arguments": {
                "report": _report(image, "Customer: {customer.name}")
            },
        },
    )
    assert created["status"] == "success", created

    def corrupting_backend(
        _project_root: Path,
        source: Path,
        destination: Path,
        *,
        variables: dict[str, str],
        plan: object,
    ) -> tuple[object, dict[str, object]]:
        del variables, plan
        source_package = OpcPackage.open(source)
        stories = document_stories(source_package)
        wrong_plan = plan_replacements(
            stories,
            [
                {
                    "search": "{customer.name}",
                    "replace": "Alice",
                    "expected_matches": 1,
                },
                {
                    "search": "Core DOCX",
                    "replace": "CORRUPTED-BY-BACKEND",
                    "expected_matches": 1,
                },
            ],
            case_sensitive=True,
        )
        apply_replacement_plan(wrong_plan)
        manifest = source_package.write_copy(
            destination,
            changed_parts=changed_story_parts(stories, wrong_plan),
        )
        return manifest, {"backend": "injected", "version": "test"}

    monkeypatch.setattr(
        service_module,
        "apply_template_with_node",
        corrupting_backend,
    )
    output = tmp_path / "existing-output.docx"
    output.write_bytes(b"must remain unchanged")
    result = DocxService(project_root).execute(
        "docx.template.apply",
        {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(template),
            "output": str(output),
            "arguments": {"variables": {"customer": {"name": "Alice"}}},
        },
    )
    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == ErrorCode.VALIDATION_FAILED
    assert output.read_bytes() == b"must remain unchanged"


def test_create_failure_paths_do_not_clobber_destination(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image = tmp_path / "invalid.jpg"
    image.write_bytes(b"\xff\xd8\xfftruncated")
    output = tmp_path / "existing.docx"
    output.write_bytes(b"existing destination")
    invalid = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {"report": _report(image)},
        },
    )
    assert invalid["status"] == "invalid_request"
    assert output.read_bytes() == b"existing destination"

    image.write_bytes(_PNG)

    def failed_validation(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "injected validation failure",
        )

    monkeypatch.setattr(service_module, "validate_created", failed_validation)
    failed = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {"report": _report(image)},
        },
    )
    assert failed["errors"][0]["code"] == ErrorCode.VALIDATION_FAILED
    assert output.read_bytes() == b"existing destination"


def test_destination_race_and_final_hash_mismatch_fail_closed(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image = tmp_path / "pixel.png"
    image.write_bytes(_PNG)
    output = tmp_path / "race.docx"
    output.write_bytes(b"initial destination")
    real_promote = transaction_module.atomic_promote

    def racing_promote(*args: object, **kwargs: object) -> ArtifactRecord:
        output.write_bytes(b"concurrent destination")
        return real_promote(*args, **kwargs)

    monkeypatch.setattr(transaction_module, "atomic_promote", racing_promote)
    raced = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {"report": _report(image)},
        },
    )
    assert raced["errors"][0]["code"] == ErrorCode.VALIDATION_FAILED
    assert raced["errors"][0]["details"]["destination_race"] is True
    assert output.read_bytes() == b"concurrent destination"

    monkeypatch.setattr(
        transaction_module,
        "atomic_promote",
        lambda *_args, **_kwargs: ArtifactRecord(
            "output",
            str(output),
            "0" * 64,
            0,
        ),
    )
    mismatch = _run(
        project_root,
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {"report": _report(image)},
        },
    )
    assert mismatch["errors"][0]["code"] == ErrorCode.VALIDATION_FAILED
    assert output.read_bytes() == b"concurrent destination"


def test_hyperlinks_form_text_mapping_boundaries() -> None:
    paragraph = Element(qn("w", "p"))
    first = SubElement(paragraph, qn("w", "r"))
    SubElement(first, qn("w", "t")).text = "before"
    hyperlink = SubElement(paragraph, qn("w", "hyperlink"), {qn("r", "id"): "rId1"})
    linked_run = SubElement(hyperlink, qn("w", "r"))
    SubElement(linked_run, qn("w", "t")).text = "inside"
    final = SubElement(paragraph, qn("w", "r"))
    SubElement(final, qn("w", "t")).text = "after"
    assert [group.text for group in map_paragraph(paragraph).groups] == [
        "before",
        "inside",
        "after",
    ]


def test_casefold_replacement_is_run_aware_and_rejects_ambiguous_folds() -> None:
    paragraph = Element(qn("w", "p"))
    first = SubElement(paragraph, qn("w", "r"))
    SubElement(first, qn("w", "t")).text = "HEL"
    second = SubElement(paragraph, qn("w", "r"))
    SubElement(second, qn("w", "t")).text = "LO suffix"
    story = Story("body", "word/document.xml", paragraph)
    plan = plan_replacements(
        [story],
        [{"search": "hello", "replace": "value", "expected_matches": 1}],
        case_sensitive=False,
    )
    apply_replacement_plan(plan)
    assert first.find(qn("w", "t")).text == "value"
    assert second.find(qn("w", "t")).text == " suffix"

    ambiguous = Element(qn("w", "p"))
    run = SubElement(ambiguous, qn("w", "r"))
    SubElement(run, qn("w", "t")).text = "Straße"
    with pytest.raises(DocumentSkillsError) as captured:
        plan_replacements(
            [Story("body", "word/document.xml", ambiguous)],
            [{"search": "STRASSE", "replace": "value", "expected_matches": 1}],
            case_sensitive=False,
        )
    assert captured.value.code == ErrorCode.REQUEST_INVALID


def test_table_projection_retains_spans_and_nested_paragraphs() -> None:
    root = Element(qn("w", "document"))
    table = SubElement(root, qn("w", "tbl"))
    row = SubElement(table, qn("w", "tr"))
    cell = SubElement(row, qn("w", "tc"))
    properties = SubElement(cell, qn("w", "tcPr"))
    SubElement(properties, qn("w", "gridSpan"), {qn("w", "val"): "2"})
    paragraph = SubElement(cell, qn("w", "p"))
    run = SubElement(paragraph, qn("w", "r"))
    SubElement(run, qn("w", "t")).text = "Outer"
    nested_table = SubElement(cell, qn("w", "tbl"))
    nested_row = SubElement(nested_table, qn("w", "tr"))
    nested_cell = SubElement(nested_row, qn("w", "tc"))
    nested_paragraph = SubElement(nested_cell, qn("w", "p"))
    nested_run = SubElement(nested_paragraph, qn("w", "r"))
    SubElement(nested_run, qn("w", "t")).text = "Nested"
    tables, truncated = project_tables(
        root,
        table_limit=10,
        row_limit=10,
    )
    assert truncated is False
    assert tables[0]["rows"][0]["cells"][0]["grid_span"] == "2"
    assert [
        item["text"]
        for item in tables[0]["rows"][0]["cells"][0]["paragraphs"]
    ] == ["Outer", "Nested"]


def test_comment_only_requested_text_requires_enhancement() -> None:
    root = Element(qn("w", "document"))
    story = Story("body", "word/document.xml", root)
    with pytest.raises(DocumentSkillsError) as captured:
        plan_replacements(
            [story],
            [{"search": "comment-only", "replace": "value", "expected_matches": None}],
            case_sensitive=True,
            protected_comment_text="comment-only",
        )
    assert captured.value.code == ErrorCode.ENHANCEMENT_REQUIRED


def test_content_type_overrides_reject_portable_aliases() -> None:
    payload = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml" ContentType="application/xml"/>
  <Override PartName="/WORD/document.xml" ContentType="application/xml"/>
</Types>"""
    with pytest.raises(DocumentSkillsError) as captured:
        parse_content_types(payload)
    assert captured.value.code == ErrorCode.ARCHIVE_UNSAFE
