"""Public PDF supervisor/worker failure-isolation regressions."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from document_skills_core.core.contracts.schemas import SchemaCatalog


CASES = [
    ("provider-exception", "pdf.render", "DS_PROVIDER_FAILED", "provider_exception", "execute", "RuntimeError", "poppler"),
    ("provider-crash", "pdf.ocr", "DS_PROVIDER_FAILED", "invalid_worker_result", "supervisor", "DocumentSkillsError", None),
    ("hang", "pdf.render", "DS_PROCESS_TIMEOUT", "timeout", "supervisor", "DocumentSkillsError", None),
    ("malformed", "pdf.ocr", "DS_PROVIDER_FAILED", "invalid_worker_result", "supervisor", "JSONDecodeError", None),
    ("oversized", "pdf.render", "DS_PROVIDER_FAILED", "invalid_worker_result", "supervisor", "ValueError", None),
]


@pytest.mark.parametrize(
    (
        "mode", "operation", "error_code", "reason_category",
        "phase", "exception_class", "provider",
    ),
    CASES,
)
def test_public_pdf_worker_failure_is_atomic_and_private(
    project_root: Path,
    tmp_path: Path,
    mode: str,
    operation: str,
    error_code: str,
    reason_category: str,
    phase: str,
    exception_class: str,
    provider: str | None,
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    source = _minimal_pdf(tmp_path / "source.pdf")
    destination = tmp_path / "sidecar.zip"
    destination.write_bytes(b"existing-sidecar")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "sentinel.bin").write_bytes(b"existing-artifact")
    request = tmp_path / f"{mode}.json"
    encoded = json.dumps(
        _request(operation, source, destination),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    if mode == "hang":
        encoded += " " * 66_000
    request.write_text(encoded, encoding="utf-8")
    before = _snapshot(tmp_path)

    completed = subprocess.run(
        [
            uv,
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(
                project_root
                / "tests"
                / "fixtures"
                / "pdf-worker-failures"
                / "public_runner.py"
            ),
            mode,
            str(request),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=15,
    )

    assert completed.returncode == 2
    assert completed.stdout.count(b"\n") == 1
    assert completed.stderr == b""
    assert all(secret not in completed.stdout for secret in (b"PRIVATE", b"topsecret", b"api_key"))
    payload = json.loads(completed.stdout)
    SchemaCatalog(project_root).validate("operation-result", payload)
    assert payload["status"] == "failed"
    assert payload["artifacts"] == []
    error = payload["errors"][0]
    assert error["code"] == error_code
    assert error["details"] == {
        "exception_class": exception_class,
        "phase": phase,
        "provider": provider,
        "reason_category": reason_category,
    }
    assert _snapshot(tmp_path) == before
    private_root = project_root / ".document-skills-tmp" / f"invocation-pdf-{mode}"
    assert not private_root.exists()


def _request(operation: str, source: Path, destination: Path) -> dict[str, object]:
    arguments: dict[str, object] = {
        "pages": [1],
        "dpi": 72,
        "max_pixels": 1_000_000,
        "max_total_bytes": 1_000_000,
    }
    if operation == "pdf.render":
        arguments["format"] = "png"
    else:
        arguments.update({"languages": ["eng"], "skip_text_pages": False})
    return {
        "schema_version": "1.0",
        "operation": operation,
        "input": str(source),
        "output": str(destination),
        "arguments": arguments,
        "options": {"fidelity": "enhanced"},
    }


def _snapshot(root: Path) -> dict[str, tuple[str, bytes]]:
    result: dict[str, tuple[str, bytes]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        result[relative] = ("directory", b"") if path.is_dir() else ("file", path.read_bytes())
    return result


def _minimal_pdf(path: Path) -> Path:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
            b"/Resources << >> /Contents 4 0 R >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{number} 0 obj\n".encode("ascii") + payload + b"\nendobj\n")
    xref_offset = len(header) + len(body)
    xref = bytearray(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for offset in offsets:
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path
