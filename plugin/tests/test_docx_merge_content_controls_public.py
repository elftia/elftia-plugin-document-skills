import json
from pathlib import Path
import shutil
import subprocess
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


def _add_simple_content_control(
    source: Path,
    destination: Path,
    *,
    data_binding: bool = False,
) -> None:
    with zipfile.ZipFile(source) as archive:
        parts = {item.filename: archive.read(item) for item in archive.infolist()}
    document = fromstring(parts["word/document.xml"])
    body = document.find(qn("w", "body"))
    assert body is not None
    control = Element(qn("w", "sdt"))
    properties = SubElement(control, qn("w", "sdtPr"))
    SubElement(properties, qn("w", "id"), {qn("w", "val"): "42"})
    SubElement(properties, qn("w", "tag"), {qn("w", "val"): "customer"})
    SubElement(properties, qn("w", "alias"), {qn("w", "val"): "Customer"})
    if data_binding:
        SubElement(
            properties,
            qn("w", "dataBinding"),
            {
                qn("w", "storeItemID"): "{11111111-1111-1111-1111-111111111111}",
                qn("w", "xpath"): "/root/customer",
            },
        )
    content = SubElement(control, qn("w", "sdtContent"))
    paragraph = SubElement(content, qn("w", "p"))
    run = SubElement(paragraph, qn("w", "r"))
    text = SubElement(run, qn("w", "t"))
    text.text = "Controlled text"
    body.insert(len(body) - 1, control)
    parts["word/document.xml"] = tostring(
        document,
        encoding="utf-8",
        xml_declaration=True,
    )
    with zipfile.ZipFile(destination, "w") as archive:
        for name, payload in sorted(parts.items()):
            archive.writestr(name, payload)


def test_public_merge_preserves_simple_unlocked_content_controls(
    project_root: Path,
    tmp_path: Path,
) -> None:
    base = _create_document(
        project_root,
        tmp_path,
        name="control-merge-base",
        text="Base",
    )
    plain_source = _create_document(
        project_root,
        tmp_path,
        name="control-merge-source-plain",
        text="Source",
    )
    source = tmp_path / "control-merge-source.docx"
    _add_simple_content_control(plain_source, source)
    source_sha256 = sha256_file(source)
    base_sha256 = sha256_file(base)
    output = tmp_path / "control-merged.docx"
    request = _request(
        tmp_path,
        "control-merge.json",
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
    assert merge["preserved_content_controls"] == 1
    assert sha256_file(base) == base_sha256
    assert sha256_file(source) == source_sha256
    with zipfile.ZipFile(output) as archive:
        document = fromstring(archive.read("word/document.xml"))
    controls = list(document.iter(qn("w", "sdt")))
    assert len(controls) == 1
    assert "".join(controls[0].itertext()) == "Controlled text"
    properties = controls[0].find(qn("w", "sdtPr"))
    assert properties is not None
    assert properties.find(qn("w", "tag")).attrib[qn("w", "val")] == "customer"


def test_public_merge_rejects_data_bound_content_controls_without_publishing(
    project_root: Path,
    tmp_path: Path,
) -> None:
    base = _create_document(
        project_root,
        tmp_path,
        name="bound-control-merge-base",
        text="Base",
    )
    plain_source = _create_document(
        project_root,
        tmp_path,
        name="bound-control-merge-source-plain",
        text="Source",
    )
    source = tmp_path / "bound-control-merge-source.docx"
    _add_simple_content_control(plain_source, source, data_binding=True)
    source_sha256 = sha256_file(source)
    base_sha256 = sha256_file(base)
    output = tmp_path / "bound-control-merged.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "bound-control-merge.json",
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
    assert error["details"]["properties"] == ["dataBinding"]
    assert output.read_bytes() == original_destination
    assert sha256_file(base) == base_sha256
    assert sha256_file(source) == source_sha256
