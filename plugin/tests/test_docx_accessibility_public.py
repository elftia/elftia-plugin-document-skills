"""Public accessibility inspection through the bundled DOCX façade."""

import json
from pathlib import Path
import subprocess
from xml.etree.ElementTree import fromstring, SubElement, tostring
import zipfile

from document_skills_core.core.io.paths import sha256_file
from document_skills_core.formats.docx.constants import qn


def test_public_accessibility_inspection_reports_bounded_semantic_issues(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-rich.docx"
    source_sha256 = sha256_file(source)
    request = tmp_path / "accessibility.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation": "docx.inspect.accessibility",
                "input": str(source),
                "arguments": {"max_issues": 10},
            }
        ),
        encoding="utf-8",
        newline="\n",
    )

    result = _public(project_root, request)

    assert result["status"] == "success", result
    assert result["provider_chain"] == ["core-python"]
    accessibility = result["diagnostics"]["operation_result"]["accessibility"]
    assert accessibility["status"] == "review_required"
    assert accessibility["truncated"] is False
    assert accessibility["issue_count"] == 2
    assert accessibility["returned_issues"] == 2
    assert {issue["code"] for issue in accessibility["issues"]} == {
        "DOCUMENT_LANGUAGE_MISSING",
        "TABLE_HEADER_MISSING",
    }
    checks = {check["id"]: check for check in accessibility["checks"]}
    assert checks == {
        "document_language": {"id": "document_language", "items_checked": 1, "issues": 1},
        "heading_hierarchy": {"id": "heading_hierarchy", "items_checked": 1, "issues": 0},
        "image_alt_text": {"id": "image_alt_text", "items_checked": 1, "issues": 0},
        "table_headers": {"id": "table_headers", "items_checked": 1, "issues": 1},
    }
    assert sha256_file(source) == source_sha256


def test_style_local_language_does_not_replace_document_language_metadata(
    project_root: Path,
    tmp_path: Path,
) -> None:
    original = project_root / "tests/fixtures/docx-rich.docx"
    source = tmp_path / "style-local-language.docx"
    with zipfile.ZipFile(original) as archive:
        styles = fromstring(archive.read("word/styles.xml"))
    style = next(styles.iter(qn("w", "style")))
    run_properties = style.find(qn("w", "rPr"))
    if run_properties is None:
        run_properties = SubElement(style, qn("w", "rPr"))
    SubElement(run_properties, qn("w", "lang"), {qn("w", "val"): "en-US"})
    _rewrite_part(
        original,
        source,
        "word/styles.xml",
        tostring(styles, encoding="utf-8", xml_declaration=True),
    )
    request = tmp_path / "style-local-language.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation": "docx.inspect.accessibility",
                "input": str(source),
                "arguments": {"max_issues": 10},
            }
        ),
        encoding="utf-8",
        newline="\n",
    )

    result = _public(project_root, request)

    accessibility = result["diagnostics"]["operation_result"]["accessibility"]
    assert "DOCUMENT_LANGUAGE_MISSING" in {
        issue["code"] for issue in accessibility["issues"]
    }


def test_disabled_repeating_header_marker_is_reported_as_missing(
    project_root: Path,
    tmp_path: Path,
) -> None:
    original = project_root / "tests/fixtures/docx-rich.docx"
    source = tmp_path / "disabled-table-header.docx"
    with zipfile.ZipFile(original) as archive:
        document = fromstring(archive.read("word/document.xml"))
    first_row = document.find(
        f".//{qn('w', 'tbl')}/{qn('w', 'tr')}"
    )
    assert first_row is not None
    row_properties = first_row.find(qn("w", "trPr"))
    if row_properties is None:
        row_properties = SubElement(first_row, qn("w", "trPr"))
    SubElement(
        row_properties,
        qn("w", "tblHeader"),
        {qn("w", "val"): "0"},
    )
    _rewrite_part(
        original,
        source,
        "word/document.xml",
        tostring(document, encoding="utf-8", xml_declaration=True),
    )
    request = tmp_path / "disabled-table-header.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation": "docx.inspect.accessibility",
                "input": str(source),
                "arguments": {"max_issues": 10},
            }
        ),
        encoding="utf-8",
        newline="\n",
    )

    result = _public(project_root, request)

    accessibility = result["diagnostics"]["operation_result"]["accessibility"]
    assert "TABLE_HEADER_MISSING" in {
        issue["code"] for issue in accessibility["issues"]
    }
    table_check = next(
        check for check in accessibility["checks"] if check["id"] == "table_headers"
    )
    assert table_check["issues"] == 1


def test_accessibility_findings_are_bounded_after_all_checks_run(
    project_root: Path,
    tmp_path: Path,
) -> None:
    original = project_root / "tests/fixtures/docx-rich.docx"
    source = tmp_path / "multiple-accessibility-issues.docx"
    with zipfile.ZipFile(original) as archive:
        document = fromstring(archive.read("word/document.xml"))
    heading_style = next(document.iter(qn("w", "pStyle")))
    heading_style.attrib[qn("w", "val")] = "Heading3"
    image_properties = next(document.iter(qn("wp", "docPr")))
    image_properties.attrib.pop("descr", None)
    _rewrite_part(
        original,
        source,
        "word/document.xml",
        tostring(document, encoding="utf-8", xml_declaration=True),
    )
    source_sha256 = sha256_file(source)
    request = tmp_path / "bounded-accessibility.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation": "docx.inspect.accessibility",
                "input": str(source),
                "arguments": {"max_issues": 2},
            }
        ),
        encoding="utf-8",
        newline="\n",
    )

    result = _public(project_root, request)

    assert result["status"] == "success", result
    accessibility = result["diagnostics"]["operation_result"]["accessibility"]
    assert accessibility["status"] == "review_required"
    assert accessibility["issue_count"] == 4
    assert accessibility["returned_issues"] == 2
    assert accessibility["truncated"] is True
    assert [issue["code"] for issue in accessibility["issues"]] == [
        "DOCUMENT_LANGUAGE_MISSING",
        "HEADING_LEVEL_SKIPPED",
    ]
    checks = {check["id"]: check["issues"] for check in accessibility["checks"]}
    assert checks == {
        "document_language": 1,
        "heading_hierarchy": 1,
        "image_alt_text": 1,
        "table_headers": 1,
    }
    assert result["warnings"] == [
        {
            "code": "DS_ACCESSIBILITY_TRUNCATED",
            "message": "Accessibility findings reached the caller-selected bound.",
            "details": {"issue_count": 4, "returned_issues": 2},
        }
    ]
    assert sha256_file(source) == source_sha256


def test_accessibility_contract_rejects_unknown_and_out_of_range_arguments(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = project_root / "tests/fixtures/docx-rich.docx"
    invalid_arguments = [
        {"max_issues": 0},
        {"max_issues": 1_001},
        {"max_issues": 10, "claim_wcag_conformance": True},
    ]
    for index, arguments in enumerate(invalid_arguments):
        request = tmp_path / f"invalid-accessibility-{index}.json"
        request.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "operation": "docx.inspect.accessibility",
                    "input": str(source),
                    "arguments": arguments,
                }
            ),
            encoding="utf-8",
            newline="\n",
        )

        result = _public(project_root, request)

        assert result["status"] == "invalid_request"
        assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"


def _public(project_root: Path, request: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-docx/scripts/run.py"),
            "run",
            "--request",
            str(request),
        ],
        cwd=project_root,
        capture_output=True,
        text=False,
        check=False,
        timeout=120,
    )
    assert completed.stderr == b""
    payload = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    assert type(payload) is dict
    return payload


def _rewrite_part(
    source: Path,
    destination: Path,
    part: str,
    payload: bytes,
) -> None:
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as rewritten:
        for info in archive.infolist():
            rewritten.writestr(info, payload if info.filename == part else archive.read(info))
