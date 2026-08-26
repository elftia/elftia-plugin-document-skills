"""Public PDF supervisor/worker pipe and workspace failure regressions."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from document_skills_core.core.contracts.schemas import SchemaCatalog


CASES = [
    (
        "provider-exception",
        "pdf.render",
        "DS_PROVIDER_FAILED",
        "provider_exception",
        "execute",
        "RuntimeError",
        "poppler",
    ),
    (
        "provider-typed",
        "pdf.render",
        "DS_PROVIDER_FAILED",
        "provider_exception",
        "execute",
        "DocumentSkillsError",
        "poppler",
    ),
    (
        "provider-noise",
        "pdf.render",
        "DS_PROVIDER_FAILED",
        "provider_exception",
        "execute",
        "RuntimeError",
        "poppler",
    ),
    pytest.param(
        "workspace-lock-transient",
        "pdf.render",
        "DS_PROVIDER_FAILED",
        "provider_exception",
        "execute",
        "RuntimeError",
        "poppler",
        marks=pytest.mark.skipif(
            os.name != "nt", reason="requires Windows directory locking"
        ),
    ),
    pytest.param(
        "workspace-lock-permanent",
        "pdf.render",
        "DS_PROVIDER_FAILED",
        "provider_exception",
        "execute",
        "RuntimeError",
        "poppler",
        marks=pytest.mark.skipif(
            os.name != "nt", reason="requires Windows directory locking"
        ),
    ),
    (
        "provider-crash",
        "pdf.ocr",
        "DS_PROVIDER_FAILED",
        "worker_exit",
        "worker",
        "DocumentSkillsError",
        None,
    ),
    (
        "hostile-serialization",
        "pdf.ocr",
        "DS_PROVIDER_FAILED",
        "worker_exit",
        "worker",
        "DocumentSkillsError",
        None,
    ),
    (
        "hang",
        "pdf.render",
        "DS_PROCESS_TIMEOUT",
        "timeout",
        "supervisor",
        "DocumentSkillsError",
        None,
    ),
    (
        "malformed",
        "pdf.ocr",
        "DS_PROVIDER_FAILED",
        "invalid_worker_result",
        "supervisor",
        "ValueError",
        None,
    ),
    (
        "binding-mismatch",
        "pdf.ocr",
        "DS_PROVIDER_FAILED",
        "invalid_worker_result",
        "supervisor",
        "ValueError",
        None,
    ),
    (
        "command-mismatch",
        "pdf.ocr",
        "DS_PROVIDER_FAILED",
        "invalid_worker_result",
        "supervisor",
        "ValueError",
        None,
    ),
    (
        "trailing-noise",
        "pdf.render",
        "DS_PROVIDER_FAILED",
        "invalid_worker_result",
        "supervisor",
        "ValueError",
        None,
    ),
    (
        "oversized",
        "pdf.render",
        "DS_PROVIDER_FAILED",
        "overflow",
        "supervisor",
        "DocumentSkillsError",
        None,
    ),
]


@pytest.mark.parametrize(
    (
        "mode",
        "operation",
        "error_code",
        "reason_category",
        "phase",
        "exception_class",
        "provider",
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
    encoded_request = json.dumps(
        _request(operation, source, destination),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    if mode == "hang":
        encoded_request += " " * 66_000
    request.write_text(encoded_request, encoding="utf-8")
    before = _snapshot(tmp_path)
    lock_mode = mode.startswith("workspace-lock-")
    trace_path = (
        tmp_path.parent / f"{tmp_path.name}-{mode}-trace.json" if lock_mode else None
    )
    command = [
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
    ]
    if trace_path is not None:
        command.append(str(trace_path))

    trace = None
    try:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            command,
            cwd=project_root,
            check=False,
            capture_output=True,
            text=False,
            shell=False,
            timeout=15,
            env=environment,
        )
        if trace_path is not None:
            trace = json.loads(trace_path.read_text(encoding="ascii"))
    finally:
        if trace_path is not None:
            trace_path.unlink(missing_ok=True)

    assert completed.returncode == 2, completed.stdout.decode("utf-8", errors="replace")
    assert completed.stdout.count(b"\n") == 1
    assert completed.stderr == b""
    secrets = (b"PRIVATE", b"topsecret", b"api_key", str(request).encode())
    assert all(secret not in completed.stdout for secret in secrets)
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
    if trace is not None:
        _assert_workspace_lock_trace(mode, trace)


def _assert_workspace_lock_trace(mode: str, trace: dict[str, object]) -> None:
    assert trace["controller_error"] is None
    assert trace["lock_acquired"] is True
    assert trace["identity_replacement_blocked"] is True
    assert trace["residual_entries"] == []
    assert trace["supervisor_elapsed_seconds"] < 5.0
    if mode == "workspace-lock-transient":
        assert trace["cleanup_attempt_count"] == 2
        assert trace["cleanup_failure_count"] == 1
        assert trace["private_root_exists_after_supervisor"] is False
        assert trace["fixture_cleanup_used"] is False
    else:
        assert mode == "workspace-lock-permanent"
        assert trace["cleanup_attempt_count"] == 4
        assert trace["cleanup_failure_count"] == 4
        assert trace["private_root_exists_after_supervisor"] is True
        assert trace["fixture_cleanup_used"] is True


def test_pdf_worker_fixtures_parse_without_generating_bytecode(
    project_root: Path,
) -> None:
    fixture_root = project_root / "tests" / "fixtures" / "pdf-worker-failures"
    for name in ("public_runner.py", "worker.py"):
        path = fixture_root / name
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


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
        result[relative] = (
            ("directory", b"") if path.is_dir() else ("file", path.read_bytes())
        )
    return result


def _minimal_pdf(path: Path) -> Path:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << >> /Contents 4 0 R >>",
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
