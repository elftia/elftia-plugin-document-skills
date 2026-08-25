import json
from pathlib import Path
import shutil
import subprocess
from xml.etree.ElementTree import fromstring, SubElement, tostring
import zipfile

import pytest

from document_skills_core.core.io.paths import sha256_file
from document_skills_core.formats.docx.constants import CONTENT_TYPES_NS, qn


def _public(
    project_root: Path,
    *arguments: str,
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
            str(project_root / "skills/document-docx/scripts/run.py"),
            *arguments,
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
    path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
    return path


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
def macro_source(project_root: Path, tmp_path: Path) -> tuple[Path, bytes]:
    base = tmp_path / "macro-base.docx"
    create_request = _request(
        tmp_path,
        "macro-create.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(base),
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
    created = _public(project_root, "run", "--request", str(create_request))
    assert created["status"] == "success", created
    with zipfile.ZipFile(base) as archive:
        content_types = fromstring(archive.read("[Content_Types].xml"))
        relationships = fromstring(archive.read("word/_rels/document.xml.rels"))
    document_override = next(
        node
        for node in content_types.findall(f"{{{CONTENT_TYPES_NS}}}Override")
        if node.attrib.get("PartName") == "/word/document.xml"
    )
    document_override.attrib["ContentType"] = (
        "application/vnd.ms-word.document.macroEnabled.main+xml"
    )
    SubElement(
        content_types,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {
            "PartName": "/word/vbaProject.bin",
            "ContentType": "application/vnd.ms-office.vbaProject",
        },
    )
    SubElement(
        relationships,
        qn("rels", "Relationship"),
        {
            "Id": "rIdVbaProject",
            "Type": "http://schemas.microsoft.com/office/2006/relationships/vbaProject",
            "Target": "vbaProject.bin",
        },
    )
    macro_payload = b"inert-vba-project-payload"
    source = tmp_path / "macro-source.docm"
    _rewrite_parts(
        base,
        source,
        {
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
            "word/vbaProject.bin": macro_payload,
        },
    )
    return source, macro_payload


def _edit_request(tmp_path: Path, source: Path, output: Path, name: str) -> Path:
    return _request(
        tmp_path,
        name,
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {
                "keep_vba": True,
                "edits": [
                    {
                        "type": "paragraph_style",
                        "target": {
                            "story": "body",
                            "paragraph_index": 1,
                            "expected_text": "Field anchor",
                        },
                        "style": "Heading2",
                    }
                ],
            },
        },
    )


def test_public_docm_inert_inventory_and_explicit_keep_vba_edit(
    project_root: Path,
    macro_source: tuple[Path, bytes],
    tmp_path: Path,
) -> None:
    source, macro_payload = macro_source
    inspect_request = _request(
        tmp_path,
        "docm-inspect.json",
        {
            "schema_version": "1.0",
            "operation": "docx.inspect.structure",
            "input": str(source),
            "arguments": {"include_hashes": True},
        },
    )
    inspected = _public(project_root, "run", "--request", str(inspect_request))
    assert inspected["status"] == "success", inspected
    security = inspected["diagnostics"]["operation_result"]["dangerous_content"]
    assert security["counts"]["vba"] >= 1
    assert security["mutation_authorized"] is False

    output = tmp_path / "macro-edited.docm"
    request = _edit_request(tmp_path, source, output, "docm-edit.json")
    result = _public(project_root, "run", "--request", str(request))
    assert result["status"] == "success", result
    assert result["diagnostics"]["operation_result"]["vba_preservation"] == {
        "mode": "keep-vba-inert"
    }
    with zipfile.ZipFile(output) as archive:
        assert archive.read("word/vbaProject.bin") == macro_payload
    assert sha256_file(source) == result["artifacts"][0]["sha256"]

    rejected_request = _request(
        tmp_path,
        "docm-edit-without-opt-in.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(source),
            "output": str(tmp_path / "rejected.docm"),
            "arguments": {"edits": []},
        },
    )
    rejected = _public(
        project_root,
        "run",
        "--request",
        str(rejected_request),
        check=False,
    )
    assert rejected["status"] == "invalid_request", rejected


def test_public_docm_keep_vba_rejects_other_dangerous_categories(
    project_root: Path,
    macro_source: tuple[Path, bytes],
    tmp_path: Path,
) -> None:
    source, _macro_payload = macro_source
    with zipfile.ZipFile(source) as archive:
        relationships = fromstring(archive.read("word/_rels/document.xml.rels"))
    SubElement(
        relationships,
        qn("rels", "Relationship"),
        {
            "Id": "rIdExternal",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
            "Target": "https://example.invalid/",
            "TargetMode": "External",
        },
    )
    unsafe = tmp_path / "macro-external.docm"
    _rewrite_parts(
        source,
        unsafe,
        {
            "word/_rels/document.xml.rels": tostring(
                relationships,
                encoding="utf-8",
                xml_declaration=True,
            )
        },
    )
    output = tmp_path / "must-survive.docm"
    sentinel = b"existing destination"
    output.write_bytes(sentinel)
    request = _edit_request(tmp_path, unsafe, output, "docm-external-edit.json")

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "failed", result
    assert result["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"
    assert output.read_bytes() == sentinel
