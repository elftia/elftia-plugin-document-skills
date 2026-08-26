import json
from pathlib import Path
import shutil
import subprocess
from xml.etree.ElementTree import fromstring, SubElement, tostring
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
        timeout=60,
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
    output = tmp_path / f"{name}.docx"
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


def _add_raw_field(
    source: Path,
    destination: Path,
    *,
    instruction: str,
    display_text: str,
) -> None:
    with zipfile.ZipFile(source) as archive:
        parts = {item.filename: archive.read(item) for item in archive.infolist()}
    document = fromstring(parts["word/document.xml"])
    paragraph = next(document.iter(qn("w", "p")))
    field = SubElement(
        paragraph,
        qn("w", "fldSimple"),
        {qn("w", "instr"): instruction},
    )
    run = SubElement(field, qn("w", "r"))
    text = SubElement(run, qn("w", "t"))
    text.text = display_text
    parts["word/document.xml"] = tostring(
        document,
        encoding="utf-8",
        xml_declaration=True,
    )
    with zipfile.ZipFile(destination, "w") as archive:
        for name, payload in sorted(parts.items()):
            archive.writestr(name, payload)


def test_public_merge_preserves_safe_word_fields(
    project_root: Path,
    tmp_path: Path,
) -> None:
    base = _create_document(
        project_root,
        tmp_path,
        name="field-merge-base",
        text="Base",
    )
    plain_source = _create_document(
        project_root,
        tmp_path,
        name="field-merge-source-plain",
        text="Source",
    )
    source = tmp_path / "field-merge-source.docx"
    edit_request = _request(
        tmp_path,
        "field-merge-edit.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(plain_source),
            "output": str(source),
            "arguments": {
                "edits": [
                    {
                        "type": "field_insert",
                        "target": {
                            "story": "body",
                            "paragraph_index": 0,
                            "expected_text": "Source",
                        },
                        "placement": "append",
                        "field": {"kind": "AUTHOR", "display_text": "Alice"},
                    }
                ]
            },
        },
    )
    edited = _public(project_root, "run", "--request", str(edit_request))
    assert edited["status"] == "success", edited
    source_sha256 = sha256_file(source)
    base_sha256 = sha256_file(base)
    output = tmp_path / "field-merged.docx"
    merge_request = _request(
        tmp_path,
        "field-merge.json",
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

    result = _public(project_root, "run", "--request", str(merge_request))

    assert result["status"] == "success", result
    merge = result["diagnostics"]["operation_result"]["merge"]
    assert merge["preserved_fields"] == 1
    assert sha256_file(base) == base_sha256
    assert sha256_file(source) == source_sha256
    with zipfile.ZipFile(output) as archive:
        document = fromstring(archive.read("word/document.xml"))
    fields = list(document.iter(qn("w", "fldSimple")))
    assert [field.attrib[qn("w", "instr")] for field in fields] == ["AUTHOR"]
    assert "".join(fields[0].itertext()) == "Alice"


def test_public_merge_rejects_dde_fields_without_publishing(
    project_root: Path,
    tmp_path: Path,
) -> None:
    base = _create_document(
        project_root,
        tmp_path,
        name="dde-merge-base",
        text="Base",
    )
    plain_source = _create_document(
        project_root,
        tmp_path,
        name="dde-merge-source-plain",
        text="Source",
    )
    source = tmp_path / "dde-merge-source.docx"
    _add_raw_field(
        plain_source,
        source,
        instruction='DDEAUTO "cmd" "/c calc"',
        display_text="blocked",
    )
    source_sha256 = sha256_file(source)
    base_sha256 = sha256_file(base)
    output = tmp_path / "dde-merged.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "dde-merge.json",
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

    assert result["status"] == "failed", result
    error = result["errors"][0]
    assert error["code"] == "DS_ARCHIVE_UNSAFE"
    assert error["details"]["security_inventory"]["categories"]["dde"] == [
        {"part": "word/document.xml", "kind": "field-code"}
    ]
    assert output.read_bytes() == original_destination
    assert sha256_file(base) == base_sha256
    assert sha256_file(source) == source_sha256
