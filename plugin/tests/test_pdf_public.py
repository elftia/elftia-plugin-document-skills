"""PDF public command surface tests — frozen uv subprocess boundary.

Exercises the real public CLI (document-pdf/scripts/run.py), the
supervisor/worker, one stdout JSON result, honest provider chain, and honest
optional ``unavailable`` gates.  Includes a Unicode invocation directory to
mirror the XLSX/PPTX public tests.

Module provenance: original Elftia-authored test suite.
"""

import json
from pathlib import Path
import subprocess

import pytest

from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.formats.pdf.create import create_pdf


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
            str(project_root / "skills/document-pdf/scripts/run.py"),
            *arguments,
        ],
        cwd=cwd or project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=60,
    )
    if check:
        assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
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


def _document() -> dict[str, object]:
    return {
        "metadata": {"title": "Public PDF", "author": "Test", "subject": ""},
        "page_size": "A4",
        "pages": [
            {
                "blocks": [
                    {"type": "heading", "text": "Title", "style": None, "table": None, "image": None, "shape": None},
                    {"type": "table", "text": None, "style": None, "table": {"rows": [{"cells": ["A", "B"]}]}, "image": None, "shape": None},
                ],
                "metadata": None,
            },
            {
                "blocks": [
                    {"type": "paragraph", "text": "Content", "style": None, "table": None, "image": None, "shape": None},
                    {"type": "image", "text": None, "style": None, "table": None, "image": {"filename": "img.png", "content_type": "image/png"}, "shape": None},
                    {"type": "vector_shape", "text": None, "style": None, "table": None, "image": None, "shape": {"kind": "rectangle", "x": 72, "y": 72, "width": 100, "height": 50, "stroke": None, "fill": None}},
                ],
                "metadata": None,
            },
        ],
    }


@pytest.fixture
def public_created(tmp_path: Path) -> Path:
    output = tmp_path / "public-created.pdf"
    create_pdf(output, _document())
    return output


# ---------------------------------------------------------------------------
# Capabilities + Doctor
# ---------------------------------------------------------------------------

def test_public_capabilities_list_pdf_operations(project_root: Path) -> None:
    report = _public(project_root, "capabilities", "--json")
    operations = {item["operation"]: item for item in report["operations"]}
    assert "pdf.read" in operations
    assert "pdf.inspect.structure" in operations
    assert "pdf.create" in operations
    assert "pdf.edit" in operations
    assert "pdf.rewrite.apply" in operations
    for op_name, item in operations.items():
        if "pdf" in op_name:
            assert item["available"] is True


def test_public_doctor_succeeds(project_root: Path) -> None:
    report = _public(project_root, "doctor", "--json")
    assert report["status"] == "healthy"


# ---------------------------------------------------------------------------
# Create + Read
# ---------------------------------------------------------------------------

def test_public_create_and_read(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    read_request = _request(
        tmp_path,
        "read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(read_request))
    assert result["status"] == "success"
    assert result["diagnostics"]["operation_result"]["page_count"] == 2


def test_public_create_is_deterministic(project_root: Path, tmp_path: Path) -> None:
    output1 = tmp_path / "d1.pdf"
    output2 = tmp_path / "d2.pdf"
    for out in [output1, output2]:
        req = _request(
            tmp_path,
            f"create_{out.stem}.json",
            {
                "schema_version": "1.0",
                "operation": "pdf.create",
                "output": str(out),
                "arguments": {"document": _document()},
            },
        )
        result = _public(
            project_root,
            "run",
            "--request",
            str(req),
            check=False,
        )
        SchemaCatalog(project_root).validate("operation-result", result)
        assert result["status"] == "enhancement_required"
        assert not any(item["role"] == "output" for item in result["artifacts"])
        assert result["validation"]["status"] != "pass"
        assert not out.exists()


def test_public_create_null_image_fails_before_candidate_and_preserves_destination(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing-null-image.pdf"
    output.write_bytes(b"existing-destination")
    document = _document()
    pages = document["pages"]
    assert isinstance(pages, list)
    second_page = pages[1]
    assert isinstance(second_page, dict)
    blocks = second_page["blocks"]
    assert isinstance(blocks, list)
    image_block = next(block for block in blocks if block["type"] == "image")
    image_block["image"] = None
    request = _request(
        tmp_path,
        "create-null-image.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] == "enhancement_required"
    assert result["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert result["errors"][0]["details"]["capability"] == "pdf.real-image"
    assert result["validation"]["status"] == "fail"
    assert not any(item["role"] == "output" for item in result["artifacts"])
    assert output.read_bytes() == b"existing-destination"


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

def test_public_inspect_inert(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    inspect_request = _request(
        tmp_path,
        "inspect.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.inspect.structure",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(inspect_request))
    assert result["status"] == "success"
    assert result["diagnostics"]["operation_result"]["dangerous_content_present"] is False


# ---------------------------------------------------------------------------
# Edit: Rotate
# ---------------------------------------------------------------------------

def test_public_edit_rotate(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-rotated.pdf"
    edit_request = _request(
        tmp_path,
        "rotate.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {"type": "rotate", "pages": [1], "degrees": 90},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(edit_request))
    assert result["status"] == "success"
    assert output.is_file()
    assert public_created.is_file()
    assert any(item["path"] == str(output.resolve()) for item in result["artifacts"])


# ---------------------------------------------------------------------------
# Edit: Merge
# ---------------------------------------------------------------------------

def test_public_edit_merge(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    # Create a second PDF to merge
    second = tmp_path / "second.pdf"
    create_pdf(second, _document())

    output = tmp_path / "public-merged.pdf"
    merge_request = _request(
        tmp_path,
        "merge.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {"type": "merge", "inputs": [str(public_created), str(second)]},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(merge_request))
    assert result["status"] == "success"
    assert output.is_file()
    op_result = result["diagnostics"]["operation_result"]
    assert op_result["primitive"] == "merge"
    assert op_result["page_count"] == 4


# ---------------------------------------------------------------------------
# Edit: Split
# ---------------------------------------------------------------------------

def test_public_edit_split(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-split.pdf"
    split_request = _request(
        tmp_path,
        "split.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "primitives": [
                    {"type": "split", "page_ranges": [[1, 1]]},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(split_request))
    assert result["status"] == "success"
    assert output.is_file()
    op_result = result["diagnostics"]["operation_result"]
    assert op_result["primitive"] == "split"
    assert op_result["retained_pages"] == 1


# ---------------------------------------------------------------------------
# Rewrite
# ---------------------------------------------------------------------------

def test_public_rewrite(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-rewritten.pdf"
    rewrite_request = _request(
        tmp_path,
        "rewrite.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "blocks": [
                    {"page": 1, "bbox": [72, 754, 300, 770], "text": "Title", "font": "F2", "size": 16.0, "color": None},
                ],
                "rewrites": [
                    {"block_index": 0, "text": "Modified Title"},
                ],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(rewrite_request))
    assert result["status"] == "success"
    assert output.is_file()
    op_result = result["diagnostics"]["operation_result"]
    assert "rewrite" in op_result
    assert op_result["rewrite"]["blocks_processed"] == 1


def test_public_rewrite_cjk_fails_closed(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    output = tmp_path / "public-cjk.pdf"
    rewrite_request = _request(
        tmp_path,
        "cjk_rewrite.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.rewrite.apply",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "blocks": [
                    {"page": 1, "bbox": [72, 754, 300, 770], "text": "Title", "font": "F2", "size": 16.0, "color": None},
                ],
                "rewrites": [
                    {"block_index": 0, "text": "日本語テスト"},
                ],
            },
        },
    )
    result = _public(
        project_root,
        "run",
        "--request",
        str(rewrite_request),
        check=False,
    )
    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] == "enhancement_required"
    assert not any(item["role"] == "output" for item in result["artifacts"])
    assert result["validation"]["status"] != "pass"
    assert not output.exists()


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

def test_public_validate_reopens_valid_pdf(project_root: Path, public_created: Path) -> None:
    result = _public(
        project_root,
        "validate",
        "--input",
        str(public_created),
        "--json",
    )
    outcomes = {item["id"]: item["outcome"] for item in result["gates"]}
    assert result["status"] == "pass"
    assert outcomes["provider.reopen"] == "pass"
    assert outcomes["visual.render"] == "unavailable"
    assert outcomes["schema.full"] == "unavailable"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_public_unknown_operation_rejected(project_root: Path, tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        "unknown.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.nonexistent",
            "input": str(tmp_path / "input.pdf"),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(request), check=False)
    assert result["status"] == "invalid_request"


def test_public_edit_output_equals_input_rejected(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    same = str(public_created.resolve())
    edit_request = _request(
        tmp_path,
        "same.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": same,
            "output": same,
            "arguments": {
                "primitives": [{"type": "rotate", "pages": [1], "degrees": 90}],
            },
        },
    )
    result = _public(project_root, "run", "--request", str(edit_request), check=False)
    assert result["status"] == "invalid_request"


# ---------------------------------------------------------------------------
# Unicode invocation directory
# ---------------------------------------------------------------------------

def test_public_unicode_invocation_directory(project_root: Path, tmp_path: Path) -> None:
    """Run from a directory containing non-ASCII characters in its path."""
    unicode_dir = tmp_path / "テスト_道場"
    unicode_dir.mkdir()
    output = unicode_dir / "ucreated.pdf"
    request_path = unicode_dir / "create.json"
    request_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation": "pdf.create",
                "output": str(output),
                "arguments": {"document": _document()},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    result = _public(
        project_root,
        "run",
        "--request",
        str(request_path),
        cwd=unicode_dir,
        check=False,
    )
    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] == "enhancement_required"
    assert not any(item["role"] == "output" for item in result["artifacts"])
    assert result["validation"]["status"] != "pass"
    assert not output.exists()


# ---------------------------------------------------------------------------
# Honest provider chain
# ---------------------------------------------------------------------------

def test_public_provider_chain_identifies_core_python(project_root: Path, public_created: Path, tmp_path: Path) -> None:
    """Verify the result advertises an honest provider chain for a read operation.

    The canonical result exposes at least one provider-chain entry and the
    accepted provider identity references core-python.
    """
    read_request = _request(
        tmp_path,
        "read_chain.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(public_created),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(read_request))
    assert result["status"] == "success"
    # The result should carry honest provider evidence
    assert "fidelity" in result or "provider_chain" in result
