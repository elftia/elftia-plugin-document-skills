import json
from pathlib import Path
import shutil
import subprocess
from xml.etree.ElementTree import Element, fromstring, SubElement, tostring
import zipfile

import pytest

from document_skills_core.formats.docx.constants import CONTENT_TYPES_NS, qn


def _public(
    project_root: Path,
    *args: str,
    check: bool = True,
) -> dict[str, object]:
    completed = subprocess.run(
        [
            shutil.which("uv"),
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills" / "document-docx" / "scripts" / "run.py"),
            *args,
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=check,
        timeout=60,
    )
    return json.loads(completed.stdout)


def _request(directory: Path, name: str, payload: dict[str, object]) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _rewrite_part(source: Path, destination: Path, part: str, payload: bytes) -> None:
    _rewrite_parts(source, destination, {part: payload})


def _rewrite_parts(source: Path, destination: Path, changes: dict[str, bytes]) -> None:
    with zipfile.ZipFile(source) as source_archive:
        with zipfile.ZipFile(destination, "w") as output_archive:
            existing = set(source_archive.namelist())
            for item in source_archive.infolist():
                output_archive.writestr(
                    item,
                    changes.get(item.filename, source_archive.read(item)),
                )
            for name in sorted(set(changes) - existing):
                output_archive.writestr(name, changes[name])


@pytest.fixture
def complex_base(project_root: Path, tmp_path: Path) -> Path:
    output = tmp_path / "complex-base.docx"
    request = _request(
        tmp_path,
        "complex-create.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "report": {
                    "blocks": [
                        {"type": "heading", "text": "Summary", "level": 1},
                        {"type": "paragraph", "text": "Field anchor"},
                    ]
                }
            },
        },
    )
    result = _public(project_root, "run", "--request", str(request))
    assert result["status"] == "success", result
    return output


def _read(project_root: Path, tmp_path: Path, source: Path, name: str):
    request = _request(
        tmp_path,
        name,
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(source),
            "arguments": {},
        },
    )
    return _public(project_root, "run", "--request", str(request))[
        "diagnostics"
    ]["operation_result"]["document"]


def test_public_template_applies_declarative_repeat_and_condition_regions(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-rich.docx"
    output = tmp_path / "regional-template.docx"
    request = _request(
        tmp_path,
        "regional-template.json",
        {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "variables": {"normal": "GLOBAL"},
                "regions": [
                    {
                        "type": "paragraph_repeat",
                        "target": {
                            "story": "body",
                            "range": "paragraph",
                            "paragraph_index": 1,
                            "expected_text": (
                                "Template {customer.name} and {region}; Replace TARGET."
                            ),
                        },
                        "items": [
                            {"customer.name": "Ada", "region": "APAC"},
                            {"customer.name": "Grace", "region": "EMEA"},
                        ],
                    },
                    {
                        "type": "paragraph_condition",
                        "target": {
                            "story": "body",
                            "range": "paragraph",
                            "paragraph_index": 9,
                            "expected_text": "Overlap AAAA",
                        },
                        "include": False,
                    },
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    operation_result = result["diagnostics"]["operation_result"]
    assert operation_result["template_regions"] == {
        "requested": 2,
        "emitted_paragraphs": 2,
        "removed_paragraphs": 2,
        "regions": [
            {"type": "paragraph_repeat", "paragraph_index": 1, "emitted": 2},
            {"type": "paragraph_condition", "paragraph_index": 9, "emitted": 0},
        ],
    }
    assert operation_result["template"]["used"] == ["normal"]
    document = _read(project_root, tmp_path, output, "regional-template-read.json")
    texts = [
        paragraph["text"]
        for story in document["stories"]
        if story["kind"] == "body"
        for paragraph in story["paragraphs"]
    ]
    assert texts[1:3] == [
        "Template Ada and APAC; Replace TARGET.",
        "Template Grace and EMEA; Replace TARGET.",
    ]
    assert "Normal placeholder GLOBAL" in texts
    assert "Overlap AAAA" not in texts


def test_public_template_region_stale_selector_preserves_destination(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-rich.docx"
    source_bytes = source.read_bytes()
    output = tmp_path / "existing.docx"
    original_destination = b"existing destination"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "regional-template-stale.json",
        {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "variables": {},
                "regions": [
                    {
                        "type": "paragraph_repeat",
                        "target": {
                            "story": "body",
                            "range": "paragraph",
                            "paragraph_index": 1,
                            "expected_text": "stale paragraph text",
                        },
                        "items": [],
                    }
                ],
            },
        },
    )
    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert output.read_bytes() == original_destination
    assert source.read_bytes() == source_bytes


def test_public_fields_and_toc_insert_read_and_refresh(
    project_root: Path,
    complex_base: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "fields.docx"
    target = {
        "story": "body",
        "paragraph_index": 1,
        "expected_text": "Field anchor",
    }
    request = _request(
        tmp_path,
        "fields-insert.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(complex_base),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "field_insert",
                        "target": target,
                        "placement": "append",
                        "field": {
                            "kind": "PAGE",
                            "display_text": "1",
                        },
                    },
                    {
                        "type": "toc_insert",
                        "target": target,
                        "position": "after",
                        "heading_levels": {"start": 1, "end": 3},
                    },
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    assert result["warnings"][0]["code"] == "DS_FIELD_UPDATE_PENDING"
    document = _read(project_root, tmp_path, output, "fields-read.json")
    assert [field["kind"] for field in document["fields"]] == ["PAGE", "TOC"]
    assert document["fields"][0]["instruction"] == "PAGE"
    assert document["fields"][1]["instruction"] == 'TOC \\o "1-3" \\h \\z \\u'
    assert document["fields"][1]["update_pending"] is True

    refreshed = tmp_path / "fields-refreshed.docx"
    refresh_request = _request(
        tmp_path,
        "field-refresh.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(output),
            "output": str(refreshed),
            "arguments": {
                "edits": [
                    {
                        "type": "field_refresh",
                        "selector": {
                            "story": "body",
                            "field_index": 0,
                            "expected_instruction": "PAGE",
                        },
                    }
                ]
            },
        },
    )
    refreshed_result = _public(
        project_root,
        "run",
        "--request",
        str(refresh_request),
    )
    assert refreshed_result["status"] == "success", refreshed_result
    refreshed_document = _read(
        project_root,
        tmp_path,
        refreshed,
        "fields-refreshed-read.json",
    )
    assert refreshed_document["fields"][0]["update_pending"] is True


def test_public_field_contract_rejects_dde_without_clobbering(
    project_root: Path,
    complex_base: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing-field.docx"
    original = b"destination must survive"
    output.write_bytes(original)
    request = _request(
        tmp_path,
        "field-dde.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(complex_base),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "field_insert",
                        "target": {
                            "story": "body",
                            "paragraph_index": 1,
                            "expected_text": "Field anchor",
                        },
                        "placement": "append",
                        "field": {"kind": "DDE", "display_text": "unsafe"},
                    }
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "invalid_request", result
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert output.read_bytes() == original


def test_public_footnotes_and_endnotes_insert_read_and_delete(
    project_root: Path,
    complex_base: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "notes.docx"
    target = {
        "story": "body",
        "paragraph_index": 1,
        "expected_text": "Field anchor",
    }
    request = _request(
        tmp_path,
        "notes-insert.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(complex_base),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "note_insert",
                        "target": target,
                        "kind": "footnote",
                        "placement": "append",
                        "text": "Footnote text",
                    },
                    {
                        "type": "note_insert",
                        "target": target,
                        "kind": "endnote",
                        "placement": "append",
                        "text": "Endnote text",
                    },
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    document = _read(project_root, tmp_path, output, "notes-read.json")
    assert document["notes"] == [
        {
            "kind": "footnote",
            "id": "1",
            "text": "Footnote text",
            "reference_count": 1,
        },
        {
            "kind": "endnote",
            "id": "1",
            "text": "Endnote text",
            "reference_count": 1,
        },
    ]
    deleted = tmp_path / "notes-deleted.docx"
    delete_request = _request(
        tmp_path,
        "note-delete.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(output),
            "output": str(deleted),
            "arguments": {
                "edits": [
                    {
                        "type": "note_delete",
                        "selector": {
                            "kind": "footnote",
                            "id": "1",
                            "expected_text": "Footnote text",
                        },
                    }
                ]
            },
        },
    )
    deleted_result = _public(
        project_root,
        "run",
        "--request",
        str(delete_request),
    )
    assert deleted_result["status"] == "success", deleted_result
    deleted_document = _read(
        project_root,
        tmp_path,
        deleted,
        "notes-deleted-read.json",
    )
    assert deleted_document["notes"] == [
        {
            "kind": "endnote",
            "id": "1",
            "text": "Endnote text",
            "reference_count": 1,
        }
    ]


def test_public_content_control_inventory_and_text_update(
    project_root: Path,
    complex_base: Path,
    tmp_path: Path,
) -> None:
    with zipfile.ZipFile(complex_base) as archive:
        document = fromstring(archive.read("word/document.xml"))
    body = document.find(qn("w", "body"))
    control = Element(qn("w", "sdt"))
    properties = SubElement(control, qn("w", "sdtPr"))
    SubElement(properties, qn("w", "id"), {qn("w", "val"): "42"})
    SubElement(properties, qn("w", "tag"), {qn("w", "val"): "customer-name"})
    SubElement(properties, qn("w", "alias"), {qn("w", "val"): "Customer name"})
    content = SubElement(control, qn("w", "sdtContent"))
    paragraph = SubElement(content, qn("w", "p"))
    run = SubElement(paragraph, qn("w", "r"))
    text = SubElement(run, qn("w", "t"))
    text.text = "Controlled text"
    body.insert(len(body) - 1, control)
    source = tmp_path / "content-control.docx"
    _rewrite_part(
        complex_base,
        source,
        "word/document.xml",
        tostring(document, encoding="utf-8", xml_declaration=True),
    )
    projected = _read(project_root, tmp_path, source, "content-control-read.json")
    assert len(projected["content_controls"]) == 1
    original = projected["content_controls"][0]
    assert original["id"] == "42"
    assert original["tag"] == "customer-name"
    assert original["text"] == "Controlled text"
    output = tmp_path / "content-control-updated.docx"
    request = _request(
        tmp_path,
        "content-control-update.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "content_control_text_update",
                        "selector": {
                            "story": "body",
                            "control_index": 0,
                            "expected_sha256": original["selector_sha256"],
                            "expected_text": "Controlled text",
                        },
                        "text": "Updated customer",
                    }
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    updated = _read(project_root, tmp_path, output, "content-control-updated-read.json")
    assert updated["content_controls"][0]["text"] == "Updated customer"
    assert updated["content_controls"][0]["tag"] == "customer-name"


def test_public_custom_style_multilevel_numbering_and_formatting_report(
    project_root: Path,
    complex_base: Path,
    tmp_path: Path,
) -> None:
    with zipfile.ZipFile(complex_base) as archive:
        styles = fromstring(archive.read("word/styles.xml"))
        numbering = fromstring(archive.read("word/numbering.xml"))
        document = fromstring(archive.read("word/document.xml"))
        content_types = fromstring(archive.read("[Content_Types].xml"))
        relationships = fromstring(archive.read("word/_rels/document.xml.rels"))
    custom = SubElement(
        styles,
        qn("w", "style"),
        {
            qn("w", "type"): "paragraph",
            qn("w", "styleId"): "CustomBody",
            qn("w", "customStyle"): "1",
        },
    )
    SubElement(custom, qn("w", "name"), {qn("w", "val"): "Custom Body"})
    SubElement(custom, qn("w", "basedOn"), {qn("w", "val"): "Normal"})
    abstract = next(numbering.iter(qn("w", "abstractNum")))
    level_zero = next(abstract.iter(qn("w", "lvl")))
    level_one = fromstring(tostring(level_zero))
    level_one.attrib[qn("w", "ilvl")] = "1"
    abstract.append(level_one)
    target_paragraph = list(document.iter(qn("w", "p")))[1]
    target_run = next(target_paragraph.iter(qn("w", "r")))
    run_properties = Element(qn("w", "rPr"))
    SubElement(run_properties, qn("w", "b"))
    target_run.insert(0, run_properties)
    SubElement(
        content_types,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {
            "PartName": "/word/theme/theme1.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.theme+xml",
        },
    )
    SubElement(
        relationships,
        qn("rels", "Relationship"),
        {
            "Id": "rIdTheme",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
            "Target": "theme/theme1.xml",
        },
    )
    theme = Element(qn("a", "theme"), {"name": "Test theme"})
    theme_elements = SubElement(theme, qn("a", "themeElements"))
    colors = SubElement(theme_elements, qn("a", "clrScheme"), {"name": "Test"})
    dark = SubElement(colors, qn("a", "dk1"))
    SubElement(dark, qn("a", "srgbClr"), {"val": "000000"})
    fonts = SubElement(theme_elements, qn("a", "fontScheme"), {"name": "Test"})
    major = SubElement(fonts, qn("a", "majorFont"))
    SubElement(major, qn("a", "latin"), {"typeface": "Aptos Display"})
    minor = SubElement(fonts, qn("a", "minorFont"))
    SubElement(minor, qn("a", "latin"), {"typeface": "Aptos"})
    SubElement(theme_elements, qn("a", "fmtScheme"), {"name": "Test"})
    source = tmp_path / "custom-formatting.docx"
    _rewrite_parts(
        complex_base,
        source,
        {
            "word/styles.xml": tostring(styles, encoding="utf-8", xml_declaration=True),
            "word/numbering.xml": tostring(
                numbering,
                encoding="utf-8",
                xml_declaration=True,
            ),
            "word/document.xml": tostring(
                document,
                encoding="utf-8",
                xml_declaration=True,
            ),
            "[Content_Types].xml": tostring(
                content_types,
                encoding="utf-8",
                xml_declaration=True,
            ),
            "word/_rels/document.xml.rels": tostring(
                relationships,
                encoding="utf-8",
                xml_declaration=True,
            ),
            "word/theme/theme1.xml": tostring(
                theme,
                encoding="utf-8",
                xml_declaration=True,
            ),
        },
    )
    projected = _read(project_root, tmp_path, source, "formatting-read.json")
    formatting = projected["formatting"]
    custom_style = next(
        style for style in formatting["styles"] if style["id"] == "CustomBody"
    )
    assert custom_style["custom"] is True
    assert custom_style["based_on"] == "Normal"
    assert formatting["numbering"]["abstract_definitions"][0]["levels"] == [0, 1]
    assert formatting["theme"]["major_latin"] is not None
    assert formatting["direct_formatting"]["run_count"] >= 1
    assert formatting["normalization_report"]["status"] == "review_required"

    output = tmp_path / "custom-formatting-edited.docx"
    target = {
        "story": "body",
        "paragraph_index": 1,
        "expected_text": "Field anchor",
    }
    request = _request(
        tmp_path,
        "custom-formatting-edit.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "edits": [
                    {"type": "paragraph_style", "target": target, "style": "CustomBody"},
                    {
                        "type": "paragraph_numbering_update",
                        "target": target,
                        "numbering": {"num_id": "1", "level": 1},
                    },
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    updated = _read(project_root, tmp_path, output, "custom-formatting-updated.json")
    body = next(story for story in updated["stories"] if story["kind"] == "body")
    paragraph = body["paragraphs"][1]
    assert paragraph["style"] == "CustomBody"
    assert paragraph["numbering"] == {"numbering_id": "1", "level": "1"}
