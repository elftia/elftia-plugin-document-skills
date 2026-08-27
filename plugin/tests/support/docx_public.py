import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from xml.etree.ElementTree import fromstring, SubElement, tostring
import zipfile

import pytest

from document_skills_core.cli import execute_request
from document_skills_core.core.capabilities import (
    Capability,
    DetectionEvidence,
    Provider,
    ProviderCatalog,
    ProviderId,
)
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import sha256_file
from document_skills_core.formats.docx.constants import qn
from document_skills_core.formats.docx.service import DocxService
from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.validation import reopen_pdf
from document_skills_core.public_cli.protocol import PublicCommand
from document_skills_core.public_cli.supervisor import PublicCommandSupervisor

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_PNG_16 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAI0lEQVR42mP4sEXjv0LCg"
    "f/k0gyUaAbRDKMuGHXBqAsGiQsA0UOFH7DDlt4AAAAASUVORK5CYII="
)
_GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")


def _require_libreoffice_or_skip(reason: str) -> None:
    if os.environ.get("ELFTIA_REQUIRE_LIBREOFFICE_PROFILE") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


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
        # LibreOffice conversion owns a 90-second aggregate worker budget;
        # leave startup/teardown headroom around that operation-specific limit.
        timeout=120,
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


def _read_document(
    project_root: Path,
    tmp_path: Path,
    source: Path,
    name: str,
) -> dict[str, object]:
    request = _request(
        tmp_path,
        name,
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(source),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(request))
    assert result["status"] == "success", result
    return result["diagnostics"]["operation_result"]["document"]


def _table_values(table: dict[str, object]) -> list[list[str]]:
    return [
        [
            "\n".join(paragraph["text"] for paragraph in cell["paragraphs"])
            for cell in row["cells"]
        ]
        for row in table["rows"]
    ]


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
    assert result["status"] == "success", json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
    )
    assert result["provider_chain"] == ["core-python"]
    SchemaCatalog(project_root).validate("operation-result", result)
    return output
