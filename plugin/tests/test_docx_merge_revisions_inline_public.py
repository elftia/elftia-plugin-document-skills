import json
from pathlib import Path
import shutil
import subprocess
from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS
from xml.etree.ElementTree import Element, fromstring, SubElement, tostring
import zipfile

from document_skills_core.core.io.paths import sha256_file
from document_skills_core.formats.docx.constants import qn


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
        timeout=PUBLIC_CLI_TEST_TIMEOUT_SECONDS,
    )
    return json.loads(completed.stdout)


def _request(directory: Path, name: str, payload: dict[str, object]) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _create_document(
    project_root: Path,
    tmp_path: Path,
    *,
    name: str,
    text: str,
) -> Path:
    output = tmp_path / f"{name}-plain.docx"
    request = _request(
        tmp_path,
        f"{name}-create.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {
                "report": {"blocks": [{"type": "paragraph", "text": text}]}
            },
        },
    )
    result = _public(project_root, "run", "--request", str(request))
    assert result["status"] == "success", result
    return output


def _revision(
    parent: Element,
    *,
    tag: str,
    revision_id: str,
    author: str,
    text: str,
) -> Element:
    revision = SubElement(
        parent,
        qn("w", tag),
        {
            qn("w", "id"): revision_id,
            qn("w", "author"): author,
            qn("w", "date"): "2026-08-24T00:00:00Z",
        },
    )
    run = SubElement(revision, qn("w", "r"))
    value = SubElement(
        run,
        qn("w", "delText" if tag in {"del", "moveFrom"} else "t"),
    )
    value.text = text
    return revision


def _complete_move_graph(parent: Element, *, label: str) -> None:
    author = f"{label} mover"
    date = "2026-08-24T00:00:00Z"
    name = f"{label} move"
    SubElement(
        parent,
        qn("w", "moveFromRangeStart"),
        {
            qn("w", "id"): "5",
            qn("w", "name"): name,
            qn("w", "author"): author,
            qn("w", "date"): date,
        },
    )
    _revision(
        parent,
        tag="moveFrom",
        revision_id="3",
        author=author,
        text=f"{label} move from",
    )
    SubElement(parent, qn("w", "moveFromRangeEnd"), {qn("w", "id"): "5"})
    SubElement(
        parent,
        qn("w", "moveToRangeStart"),
        {
            qn("w", "id"): "6",
            qn("w", "name"): name,
            qn("w", "author"): author,
            qn("w", "date"): date,
        },
    )
    _revision(
        parent,
        tag="moveTo",
        revision_id="4",
        author=author,
        text=f"{label} move to",
    )
    SubElement(parent, qn("w", "moveToRangeEnd"), {qn("w", "id"): "6"})


def _add_revisions(
    source: Path,
    destination: Path,
    *,
    label: str,
    nested: bool,
    moves: bool = False,
    complete_moves: bool = False,
) -> None:
    with zipfile.ZipFile(source) as archive:
        parts = {item.filename: archive.read(item) for item in archive.infolist()}
    document = fromstring(parts["word/document.xml"])
    body = document.find(qn("w", "body"))
    assert body is not None
    paragraph = next(body.iter(qn("w", "p")))
    _revision(
        paragraph,
        tag="ins",
        revision_id="1",
        author=f"{label} inserter",
        text=f"{label} insertion",
    )
    _revision(
        paragraph,
        tag="del",
        revision_id="2",
        author=f"{label} deleter",
        text=f"{label} deletion",
    )
    if moves:
        if complete_moves:
            _complete_move_graph(paragraph, label=label)
        else:
            _revision(
                paragraph,
                tag="moveFrom",
                revision_id="3",
                author=f"{label} mover",
                text=f"{label} move from",
            )
            _revision(
                paragraph,
                tag="moveTo",
                revision_id="4",
                author=f"{label} mover",
                text=f"{label} move to",
            )
    if nested:
        table = Element(qn("w", "tbl"))
        SubElement(table, qn("w", "tblPr"))
        grid = SubElement(table, qn("w", "tblGrid"))
        SubElement(grid, qn("w", "gridCol"), {qn("w", "w"): "2400"})
        row = SubElement(table, qn("w", "tr"))
        cell = SubElement(row, qn("w", "tc"))
        nested_paragraph = SubElement(cell, qn("w", "p"))
        _revision(
            nested_paragraph,
            tag="ins",
            revision_id="3",
            author=f"{label} nested inserter",
            text=f"{label} nested insertion",
        )
        _revision(
            nested_paragraph,
            tag="del",
            revision_id="4",
            author=f"{label} nested deleter",
            text=f"{label} nested deletion",
        )
        body.insert(len(body) - 1, table)
    parts["word/document.xml"] = tostring(
        document,
        encoding="utf-8",
        xml_declaration=True,
    )
    with zipfile.ZipFile(destination, "w") as archive:
        for name, payload in sorted(parts.items()):
            archive.writestr(name, payload)


def _add_custom_xml_move_markers(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source) as archive:
        parts = {item.filename: archive.read(item) for item in archive.infolist()}
    document = fromstring(parts["word/document.xml"])
    body = document.find(qn("w", "body"))
    assert body is not None
    paragraph = next(body.iter(qn("w", "p")))
    for tag, revision_id in (
        ("customXmlMoveFromRangeStart", "11"),
        ("customXmlMoveFromRangeEnd", "11"),
        ("customXmlMoveToRangeStart", "12"),
        ("customXmlMoveToRangeEnd", "12"),
    ):
        SubElement(paragraph, qn("w", tag), {qn("w", "id"): revision_id})
    parts["word/document.xml"] = tostring(
        document,
        encoding="utf-8",
        xml_declaration=True,
    )
    with zipfile.ZipFile(destination, "w") as archive:
        for name, payload in sorted(parts.items()):
            archive.writestr(name, payload)


def _add_property_revision(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source) as archive:
        parts = {item.filename: archive.read(item) for item in archive.infolist()}
    document = fromstring(parts["word/document.xml"])
    body = document.find(qn("w", "body"))
    assert body is not None
    paragraph = next(body.iter(qn("w", "p")))
    properties = paragraph.find(qn("w", "pPr"))
    if properties is None:
        properties = Element(qn("w", "pPr"))
        paragraph.insert(0, properties)
    change = SubElement(
        properties,
        qn("w", "pPrChange"),
        {
            qn("w", "id"): "21",
            qn("w", "author"): "Property reviewer",
            qn("w", "date"): "2026-08-24T00:00:00Z",
        },
    )
    SubElement(change, qn("w", "pPr"))
    parts["word/document.xml"] = tostring(
        document,
        encoding="utf-8",
        xml_declaration=True,
    )
    with zipfile.ZipFile(destination, "w") as archive:
        for name, payload in sorted(parts.items()):
            archive.writestr(name, payload)


def test_public_merge_remaps_inline_revision_ids_including_nested_tables(
    project_root: Path,
    tmp_path: Path,
) -> None:
    base_plain = _create_document(
        project_root,
        tmp_path,
        name="revision-merge-base",
        text="Base",
    )
    source_plain = _create_document(
        project_root,
        tmp_path,
        name="revision-merge-source",
        text="Source",
    )
    base = tmp_path / "revision-merge-base.docx"
    source = tmp_path / "revision-merge-source.docx"
    _add_revisions(base_plain, base, label="Base", nested=False)
    _add_revisions(source_plain, source, label="Source", nested=True)
    base_sha256 = sha256_file(base)
    source_sha256 = sha256_file(source)
    output = tmp_path / "revisions-merged.docx"
    request = _request(
        tmp_path,
        "revisions-merge.json",
        {
            "schema_version": "1.0",
            "operation": "docx.merge",
            "input": str(base),
            "output": str(output),
            "arguments": {
                "sources": [
                    {"path": str(source), "expected_sha256": source_sha256}
                ],
                "style_conflict_policy": "require-identical",
                "numbering_conflict_policy": "require-identical",
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    merge = result["diagnostics"]["operation_result"]["merge"]
    assert merge["revision_mappings"] == [
        {"source_id": "1", "source_index": 1, "target_id": "3", "type": "ins"},
        {"source_id": "2", "source_index": 1, "target_id": "4", "type": "del"},
        {"source_id": "3", "source_index": 1, "target_id": "5", "type": "ins"},
        {"source_id": "4", "source_index": 1, "target_id": "6", "type": "del"},
    ]
    assert merge["preserved_revisions"] == 6
    with zipfile.ZipFile(output) as archive:
        document = fromstring(archive.read("word/document.xml"))
    revisions = [
        node
        for tag in ("ins", "del")
        for node in document.iter(qn("w", tag))
    ]
    assert {node.attrib[qn("w", "id")] for node in revisions} == {
        "1", "2", "3", "4", "5", "6"
    }
    assert "Source nested insertion" in "".join(document.itertext())
    assert "Source nested deletion" in "".join(document.itertext())
    assert sha256_file(base) == base_sha256
    assert sha256_file(source) == source_sha256


def test_public_merge_remaps_complete_move_revision_graph(
    project_root: Path,
    tmp_path: Path,
) -> None:
    base_plain = _create_document(
        project_root,
        tmp_path,
        name="move-graph-base",
        text="Base",
    )
    source_plain = _create_document(
        project_root,
        tmp_path,
        name="move-graph-source",
        text="Source",
    )
    base = tmp_path / "move-graph-base.docx"
    source = tmp_path / "move-graph-source.docx"
    _add_revisions(
        base_plain,
        base,
        label="Shared",
        nested=False,
        moves=True,
        complete_moves=True,
    )
    _add_revisions(
        source_plain,
        source,
        label="Shared",
        nested=False,
        moves=True,
        complete_moves=True,
    )
    base_sha256 = sha256_file(base)
    source_sha256 = sha256_file(source)
    output = tmp_path / "move-graph-merged.docx"
    request = _request(
        tmp_path,
        "move-graph-merge.json",
        {
            "schema_version": "1.0",
            "operation": "docx.merge",
            "input": str(base),
            "output": str(output),
            "arguments": {
                "sources": [
                    {"path": str(source), "expected_sha256": source_sha256}
                ],
                "style_conflict_policy": "require-identical",
                "numbering_conflict_policy": "require-identical",
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    merge = result["diagnostics"]["operation_result"]["merge"]
    assert merge["revision_mappings"] == [
        {"source_id": "1", "source_index": 1, "target_id": "7", "type": "ins"},
        {"source_id": "2", "source_index": 1, "target_id": "8", "type": "del"},
        {
            "source_id": "3",
            "source_index": 1,
            "target_id": "9",
            "type": "moveFrom",
        },
        {
            "source_id": "4",
            "source_index": 1,
            "target_id": "10",
            "type": "moveTo",
        },
    ]
    assert merge["move_range_mappings"] == [
        {
            "source_id": "5",
            "source_index": 1,
            "target_id": "11",
            "type": "moveFromRange",
        },
        {
            "source_id": "6",
            "source_index": 1,
            "target_id": "12",
            "type": "moveToRange",
        },
    ]
    assert merge["move_name_mappings"] == [
        {
            "source_index": 1,
            "source_name": "Shared move",
            "target_name": "move_1_1ca0ce162c5080f6",
        }
    ]
    assert merge["preserved_revisions"] == 8
    assert merge["preserved_move_ranges"] == 4
    with zipfile.ZipFile(output) as archive:
        document = fromstring(archive.read("word/document.xml"))
    revision_ids = {
        node.attrib[qn("w", "id")]
        for tag in ("ins", "del", "moveFrom", "moveTo")
        for node in document.iter(qn("w", tag))
    }
    assert revision_ids == {"1", "2", "3", "4", "7", "8", "9", "10"}
    range_ids = {
        node.attrib[qn("w", "id")]
        for tag in ("moveFromRangeStart", "moveToRangeStart")
        for node in document.iter(qn("w", tag))
    }
    assert range_ids == {"5", "6", "11", "12"}
    assert "Shared move from" in "".join(document.itertext())
    assert "Shared move to" in "".join(document.itertext())
    assert sha256_file(base) == base_sha256
    assert sha256_file(source) == source_sha256


def test_public_merge_rejects_move_revision_graph_without_publishing(
    project_root: Path,
    tmp_path: Path,
) -> None:
    base = _create_document(
        project_root,
        tmp_path,
        name="move-revision-base",
        text="Base",
    )
    source_plain = _create_document(
        project_root,
        tmp_path,
        name="move-revision-source",
        text="Source",
    )
    source = tmp_path / "move-revision-source.docx"
    _add_revisions(
        source_plain,
        source,
        label="Source",
        nested=False,
        moves=True,
    )
    source_sha256 = sha256_file(source)
    base_sha256 = sha256_file(base)
    output = tmp_path / "move-revisions-merged.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "move-revisions-merge.json",
        {
            "schema_version": "1.0",
            "operation": "docx.merge",
            "input": str(base),
            "output": str(output),
            "arguments": {
                "sources": [
                    {"path": str(source), "expected_sha256": source_sha256}
                ],
                "style_conflict_policy": "require-identical",
                "numbering_conflict_policy": "require-identical",
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

    assert result["status"] == "enhancement_required", result
    error = result["errors"][0]
    assert error["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert error["details"]["structures"] == ["moveFrom", "moveTo"]
    assert output.read_bytes() == original_destination
    assert sha256_file(base) == base_sha256
    assert sha256_file(source) == source_sha256


def test_public_merge_rejects_custom_xml_move_graph_without_publishing(
    project_root: Path,
    tmp_path: Path,
) -> None:
    base = _create_document(
        project_root,
        tmp_path,
        name="custom-move-base",
        text="Base",
    )
    source_plain = _create_document(
        project_root,
        tmp_path,
        name="custom-move-source",
        text="Source",
    )
    source = tmp_path / "custom-move-source.docx"
    _add_custom_xml_move_markers(source_plain, source)
    source_sha256 = sha256_file(source)
    base_sha256 = sha256_file(base)
    output = tmp_path / "custom-move-merged.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "custom-move-merge.json",
        {
            "schema_version": "1.0",
            "operation": "docx.merge",
            "input": str(base),
            "output": str(output),
            "arguments": {
                "sources": [
                    {"path": str(source), "expected_sha256": source_sha256}
                ],
                "style_conflict_policy": "require-identical",
                "numbering_conflict_policy": "require-identical",
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

    assert result["status"] == "enhancement_required", result
    error = result["errors"][0]
    assert error["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert error["details"]["structures"] == [
        "customXmlMoveFromRangeEnd",
        "customXmlMoveFromRangeStart",
        "customXmlMoveToRangeEnd",
        "customXmlMoveToRangeStart",
    ]
    assert output.read_bytes() == original_destination
    assert sha256_file(base) == base_sha256
    assert sha256_file(source) == source_sha256


def test_public_merge_rejects_unplanned_property_revision_without_publishing(
    project_root: Path,
    tmp_path: Path,
) -> None:
    base = _create_document(
        project_root,
        tmp_path,
        name="property-revision-base",
        text="Base",
    )
    source_plain = _create_document(
        project_root,
        tmp_path,
        name="property-revision-source",
        text="Source",
    )
    source = tmp_path / "property-revision-source.docx"
    _add_property_revision(source_plain, source)
    source_sha256 = sha256_file(source)
    base_sha256 = sha256_file(base)
    output = tmp_path / "property-revision-merged.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "property-revision-merge.json",
        {
            "schema_version": "1.0",
            "operation": "docx.merge",
            "input": str(base),
            "output": str(output),
            "arguments": {
                "sources": [
                    {"path": str(source), "expected_sha256": source_sha256}
                ],
                "style_conflict_policy": "require-identical",
                "numbering_conflict_policy": "require-identical",
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

    assert result["status"] == "enhancement_required", result
    error = result["errors"][0]
    assert error["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert error["details"]["structures"] == ["pPrChange"]
    assert output.read_bytes() == original_destination
    assert sha256_file(base) == base_sha256
    assert sha256_file(source) == source_sha256
