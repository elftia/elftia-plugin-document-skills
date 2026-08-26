import json
from pathlib import Path
import shutil
import subprocess

from document_skills_core.core.io.paths import sha256_file
from document_skills_core.formats.docx.validation import reopen_docx
from document_skills_core.formats.pdf.validation import reopen_pdf
from document_skills_core.providers.libreoffice import build_libreoffice_provider
from tests.support.docx_public import _require_libreoffice_or_skip


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
        timeout=120,
    )
    return json.loads(completed.stdout)


def _request(directory: Path, name: str, payload: dict[str, object]) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
    return path


def _create_legacy_doc(project_root: Path, tmp_path: Path) -> Path:
    modern = tmp_path / "legacy-source.docx"
    create_request = _request(
        tmp_path,
        "legacy-create.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(modern),
            "arguments": {
                "report": {
                    "blocks": [
                        {"type": "heading", "text": "Legacy", "level": 1},
                        {"type": "paragraph", "text": "Explicit conversion"},
                    ]
                }
            },
        },
    )
    created = _public(project_root, "run", "--request", str(create_request))
    assert created["status"] == "success", created

    _definition, provider = build_libreoffice_provider(project_root)
    evidence = provider.detect()
    if not evidence.available:
        _require_libreoffice_or_skip(
            "LibreOffice provider profile is unavailable"
        )
    if evidence.path:
        provider.runner.set_executable(evidence.path)
    output_dir = tmp_path / "legacy-fixture"
    output_dir.mkdir()
    return provider.runner.convert(modern, "doc", output_dir)


def test_public_legacy_doc_conversion_is_explicit_and_provider_gated(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _create_legacy_doc(project_root, tmp_path)
    source_sha256 = sha256_file(source)
    capabilities = _public(project_root, "capabilities", "--json")
    operations = {
        item["operation"]: item for item in capabilities["operations"]
    }
    assert operations["docx.convert.legacy"] == {
        "available": True,
        "fidelity": "enhanced",
        "operation": "docx.convert.legacy",
        "providers": ["libreoffice"],
        "reason": None,
    }

    for target_format in ("docx", "pdf"):
        output = tmp_path / f"legacy-converted.{target_format}"
        request = _request(
            tmp_path,
            f"legacy-convert-{target_format}.json",
            {
                "schema_version": "1.0",
                "operation": "docx.convert.legacy",
                "input": str(source),
                "output": str(output),
                "options": {"fidelity": "enhanced"},
                "arguments": {
                    "format": target_format,
                    "max_output_bytes": 8 * 1024 * 1024,
                },
            },
        )
        result = _public(project_root, "run", "--request", str(request))
        assert result["status"] == "success", result
        assert result["provider_chain"] == ["libreoffice"]
        conversion = result["diagnostics"]["operation_result"]["conversion"]
        assert conversion["input_format"] == "doc"
        assert conversion["format"] == target_format
        assert conversion["output_bytes"] == output.stat().st_size
        if target_format == "docx":
            assert reopen_docx(output)["parts"] >= 3
        else:
            assert reopen_pdf(output)["pages"] >= 1
        assert sha256_file(source) == source_sha256

    read_request = _request(
        tmp_path,
        "legacy-read-rejected.json",
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(source),
            "arguments": {},
        },
    )
    rejected = _public(
        project_root,
        "run",
        "--request",
        str(read_request),
        check=False,
    )
    assert rejected["status"] == "invalid_request", rejected
