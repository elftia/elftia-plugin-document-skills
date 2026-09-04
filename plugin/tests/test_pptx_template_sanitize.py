from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS
from xml.etree.ElementTree import tostring

from defusedxml.ElementTree import fromstring
import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pptx.package import OpcPackage, write_deterministic_zip
from document_skills_core.formats.pptx.template_sanitize import sanitize_template


_POLICY = {
    "active_content": "reject",
    "external_relationships": "remove",
    "hidden_or_unselected_content": "keep",
    "ole_and_embedded_files": "remove",
    "signatures": "reject",
    "unreachable_parts": "purge",
}
_PRESENTATION_TYPE = (
    "application/vnd.openxmlformats-officedocument."
    "presentationml.presentation.main+xml"
)
_TEMPLATE_TYPE = (
    "application/vnd.openxmlformats-officedocument."
    "presentationml.template.main+xml"
)


def _fixture(project_root: Path, name: str) -> Path:
    return project_root / "tests/fixtures/pptx/ecosystem_bc/templates" / name


def _sanitize(source: Path, output: Path, expected: str | None = None):
    source_hash = sha256(source.read_bytes()).hexdigest()
    return sanitize_template(
        source,
        output,
        source_sha256=source_hash,
        expected_sha256=source_hash if expected is None else expected,
        policy=_POLICY,
    )


def _public(
    project_root: Path,
    *arguments: str,
    check: bool = True,
) -> dict[str, object]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-pptx/scripts/run.py"),
            *arguments,
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=PUBLIC_CLI_TEST_TIMEOUT_SECONDS,
    )
    if check:
        assert process.returncode == 0, (
            process.stderr.decode("utf-8", errors="replace")
            or process.stdout.decode("utf-8", errors="replace")
        )
    assert process.stderr == b""
    text = process.stdout.decode("utf-8", errors="strict")
    payload, end = json.JSONDecoder().raw_decode(text)
    assert text[end:].strip() == ""
    assert type(payload) is dict
    return payload


def _request(tmp_path: Path, name: str, value: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(value, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _request_value(source: Path, output: Path) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": "pptx.template.sanitize",
        "input": str(source),
        "output": str(output),
        "arguments": {
            "expected_input_sha256": sha256(source.read_bytes()).hexdigest(),
            "policy": dict(_POLICY),
        },
    }


def test_template_sanitizer_removes_external_and_embedded_content(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _fixture(project_root, "external-and-ole.pptx")
    source_hash = sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "sanitized.pptx"
    result = _sanitize(source, output)

    assert sha256(source.read_bytes()).hexdigest() == source_hash
    candidate = OpcPackage.open(output)
    assert candidate.content_type_for("ppt/presentation.xml") == _PRESENTATION_TYPE
    assert not any(item.target_mode == "External" for item in candidate.relationships)
    assert not any(
        item.relationship_type.rsplit("/", 1)[-1].casefold() in {"oleobject", "package"}
        for item in candidate.relationships
    )
    assert not any(part.startswith("ppt/embeddings/") for part in candidate.parts)
    source_package = OpcPackage.open(source, allow_dangerous_inventory=True)
    assert candidate.parts["ppt/notesSlides/notesSlide1.xml"] == source_package.parts[
        "ppt/notesSlides/notesSlide1.xml"
    ]
    chart_xml = candidate.parts["ppt/charts/chart1.xml"]
    assert b"numRef" not in chart_xml and b"strRef" not in chart_xml
    assert b"numLit" in chart_xml and b"strLit" in chart_xml
    assert all(b"example.invalid" not in payload for payload in candidate.parts.values())

    operation = result.operation_result
    removed_types = {
        (item["type"], item["reason"])
        for item in operation["removed_relationships"]
    }
    assert ("package", "ole_or_embedded_file") in removed_types
    assert ("hyperlink", "external_relationship") in removed_types
    assert ("image", "external_relationship") in removed_types
    assert {item["part"] for item in operation["removed_parts"]} >= {
        "ppt/embeddings/syntheticWorkbook.xlsx",
        "ppt/media/image1.png",
    }
    assert operation["physical_purge"]["purged_parts_absent"] is True
    serialized = json.dumps(operation, ensure_ascii=False)
    assert "https://example.invalid" not in serialized
    assert all(item["target_sha256"] for item in operation["removed_relationships"])


def test_template_sanitizer_downgrades_potx_identity(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source_fixture = _fixture(project_root, "external-and-ole.pptx")
    package = OpcPackage.open(source_fixture, allow_dangerous_inventory=True)
    parts = dict(package.parts)
    content_types = fromstring(parts["[Content_Types].xml"])
    declaration = next(
        node
        for node in content_types
        if node.attrib.get("PartName") == "/ppt/presentation.xml"
    )
    declaration.set("ContentType", _TEMPLATE_TYPE)
    parts["[Content_Types].xml"] = tostring(
        content_types,
        encoding="UTF-8",
        xml_declaration=True,
    )
    potx = tmp_path / "source.potx"
    write_deterministic_zip(potx, parts)

    output = tmp_path / "downgraded.pptx"
    result = _sanitize(potx, output)
    assert result.operation_result["template_identity"] == {
        "input_content_type": _TEMPLATE_TYPE,
        "output_content_type": _PRESENTATION_TYPE,
        "template_downgraded": True,
    }
    assert OpcPackage.open(output).content_type_for("ppt/presentation.xml") == _PRESENTATION_TYPE


def test_template_sanitizer_rejects_signatures_active_content_and_bad_graphs(
    project_root: Path,
    tmp_path: Path,
) -> None:
    signed = _fixture(project_root, "mislabelled-active.pptx")
    with pytest.raises(DocumentSkillsError) as signed_error:
        _sanitize(signed, tmp_path / "signed-output.pptx")
    assert signed_error.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert signed_error.value.status == "invalid_request"
    assert signed_error.value.details["signature_inventory"]
    assert not (tmp_path / "signed-output.pptx").exists()

    package = OpcPackage.open(signed, allow_dangerous_inventory=True)
    parts = {
        name: payload
        for name, payload in package.parts.items()
        if not name.startswith("_xmlsignatures/")
    }
    root_rels = fromstring(parts["_rels/.rels"])
    for node in list(root_rels):
        if "digital-signature" in node.attrib.get("Type", ""):
            root_rels.remove(node)
    parts["_rels/.rels"] = tostring(root_rels, encoding="UTF-8", xml_declaration=True)
    content_types = fromstring(parts["[Content_Types].xml"])
    for node in list(content_types):
        if node.attrib.get("PartName", "").startswith("/_xmlsignatures/"):
            content_types.remove(node)
    parts["[Content_Types].xml"] = tostring(
        content_types,
        encoding="UTF-8",
        xml_declaration=True,
    )
    active = tmp_path / "active-only.pptx"
    write_deterministic_zip(active, parts)
    with pytest.raises(DocumentSkillsError) as active_error:
        _sanitize(active, tmp_path / "active-output.pptx")
    assert active_error.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert active_error.value.details["active_inventory"]
    assert not (tmp_path / "active-output.pptx").exists()

    malformed = _fixture(project_root, "orphan-and-dangling.pptx")
    with pytest.raises(DocumentSkillsError) as malformed_error:
        _sanitize(malformed, tmp_path / "malformed-output.pptx")
    details = malformed_error.value.details
    assert details["duplicate_relationship_ids"]
    assert details["dangling_relationships"]
    assert any(item["part"] == "ppt/media/unreachable.bin" for item in details["orphan_parts"])
    assert not (tmp_path / "malformed-output.pptx").exists()


def test_public_template_sanitize_truth_and_fail_closed_results(
    project_root: Path,
    tmp_path: Path,
) -> None:
    capabilities = _public(project_root, "capabilities", "--json")
    operation = next(
        item
        for item in capabilities["operations"]
        if item["operation"] == "pptx.template.sanitize"
    )
    assert operation["available"] is True
    assert operation["providers"] == ["core-python"]

    source = _fixture(project_root, "external-and-ole.pptx")
    output = tmp_path / "public-sanitized.pptx"
    success_request = _request(
        tmp_path,
        "success.json",
        _request_value(source, output),
    )
    success = _public(project_root, "run", "--request", str(success_request))
    assert success["status"] == "success", success
    assert output.is_file()
    assert success["provider_chain"] == ["core-python"]
    operation_result = success["diagnostics"]["operation_result"]
    assert operation_result["consumer"]["core_opc"]["status"] == "passed"
    assert operation_result["consumer"]["powerpoint"]["status"] == "not_run"
    assert operation_result["license_status"] == "not_evaluated"
    assert operation_result["physical_purge"]["reopen"] == "passed"
    receipt = operation_result["delivery_receipt"]
    receipt_payload = {
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    }
    independently_recomputed = sha256(
        json.dumps(
            receipt_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert receipt["receipt_sha256"] == independently_recomputed
    assert receipt["output_sha256"] == sha256(output.read_bytes()).hexdigest()
    assert receipt["input_sha256"] == sha256(source.read_bytes()).hexdigest()

    stale_output = tmp_path / "stale.pptx"
    stale_value = _request_value(source, stale_output)
    stale_value["arguments"]["expected_input_sha256"] = "0" * 64
    stale = _public(
        project_root,
        "run",
        "--request",
        str(_request(tmp_path, "stale.json", stale_value)),
        check=False,
    )
    assert stale["status"] == "invalid_request"
    assert stale["errors"][0]["code"] == "DS_STALE_PRECONDITION"
    assert not stale_output.exists()

    policy_output = tmp_path / "policy.pptx"
    invalid_policy = _request_value(source, policy_output)
    invalid_policy["arguments"]["policy"]["active_content"] = "remove"
    rejected_policy = _public(
        project_root,
        "run",
        "--request",
        str(_request(tmp_path, "policy.json", invalid_policy)),
        check=False,
    )
    assert rejected_policy["status"] == "invalid_request"
    assert not policy_output.exists()

    package = OpcPackage.open(source, allow_dangerous_inventory=True)
    unsupported_parts = dict(package.parts)
    chart = fromstring(unsupported_parts["ppt/charts/chart1.xml"])
    reference = next(
        node for node in chart.iter() if node.tag.rsplit("}", 1)[-1] == "numRef"
    )
    cache = next(
        node for node in reference if node.tag.rsplit("}", 1)[-1] == "numCache"
    )
    reference.remove(cache)
    unsupported_parts["ppt/charts/chart1.xml"] = tostring(
        chart,
        encoding="UTF-8",
        xml_declaration=True,
    )
    unsupported_source = tmp_path / "unsupported-cache.pptx"
    write_deterministic_zip(unsupported_source, unsupported_parts)
    unsupported_output = tmp_path / "unsupported-output.pptx"
    unsupported = _public(
        project_root,
        "run",
        "--request",
        str(
            _request(
                tmp_path,
                "unsupported.json",
                _request_value(unsupported_source, unsupported_output),
            )
        ),
        check=False,
    )
    assert unsupported["status"] == "invalid_request"
    assert unsupported["errors"][0]["code"] == "DS_UNSUPPORTED_FEATURE"
    assert not unsupported_output.exists()

    same_source = tmp_path / "same.pptx"
    same_source.write_bytes(source.read_bytes())
    same = _public(
        project_root,
        "run",
        "--request",
        str(_request(tmp_path, "same.json", _request_value(same_source, same_source))),
        check=False,
    )
    assert same["status"] == "invalid_request"
    assert same["errors"][0]["code"] == "DS_OUTPUT_EQUALS_INPUT"
    assert same_source.read_bytes() == source.read_bytes()

    unsafe_output = tmp_path / "unsafe.pptx"
    unsafe = _public(
        project_root,
        "run",
        "--request",
        str(
            _request(
                tmp_path,
                "unsafe.json",
                _request_value(
                    _fixture(project_root, "mislabelled-active.pptx"),
                    unsafe_output,
                ),
            )
        ),
        check=False,
    )
    assert unsafe["status"] == "invalid_request"
    assert unsafe["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"
    assert not unsafe_output.exists()

    malformed_output = tmp_path / "malformed-public.pptx"
    malformed = _public(
        project_root,
        "run",
        "--request",
        str(
            _request(
                tmp_path,
                "malformed.json",
                _request_value(
                    _fixture(project_root, "orphan-and-dangling.pptx"),
                    malformed_output,
                ),
            )
        ),
        check=False,
    )
    assert malformed["status"] == "invalid_request"
    assert malformed["errors"][0]["details"]["duplicate_relationship_ids"]
    assert malformed["errors"][0]["details"]["dangling_relationships"]
    assert not malformed_output.exists()


def test_template_sanitize_reports_resource_limit(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _fixture(project_root, "external-and-ole.pptx")
    package = OpcPackage.open(source, allow_dangerous_inventory=True)
    parts = dict(package.parts)
    parts["ppt/media/compression-bomb.bin"] = b"0" * 8_000_000
    bomb = tmp_path / "compression-bomb.pptx"
    write_deterministic_zip(bomb, parts)
    output = tmp_path / "bomb-output.pptx"
    request = _request(tmp_path, "bomb.json", _request_value(bomb, output))
    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )
    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == ErrorCode.RESOURCE_LIMIT.value
    assert not output.exists()
