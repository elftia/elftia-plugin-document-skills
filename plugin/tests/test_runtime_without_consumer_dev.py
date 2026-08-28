"""Production frozen-uv execution must not depend on consumer-only packages."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


def test_runtime_sync_and_public_command_exclude_consumer_dev_dependencies(
    project_root: Path,
    tmp_path: Path,
) -> None:
    from docx import Document

    artifact = tmp_path / "runtime.docx"
    document = Document()
    document.add_paragraph("runtime without consumer dependencies")
    document.save(artifact)
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation": "docx.read",
                "input": str(artifact),
                "arguments": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    runtime_environment = tmp_path / "runtime-environment"
    environment = os.environ.copy()
    environment.pop("VIRTUAL_ENV", None)
    environment["UV_PROJECT_ENVIRONMENT"] = str(runtime_environment)

    sync = subprocess.run(
        [
            "uv",
            "sync",
            "--project",
            str(project_root),
            "--frozen",
            "--no-dev",
            "--offline",
        ],
        cwd=project_root,
        env=environment,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=60,
    )
    assert sync.returncode == 0, sync.stderr.decode("utf-8", errors="replace")

    result = _run_public(
        project_root,
        environment,
        skill="document-docx",
        request=request,
    )
    assert result["status"] == "success"

    pdf = tmp_path / "runtime.pdf"
    create_request = tmp_path / "pdf-create-request.json"
    create_request.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation": "pdf.create",
                "output": str(pdf),
                "arguments": {
                    "document": {
                        "metadata": {
                            "title": "Production dependency smoke",
                            "author": "Elftia",
                            "subject": "",
                        },
                        "page_size": "A4",
                        "pages": [
                            {
                                "blocks": [
                                    {
                                        "type": "paragraph",
                                        "text": "PDF production dependencies are available.",
                                        "style": None,
                                        "table": None,
                                        "image": None,
                                        "shape": None,
                                    }
                                ],
                                "metadata": None,
                            }
                        ],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    create_result = _run_public(
        project_root,
        environment,
        skill="document-pdf",
        request=create_request,
    )
    assert create_result["status"] == "success"
    assert pdf.is_file()

    read_request = tmp_path / "pdf-read-request.json"
    read_request.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation": "pdf.read",
                "input": str(pdf),
                "arguments": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    read_result = _run_public(
        project_root,
        environment,
        skill="document-pdf",
        request=read_request,
    )
    assert read_result["status"] == "success"
    operation_result = read_result["diagnostics"]["operation_result"]
    assert operation_result["page_count"] == 1
    assert operation_result["text_by_page"][0]["text"] == (
        "PDF production dependencies are available."
    )

    python = runtime_environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    absent = subprocess.run(
        [
            str(python),
            "-c",
            (
                "import importlib.util; "
                "names=('docx','fitz','openpyxl','pptx'); "
                "assert all(importlib.util.find_spec(name) is None for name in names); "
                "assert importlib.util.find_spec('pypdf') is not None; "
                "assert importlib.util.find_spec('PIL') is not None"
            ),
        ],
        cwd=project_root,
        env=environment,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=30,
    )
    assert absent.returncode == 0, absent.stderr.decode("utf-8", errors="replace")


def _run_public(
    project_root: Path,
    environment: dict[str, str],
    *,
    skill: str,
    request: Path,
) -> dict[str, object]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "--no-dev",
            "--offline",
            "--no-sync",
            "python",
            str(project_root / f"skills/{skill}/scripts/run.py"),
            "run",
            "--request",
            str(request),
        ],
        cwd=project_root,
        env=environment,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=60,
    )
    diagnostic = process.stdout.decode("utf-8", errors="replace")
    assert process.returncode == 0, diagnostic or "public stdout was empty"
    assert process.stderr == b""
    result = json.loads(process.stdout.decode("utf-8", errors="strict"))
    assert isinstance(result, dict)
    return result
