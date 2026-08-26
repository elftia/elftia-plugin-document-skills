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
    replacement_diff = replaced["diagnostics"]["operation_result"]["structure_diff"]
    assert replacement_diff["changed_parts"] == [
        "word/document.xml",
        "word/footer1.xml",
        "word/header1.xml",
    ]
    assert all(
        item["delta"] == 0
        for item in replacement_diff["counts"].values()
    )

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


def test_public_template_apply_uses_dotx_as_a_preserved_docx_base(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    template_content_type = (
        b"application/vnd.openxmlformats-officedocument."
        b"wordprocessingml.template.main+xml"
    )
    document_content_type = (
        b"application/vnd.openxmlformats-officedocument."
        b"wordprocessingml.document.main+xml"
    )
    template = tmp_path / "public-base.dotx"
    with zipfile.ZipFile(public_created) as source_archive:
        with zipfile.ZipFile(template, "w") as template_archive:
            for item in source_archive.infolist():
                payload = source_archive.read(item)
                if item.filename == "[Content_Types].xml":
                    assert payload.count(document_content_type) == 1
                    payload = payload.replace(
                        document_content_type,
                        template_content_type,
                    )
                template_archive.writestr(item, payload)
    template_sha256 = sha256_file(template)
    output = tmp_path / "rendered-from-dotx.docx"
    request = _request(
        tmp_path,
        "template-dotx.json",
        {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(template),
            "output": str(output),
            "arguments": {"variables": {"name": "Agent"}},
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", json.dumps(result, indent=2)
    assert result["provider_chain"] == ["core-node"]
    template_result = result["diagnostics"]["operation_result"]
    assert template_result["template_base"] == {
        "input_format": "dotx",
        "output_format": "docx",
        "converted_main_content_type": True,
    }
    preservation = template_result["preservation"]
    assert set(preservation["changed_parts"]) == {
        "[Content_Types].xml",
        "word/document.xml",
    }
    structural = template_result["structure_diff"]
    assert structural["changed_parts"] == [
        "[Content_Types].xml",
        "word/document.xml",
    ]
    assert all(
        item["delta"] == 0
        for item in structural["counts"].values()
    )
    with zipfile.ZipFile(template) as template_archive:
        with zipfile.ZipFile(output) as output_archive:
            content_types = output_archive.read("[Content_Types].xml")
            assert document_content_type in content_types
            assert template_content_type not in content_types
            for part in (
                "word/styles.xml",
                "word/header1.xml",
                "word/footer1.xml",
            ):
                assert output_archive.read(part) == template_archive.read(part)
    document = _read_document(
        project_root,
        tmp_path,
        output,
        "read-rendered-dotx.json",
    )
    body = next(story for story in document["stories"] if story["kind"] == "body")
    assert body["paragraphs"][1]["text"] == "Hello Agent"
    repeated_output = tmp_path / "rendered-from-dotx-repeated.docx"
    repeated_request = _request(
        tmp_path,
        "template-dotx-repeated.json",
        {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(template),
            "output": str(repeated_output),
            "arguments": {"variables": {"name": "Agent"}},
        },
    )
    repeated = _public(project_root, "run", "--request", str(repeated_request))
    assert repeated["status"] == "success", repeated
    assert repeated_output.read_bytes() == output.read_bytes()
    assert sha256_file(template) == template_sha256


def test_public_dotx_template_rejects_external_attachment_without_clobbering(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    template_content_type = (
        b"application/vnd.openxmlformats-officedocument."
        b"wordprocessingml.template.main+xml"
    )
    document_content_type = (
        b"application/vnd.openxmlformats-officedocument."
        b"wordprocessingml.document.main+xml"
    )
    relationship = (
        b'<Relationship Id="rIdAttached" '
        b'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        b'relationships/attachedTemplate" Target="https://example.invalid/base.dotx" '
        b'TargetMode="External"/>'
    )
    template = tmp_path / "external-base.dotx"
    with zipfile.ZipFile(public_created) as source_archive:
        with zipfile.ZipFile(template, "w") as template_archive:
            for item in source_archive.infolist():
                payload = source_archive.read(item)
                if item.filename == "[Content_Types].xml":
                    payload = payload.replace(
                        document_content_type,
                        template_content_type,
                    )
                elif item.filename == "word/_rels/document.xml.rels":
                    assert payload.count(b"</Relationships>") == 1
                    payload = payload.replace(
                        b"</Relationships>",
                        relationship + b"</Relationships>",
                    )
                template_archive.writestr(item, payload)
    template_sha256 = sha256_file(template)
    output = tmp_path / "existing-external-dotx.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "template-dotx-external.json",
        {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(template),
            "output": str(output),
            "arguments": {"variables": {"name": "Agent"}},
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"
    assert output.read_bytes() == original_destination
    assert sha256_file(template) == template_sha256
