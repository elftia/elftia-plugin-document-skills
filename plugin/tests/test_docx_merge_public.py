import base64
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS
from xml.etree.ElementTree import Element, fromstring, SubElement, tostring
import zipfile

import pytest

from document_skills_core.core.io.paths import sha256_file
from document_skills_core.formats.docx.constants import qn

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _public(
    project_root: Path,
    *args: str,
    cwd: Path | None = None,
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
        cwd=cwd or project_root,
        capture_output=True,
        text=True,
        check=check,
        timeout=PUBLIC_CLI_TEST_TIMEOUT_SECONDS,
    )
    return json.loads(completed.stdout)


def _write_request(directory: Path, name: str, payload: dict[str, object]) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def merge_base(project_root: Path, tmp_path: Path) -> Path:
    output = tmp_path / "base.docx"
    request = _write_request(
        tmp_path,
        "create-base.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "report": {
                    "blocks": [{"type": "paragraph", "text": "Base"}]
                }
            },
        },
    )
    result = _public(project_root, "run", "--request", str(request))
    assert result["status"] == "success", result
    return output


def _merge_payload(
    base: str,
    output: str,
    sources: list[dict[str, str]],
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": "docx.merge",
        "input": base,
        "output": output,
        "arguments": {
            "sources": sources,
            "style_conflict_policy": "require-identical",
            "numbering_conflict_policy": "require-identical",
        },
    }


def _rewrite_docx(source: Path, destination: Path, changes: dict[str, bytes]) -> None:
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


def test_public_merge_accepts_sixteen_relative_sources(
    project_root: Path,
    merge_base: Path,
    tmp_path: Path,
) -> None:
    invocation = tmp_path / "relative-merge"
    sources_dir = invocation / "sources"
    output_dir = invocation / "output"
    sources_dir.mkdir(parents=True)
    output_dir.mkdir()
    sources = []
    for index in range(16):
        source = sources_dir / f"source-{index:02d}.docx"
        source.write_bytes(merge_base.read_bytes())
        sources.append(
            {
                "path": f"sources/{source.name}",
                "expected_sha256": sha256_file(source),
            }
        )
    request = _write_request(
        invocation,
        "merge.json",
        _merge_payload(str(merge_base), "output/merged.docx", sources),
    )

    result = _public(
        project_root,
        "run",
        "--request",
        request.name,
        cwd=invocation,
    )

    assert result["status"] == "success", result
    merge = result["diagnostics"]["operation_result"]["merge"]
    assert merge["source_count"] == 16
    assert (output_dir / "merged.docx").is_file()


def test_public_merge_contract_rejects_unsafe_shapes_and_aliases(
    project_root: Path,
    merge_base: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.docx"
    source.write_bytes(merge_base.read_bytes())
    source_record = {
        "path": str(source),
        "expected_sha256": sha256_file(source),
    }
    output = tmp_path / "output.docx"
    cases = []

    unknown = _merge_payload(str(merge_base), str(output), [source_record])
    unknown["arguments"]["raw_xml"] = "<w:p/>"
    cases.append(("unknown.json", unknown, "DS_REQUEST_INVALID"))

    for key in ("style_conflict_policy", "numbering_conflict_policy"):
        invalid_policy = _merge_payload(str(merge_base), str(output), [source_record])
        invalid_policy["arguments"][key] = "overwrite-base"
        cases.append((f"invalid-{key}.json", invalid_policy, "DS_REQUEST_INVALID"))

    too_many = []
    for index in range(17):
        extra = tmp_path / f"extra-{index:02d}.docx"
        extra.write_bytes(merge_base.read_bytes())
        too_many.append({"path": str(extra), "expected_sha256": sha256_file(extra)})
    cases.append(
        (
            "too-many.json",
            _merge_payload(str(merge_base), str(output), too_many),
            "DS_REQUEST_INVALID",
        )
    )

    alias = _merge_payload(str(merge_base), str(source), [source_record])
    cases.append(("output-alias.json", alias, "DS_OUTPUT_EQUALS_INPUT"))

    for name, payload, expected_code in cases:
        request = _write_request(tmp_path, name, payload)
        result = _public(
            project_root,
            "run",
            "--request",
            str(request),
            check=False,
        )
        assert result["status"] in {"invalid_request", "failed"}, result
        assert result["errors"][0]["code"] == expected_code


def test_public_merge_rejects_portably_duplicate_source_paths(
    project_root: Path,
    merge_base: Path,
    tmp_path: Path,
) -> None:
    ascii_source = tmp_path / "A.docx"
    compatibility_source = tmp_path / "Ａ.docx"
    ascii_source.write_bytes(merge_base.read_bytes())
    compatibility_source.write_bytes(merge_base.read_bytes())
    output = tmp_path / "portable-duplicate.docx"
    original_destination = b"destination must survive"
    output.write_bytes(original_destination)
    request = _write_request(
        tmp_path,
        "portable-duplicate.json",
        _merge_payload(
            str(merge_base),
            str(output),
            [
                {
                    "path": str(ascii_source),
                    "expected_sha256": sha256_file(ascii_source),
                },
                {
                    "path": str(compatibility_source),
                    "expected_sha256": sha256_file(compatibility_source),
                },
            ],
        ),
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
    assert output.read_bytes() == original_destination


def test_public_merge_renames_conflicting_source_styles_and_rewrites_references(
    project_root: Path,
    merge_base: Path,
    tmp_path: Path,
) -> None:
    with zipfile.ZipFile(merge_base) as archive:
        styles = fromstring(archive.read("word/styles.xml"))
        document = fromstring(archive.read("word/document.xml"))
    normal = next(
        style
        for style in styles.findall(qn("w", "style"))
        if style.attrib.get(qn("w", "styleId")) == "Normal"
    )
    run_properties = normal.find(qn("w", "rPr"))
    if run_properties is None:
        run_properties = SubElement(normal, qn("w", "rPr"))
    SubElement(run_properties, qn("w", "color"), {qn("w", "val"): "AA2255"})
    paragraph = next(document.iter(qn("w", "p")))
    paragraph_properties = paragraph.find(qn("w", "pPr"))
    if paragraph_properties is None:
        paragraph_properties = SubElement(paragraph, qn("w", "pPr"))
    paragraph_properties.insert(
        0,
        Element(
            qn("w", "pStyle"),
            {qn("w", "val"): "Normal"},
        ),
    )
    source = tmp_path / "style-conflict.docx"
    _rewrite_docx(
        merge_base,
        source,
        {
            "word/styles.xml": tostring(styles, encoding="utf-8", xml_declaration=True),
            "word/document.xml": tostring(
                document,
                encoding="utf-8",
                xml_declaration=True,
            ),
        },
    )
    output = tmp_path / "style-renamed.docx"
    payload = _merge_payload(
        str(merge_base),
        str(output),
        [{"path": str(source), "expected_sha256": sha256_file(source)}],
    )
    payload["arguments"]["style_conflict_policy"] = "rename-source"
    request = _write_request(tmp_path, "style-rename.json", payload)

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    merge = result["diagnostics"]["operation_result"]["merge"]
    assert merge["styles"] == "remapped"
    assert merge["style_mappings"] == [
        {
            "source_index": 1,
            "source_style_id": "Normal",
            "target_style_id": "Merge1_Normal",
            "action": "renamed",
        }
    ]
    with zipfile.ZipFile(output) as archive:
        output_styles = fromstring(archive.read("word/styles.xml"))
        output_document = fromstring(archive.read("word/document.xml"))
    style_ids = {
        style.attrib.get(qn("w", "styleId"))
        for style in output_styles.findall(qn("w", "style"))
    }
    assert "Normal" in style_ids
    assert "Merge1_Normal" in style_ids
    assert any(
        node.attrib.get(qn("w", "val")) == "Merge1_Normal"
        for node in output_document.iter(qn("w", "pStyle"))
    )


def test_public_merge_remaps_source_numbering_ids_and_body_references(
    project_root: Path,
    merge_base: Path,
    tmp_path: Path,
) -> None:
    with zipfile.ZipFile(merge_base) as archive:
        numbering = fromstring(archive.read("word/numbering.xml"))
        document = fromstring(archive.read("word/document.xml"))
    abstract = next(numbering.iter(qn("w", "abstractNum")))
    abstract.attrib[qn("w", "abstractNumId")] = "7"
    number = next(numbering.iter(qn("w", "num")))
    number.attrib[qn("w", "numId")] = "7"
    number.find(qn("w", "abstractNumId")).attrib[qn("w", "val")] = "7"
    paragraph = next(document.iter(qn("w", "p")))
    paragraph_properties = paragraph.find(qn("w", "pPr"))
    if paragraph_properties is None:
        paragraph_properties = Element(qn("w", "pPr"))
        paragraph.insert(0, paragraph_properties)
    numbering_properties = SubElement(paragraph_properties, qn("w", "numPr"))
    SubElement(numbering_properties, qn("w", "ilvl"), {qn("w", "val"): "0"})
    SubElement(numbering_properties, qn("w", "numId"), {qn("w", "val"): "7"})
    source = tmp_path / "numbering-conflict.docx"
    _rewrite_docx(
        merge_base,
        source,
        {
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
        },
    )
    output = tmp_path / "numbering-remapped.docx"
    payload = _merge_payload(
        str(merge_base),
        str(output),
        [{"path": str(source), "expected_sha256": sha256_file(source)}],
    )
    payload["arguments"]["numbering_conflict_policy"] = "remap-source"
    request = _write_request(tmp_path, "numbering-remap.json", payload)

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    merge = result["diagnostics"]["operation_result"]["merge"]
    assert merge["numbering"] == "remapped"
    assert merge["abstract_num_mappings"] == [
        {"source_index": 1, "source_id": "7", "target_id": "2"}
    ]
    assert merge["num_mappings"] == [
        {"source_index": 1, "source_id": "7", "target_id": "2"}
    ]
    with zipfile.ZipFile(output) as archive:
        output_numbering = fromstring(archive.read("word/numbering.xml"))
        output_document = fromstring(archive.read("word/document.xml"))
    assert {
        node.attrib[qn("w", "abstractNumId")]
        for node in output_numbering.iter(qn("w", "abstractNum"))
    } == {"1", "2"}
    assert {
        node.attrib[qn("w", "numId")]
        for node in output_numbering.iter(qn("w", "num"))
    } == {"1", "2"}
    assert any(
        node.attrib.get(qn("w", "val")) == "2"
        for node in output_document.iter(qn("w", "numId"))
    )


def test_public_merge_remaps_colliding_bookmarks_and_internal_links(
    project_root: Path,
    merge_base: Path,
    tmp_path: Path,
) -> None:
    linked_documents = []
    for label in ("base", "source"):
        output = tmp_path / f"{label}-linked.docx"
        request = _write_request(
            tmp_path,
            f"{label}-linked.json",
            {
                "schema_version": "1.0",
                "operation": "docx.edit",
                "input": str(merge_base),
                "output": str(output),
                "arguments": {
                    "edits": [
                        {
                            "type": "bookmark_insert",
                            "target": {
                                "story": "body",
                                "paragraph_index": 0,
                                "expected_text": "Base",
                            },
                            "name": "Shared",
                            "range": "paragraph",
                        },
                        {
                            "type": "hyperlink_insert",
                            "target": {
                                "story": "body",
                                "paragraph_index": 0,
                                "expected_text": "Base",
                            },
                            "bookmark_name": "Shared",
                            "placement": "append",
                            "text": f"Jump from {label}",
                        },
                    ]
                },
            },
        )
        result = _public(project_root, "run", "--request", str(request))
        assert result["status"] == "success", result
        linked_documents.append(output)
    output = tmp_path / "bookmark-merged.docx"
    request = _write_request(
        tmp_path,
        "bookmark-merge.json",
        _merge_payload(
            str(linked_documents[0]),
            str(output),
            [
                {
                    "path": str(linked_documents[1]),
                    "expected_sha256": sha256_file(linked_documents[1]),
                }
            ],
        ),
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    mappings = result["diagnostics"]["operation_result"]["merge"][
        "bookmark_mappings"
    ]
    assert mappings == [
        {
            "source_index": 1,
            "source_id": "0",
            "target_id": "1",
            "source_name": "Shared",
            "target_name": "Merge1_Shared",
        }
    ]
    with zipfile.ZipFile(output) as archive:
        document = fromstring(archive.read("word/document.xml"))
    starts = list(document.iter(qn("w", "bookmarkStart")))
    ends = list(document.iter(qn("w", "bookmarkEnd")))
    assert {node.attrib[qn("w", "id")] for node in starts} == {"0", "1"}
    assert {node.attrib[qn("w", "id")] for node in ends} == {"0", "1"}
    assert {node.attrib[qn("w", "name")] for node in starts} == {
        "Shared",
        "Merge1_Shared",
    }
    assert {
        node.attrib[qn("w", "anchor")]
        for node in document.iter(qn("w", "hyperlink"))
    } == {"Shared", "Merge1_Shared"}


def test_public_merge_copies_nested_header_image_relationship_graph(
    project_root: Path,
    merge_base: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "header-image.png"
    image.write_bytes(_PNG)
    created_source = tmp_path / "header-image-created.docx"
    create_request = _write_request(
        tmp_path,
        "header-image-create.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(created_source),
            "arguments": {
                "report": {
                    "header": "Header with image",
                    "blocks": [
                        {"type": "paragraph", "text": "Nested graph source"},
                        {
                            "type": "image",
                            "path": str(image),
                            "alt_text": "Header mark",
                            "width_inches": 1,
                        },
                    ],
                }
            },
        },
    )
    created = _public(project_root, "run", "--request", str(create_request))
    assert created["status"] == "success", created
    with zipfile.ZipFile(created_source) as archive:
        document = fromstring(archive.read("word/document.xml"))
        relationships = fromstring(archive.read("word/_rels/document.xml.rels"))
        header = fromstring(archive.read("word/header1.xml"))
    body = document.find(qn("w", "body"))
    drawing_paragraph = next(
        paragraph
        for paragraph in body.findall(qn("w", "p"))
        if next(paragraph.iter(qn("w", "drawing")), None) is not None
    )
    drawing = next(drawing_paragraph.iter(qn("w", "drawing")))
    header_paragraph = next(header.iter(qn("w", "p")))
    run = SubElement(header_paragraph, qn("w", "r"))
    run.append(deepcopy(drawing))
    body.remove(drawing_paragraph)
    image_relationship = next(
        node
        for node in relationships.findall(qn("rels", "Relationship"))
        if node.attrib["Type"].endswith("/image")
    )
    image_relationship_id = image_relationship.attrib["Id"]
    relationships.remove(image_relationship)
    header_relationships = Element(qn("rels", "Relationships"))
    SubElement(
        header_relationships,
        qn("rels", "Relationship"),
        {
            "Id": image_relationship_id,
            "Type": image_relationship.attrib["Type"],
            "Target": "media/image1.png",
        },
    )
    source = tmp_path / "header-image-source.docx"
    _rewrite_docx(
        created_source,
        source,
        {
            "word/document.xml": tostring(
                document,
                encoding="utf-8",
                xml_declaration=True,
            ),
            "word/_rels/document.xml.rels": tostring(
                relationships,
                encoding="utf-8",
                xml_declaration=True,
            ),
            "word/header1.xml": tostring(
                header,
                encoding="utf-8",
                xml_declaration=True,
            ),
            "word/_rels/header1.xml.rels": tostring(
                header_relationships,
                encoding="utf-8",
                xml_declaration=True,
            ),
        },
    )
    output = tmp_path / "nested-header-merged.docx"
    request = _write_request(
        tmp_path,
        "nested-header-merge.json",
        _merge_payload(
            str(merge_base),
            str(output),
            [{"path": str(source), "expected_sha256": sha256_file(source)}],
        ),
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    part_mappings = result["diagnostics"]["operation_result"]["merge"][
        "part_mappings"
    ]
    header_mapping = next(
        item for item in part_mappings if item["source_part"] == "word/header1.xml"
    )
    image_mapping = next(
        item for item in part_mappings if item["source_part"] == "word/media/image1.png"
    )
    header_part = header_mapping["target_part"]
    image_part = image_mapping["target_part"]
    header_path = Path(header_part)
    header_rels = (
        header_path.parent / "_rels" / f"{header_path.name}.rels"
    ).as_posix()
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        merged_header = fromstring(archive.read(header_part))
        merged_header_rels = fromstring(archive.read(header_rels))
    assert {header_part, header_rels, image_part}.issubset(names)
    embedded_id = next(merged_header.iter(qn("a", "blip"))).attrib[qn("r", "embed")]
    nested_relationship = next(
        node
        for node in merged_header_rels.findall(qn("rels", "Relationship"))
        if node.attrib["Id"] == embedded_id
    )
    assert nested_relationship.attrib["Target"] == Path(image_part).relative_to(
        "word"
    ).as_posix()
