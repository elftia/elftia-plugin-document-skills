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
            str(project_root / "skills/document-docx/scripts/run.py"),
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
    assert process.returncode == 0
    assert process.stderr == b""
    result = json.loads(process.stdout.decode("utf-8", errors="strict"))
    assert result["status"] == "success"

    python = runtime_environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    absent = subprocess.run(
        [
            str(python),
            "-c",
            (
                "import importlib.util; "
                "names=('docx','fitz','openpyxl','pptx'); "
                "assert all(importlib.util.find_spec(name) is None for name in names)"
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
