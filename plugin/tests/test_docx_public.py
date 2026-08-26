import base64
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from document_skills_core.core.contracts.schemas import SchemaCatalog

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _public(
    project_root: Path,
    *arguments: str,
    check: bool = True,
    cwd: Path | None = None,
) -> dict[str, object]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-docx/scripts/run.py"),
            *arguments,
        ],
        cwd=cwd or project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=30,
    )
    if check:
        diagnostic = process.stdout.decode("utf-8", errors="replace")
        assert process.returncode == 0, diagnostic or "public stdout was empty"
    assert process.stderr == b""
    text = process.stdout.decode("utf-8", errors="strict")
    decoder = json.JSONDecoder()
    payload, end = decoder.raw_decode(text)
    assert text[end:].strip() == ""
    assert type(payload) is dict
    return payload


def _request(tmp_path: Path, name: str, payload: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _report(image_path: str) -> dict[str, object]:
    return {
        "metadata": {"title": "Public DOCX"},
        "blocks": [
            {"type": "heading", "text": "Public DOCX", "level": 1},
            {"type": "paragraph", "text": "Hello {name}"},
            {
                "type": "table",
                "rows": [["Key", "Value"], ["Target", "PUBLIC"]],
            },
        ],
        "image": {"path": image_path, "alt_text": "pixel"},
        "header": "Header PUBLIC",
        "footer": "Footer PUBLIC",
        "sections": [
            {"orientation": "portrait"},
            {"orientation": "landscape"},
        ],
    }


@pytest.fixture
def public_created(project_root: Path, tmp_path: Path) -> Path:
    image = tmp_path / "pixel.png"
    image.write_bytes(_PNG)
    output = tmp_path / "public-created.docx"
    request = _request(
        tmp_path,
        "create.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(output),
            "arguments": {"report": _report(str(image))},
        },
    )
    result = _public(project_root, "run", "--request", str(request))
    assert result["status"] == "success"
    assert result["provider_chain"] == ["core-python"]
    SchemaCatalog(project_root).validate("operation-result", result)
    return output


def test_public_capabilities_are_callable_not_detection_inferred(
    project_root: Path,
) -> None:
    report = _public(project_root, "capabilities", "--json")
    operations = {item["operation"]: item for item in report["operations"]}
    assert set(operations) == {
        "docx.create",
        "docx.edit.replace-text",
        "docx.inspect.structure",
        "docx.read",
        "docx.template.apply",
    }
    assert operations["docx.template.apply"]["providers"] == ["core-node"]
    assert all(item["available"] for item in operations.values())
    assert not any(
        provider in item["providers"]
        for item in operations.values()
        for provider in ("libreoffice", "dotnet-openxml")
    )


def test_public_relative_request_and_input_use_invocation_base(
    project_root: Path,
    tmp_path: Path,
) -> None:
    invocation_base = tmp_path / "用户 workspace"
    source = invocation_base / "资料" / "输入.docx"
    source.parent.mkdir(parents=True)
    source.write_bytes((project_root / "tests/fixtures/docx-rich.docx").read_bytes())
    (invocation_base / "请求").mkdir()
    request = _request(
        invocation_base / "请求",
        "读取.json",
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": "资料/输入.docx",
            "arguments": {},
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        request.relative_to(invocation_base).as_posix(),
        cwd=invocation_base,
    )

    assert result["status"] == "success"
    assert result["artifacts"][0]["path"] == str(source.resolve())


def test_public_relative_output_can_target_project_external_directory(
    project_root: Path,
    tmp_path: Path,
) -> None:
    invocation_base = tmp_path / "external invocation"
    source = invocation_base / "input.docx"
    invocation_base.mkdir()
    source.write_bytes((project_root / "tests/fixtures/docx-rich.docx").read_bytes())
    request = _request(
        invocation_base,
        "replace.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit.replace-text",
            "input": "input.docx",
            "output": "用户结果/替换.docx",
            "arguments": {
                "replacements": [
                    {
                        "search": "TARGET",
                        "replace": "REPLACED",
                        "expected_matches": 4,
                    }
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        request.name,
        cwd=invocation_base,
    )

    output = invocation_base / "用户结果" / "替换.docx"
    assert result["status"] == "success"
    assert output.is_file()
    assert any(item["path"] == str(output.resolve()) for item in result["artifacts"])


def test_public_create_rebases_relative_image_and_output_from_unicode_invocation(
    project_root: Path,
    tmp_path: Path,
) -> None:
    invocation_base = tmp_path / "用户 外部工作区"
    image = invocation_base / "素材" / "像素.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(_PNG)
    (invocation_base / "请求").mkdir()
    request = _request(
        invocation_base / "请求",
        "创建.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": "结果/报告.docx",
            "arguments": {"report": _report("素材/像素.png")},
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        request.relative_to(invocation_base).as_posix(),
        cwd=invocation_base,
    )

    output = invocation_base / "结果" / "报告.docx"
    assert result["status"] == "success", result
    assert output.is_file()
    assert any(item["path"] == str(output.resolve()) for item in result["artifacts"])


@pytest.mark.parametrize(
    "image_path",
    ["https://example.invalid/image.png", r"\\example.invalid\share\image.png"],
)
def test_public_create_keeps_nonlocal_image_paths_rejected(
    image_path: str,
    project_root: Path,
    tmp_path: Path,
) -> None:
    invocation_base = tmp_path / "nonlocal image"
    invocation_base.mkdir()
    request = _request(
        invocation_base,
        "create.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": "must-not-exist.docx",
            "arguments": {"report": _report(image_path)},
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        request.name,
        check=False,
        cwd=invocation_base,
    )

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert not (invocation_base / "must-not-exist.docx").exists()


def test_public_validate_reopens_valid_relative_docx(
    project_root: Path,
    tmp_path: Path,
) -> None:
    invocation_base = tmp_path / "验证 workspace"
    document = invocation_base / "资料" / "有效.docx"
    document.parent.mkdir(parents=True)
    document.write_bytes(
        (project_root / "tests/fixtures/docx-rich.docx").read_bytes()
    )

    result = _public(
        project_root,
        "validate",
        "--input",
        "资料/有效.docx",
        "--json",
        cwd=invocation_base,
    )

    outcomes = {item["id"]: item["outcome"] for item in result["gates"]}
    assert result["status"] == "pass"
    assert outcomes["provider.reopen"] == "pass"
    assert outcomes["visual.render"] == "unavailable"
    assert outcomes["schema.full"] == "unavailable"


def test_public_validate_rejects_malformed_docx(
    project_root: Path,
    tmp_path: Path,
) -> None:
    document = tmp_path / "malformed.docx"
    document.write_bytes(b"not a DOCX package")

    result = _public(
        project_root,
        "validate",
        "--input",
        str(document),
        "--json",
        check=False,
    )

    outcomes = {item["id"]: item["outcome"] for item in result["gates"]}
    assert result["status"] == "fail"
    assert outcomes["artifact.magic-extension"] == "fail"
    assert outcomes["provider.reopen"] == "fail"


def test_public_validate_rejects_active_docx(
    project_root: Path,
) -> None:
    document = project_root / "tests/fixtures/docx-malicious-active.docx"

    result = _public(
        project_root,
        "validate",
        "--input",
        str(document),
        "--json",
        check=False,
    )

    gates = {item["id"]: item for item in result["gates"]}
    assert result["status"] == "fail"
    assert gates["ooxml.archive-xml"]["outcome"] == "fail"
    assert gates["provider.reopen"]["outcome"] == "fail"
    assert gates["provider.reopen"]["evidence"]["reason"] == "DS_ARCHIVE_UNSAFE"


def test_public_validate_rejects_docx_missing_required_part(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-rich.docx"
    document = tmp_path / "missing-document-part.docx"
    with zipfile.ZipFile(source) as input_archive:
        with zipfile.ZipFile(document, "w") as output_archive:
            for item in input_archive.infolist():
                if item.filename != "word/document.xml":
                    output_archive.writestr(item, input_archive.read(item))

    result = _public(
        project_root,
        "validate",
        "--input",
        str(document),
        "--json",
        check=False,
    )

    outcomes = {item["id"]: item["outcome"] for item in result["gates"]}
    assert result["status"] == "fail"
    assert outcomes["ooxml.required-part"] == "fail"
    assert outcomes["provider.reopen"] == "fail"


def test_all_five_operations_cross_the_one_shot_public_boundary(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    read_request = _request(
        tmp_path,
        "read.json",
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(public_created),
            "arguments": {"max_paragraphs": 100},
        },
    )
    read = _public(project_root, "run", "--request", str(read_request))
    assert read["status"] == "success"

    inspect_request = _request(
        tmp_path,
        "inspect.json",
        {
            "schema_version": "1.0",
            "operation": "docx.inspect.structure",
            "input": str(public_created),
            "arguments": {},
        },
    )
    inspection = _public(project_root, "run", "--request", str(inspect_request))
    assert inspection["status"] == "success"
    assert inspection["diagnostics"]["operation_result"]["mutation_authorized"] is False

    replace_output = tmp_path / "public-replaced.docx"
    replace_request = _request(
        tmp_path,
        "replace.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit.replace-text",
            "input": str(public_created),
            "output": str(replace_output),
            "arguments": {
                "replacements": [
                    {"search": "PUBLIC", "replace": "REPLACED", "expected_matches": 3}
                ]
            },
        },
    )
    replaced = _public(project_root, "run", "--request", str(replace_request))
    assert replaced["status"] == "success"
    assert replaced["provider_chain"] == ["core-python"]

    template_output = tmp_path / "public-rendered.docx"
    template_request = _request(
        tmp_path,
        "template.json",
        {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(public_created),
            "output": str(template_output),
            "arguments": {"variables": {"name": "Agent"}},
        },
    )
    templated = _public(project_root, "run", "--request", str(template_request))
    assert templated["status"] == "success"
    assert templated["provider_chain"] == ["core-node"]

    assert public_created.is_file()
    assert replace_output.is_file()
    assert template_output.is_file()


def test_public_unknown_format_operation_never_reaches_docx_provider(
    project_root: Path,
    tmp_path: Path,
) -> None:
    request = _request(
        tmp_path,
        "unknown.json",
        {
            "schema_version": "1.0",
            "operation": "pdfx.read",
            "input": str(tmp_path / "input.pdfx"),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(request), check=False)
    assert result["status"] == "invalid_request"
    assert result["provider_chain"] == []
    assert result["errors"][0]["code"] == "DS_OPERATION_UNKNOWN"


def test_public_expected_docx_errors_keep_specific_codes(
    project_root: Path,
    tmp_path: Path,
) -> None:
    invalid_request = _request(
        tmp_path,
        "invalid-docx.json",
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(tmp_path / "input.docx"),
            "arguments": {"unknown": True},
        },
    )
    invalid = _public(
        project_root,
        "run",
        "--request",
        str(invalid_request),
        check=False,
    )
    assert invalid["status"] == "invalid_request"
    assert invalid["provider_chain"] == []
    assert invalid["errors"][0]["code"] == "DS_REQUEST_INVALID"

    fixture_root = project_root / "tests" / "fixtures"
    unsafe_request = _request(
        tmp_path,
        "unsafe-docx.json",
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(fixture_root / "docx-malicious-active.docx"),
            "arguments": {},
        },
    )
    unsafe = _public(
        project_root,
        "run",
        "--request",
        str(unsafe_request),
        check=False,
    )
    assert unsafe["status"] == "failed"
    assert unsafe["provider_chain"] == ["core-python"]
    assert unsafe["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"

    protected_output = tmp_path / "protected-output.docx"
    protected_request = _request(
        tmp_path,
        "protected-docx.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit.replace-text",
            "input": str(fixture_root / "docx-revision-comments.docx"),
            "output": str(protected_output),
            "arguments": {
                "replacements": [
                    {"search": "revision-only", "replace": "changed"}
                ]
            },
        },
    )
    protected = _public(
        project_root,
        "run",
        "--request",
        str(protected_request),
        check=False,
    )
    assert protected["status"] == "enhancement_required"
    assert protected["provider_chain"] == ["core-python"]
    assert protected["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert not protected_output.exists()
