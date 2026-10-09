"""Execute every optional DOCX operation and persist result-bound CI evidence."""

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any

from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.providers.libreoffice import build_libreoffice_provider
from document_skills_core.providers.libreoffice.quota import hard_quota_capability
from tools.ci_docx_optional_requests import (
    comments_add_request,
    comments_read_request,
    comments_resolve_request,
    libreoffice_requests,
    OPERATION_PROVIDERS,
    OPTIONAL_PROVIDERS,
    repair_create_request,
    revision_apply_request,
    revision_read_request,
    schema_request,
    source_create_request,
)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    evidence_root = Path(sys.argv[1]).resolve()
    evidence_root.mkdir(parents=True, exist_ok=True)
    for marker in ("evidence-index.json", "executed-profile.json"):
        (evidence_root / marker).unlink(missing_ok=True)
    catalog = SchemaCatalog(project_root)

    doctor = _command(project_root, "doctor", "--json")
    catalog.validate("doctor-report", doctor)
    _write_json(evidence_root / "doctor.json", doctor)
    capabilities = _command(project_root, "capabilities", "--json")
    catalog.validate("capability-report", capabilities)
    _write_json(evidence_root / "capabilities.json", capabilities)
    libreoffice_available = _assert_optional_profile(doctor, capabilities)

    source = evidence_root / "optional-source.docx"
    _run(
        project_root,
        evidence_root,
        catalog,
        "setup-source-create",
        source_create_request(source),
        "core-python",
    )
    results: dict[str, dict[str, Any]] = {}
    repair_source = _prepare_repair_source(project_root, evidence_root, catalog)
    legacy_source = _prepare_legacy_source(project_root, evidence_root, source)
    for request in libreoffice_requests(source, repair_source, legacy_source, evidence_root):
        results[request["operation"]] = _run_optional(project_root, evidence_root, catalog, request)
    _run_dotnet_operations(
        project_root, evidence_root, catalog, results
    )
    _write_final_evidence(evidence_root, results, libreoffice_available=libreoffice_available)
    return 0


def _prepare_repair_source(
    project_root: Path,
    evidence_root: Path,
    catalog: SchemaCatalog,
) -> Path:
    image = evidence_root / "setup-wide.png"
    # Tracked deterministic 16x16 PNG used only to force a repairable figure.
    image.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000100000001008060000001ff3ff61"
            "000000234944415438da63f8b045e3bf42c281ffe4d20c946806d10ca32e1875c1"
            "a80b06890b00d143851fb0c396de0000000049454e44ae426082"
        )
    )
    source = evidence_root / "repair-source.docx"
    _run(
        project_root,
        evidence_root,
        catalog,
        "setup-repair-create",
        repair_create_request(source, image),
        "core-python",
    )
    return source


def _prepare_legacy_source(
    project_root: Path,
    evidence_root: Path,
    source: Path,
) -> Path:
    _definition, provider = build_libreoffice_provider(project_root)
    detected = provider.detect()
    if not detected.available:
        raise AssertionError(f"LibreOffice is not callable: {detected}")
    if detected.path:
        provider.runner.set_executable(detected.path)
    output_root = evidence_root / "setup-legacy-input"
    output_root.mkdir(exist_ok=True)
    return provider.runner.convert(source, "doc", output_root)


def _run_dotnet_operations(
    project_root: Path,
    evidence_root: Path,
    catalog: SchemaCatalog,
    results: dict[str, dict[str, Any]],
) -> None:
    results["docx.revisions.read"] = _run_optional(
        project_root,
        evidence_root,
        catalog,
        revision_read_request(project_root),
    )
    revisions = results["docx.revisions.read"]["diagnostics"][
        "operation_result"
    ]["revisions"]["items"]
    revision_id = revisions[0]["id"]
    results["docx.revisions.apply"] = _run_optional(
        project_root,
        evidence_root,
        catalog,
        revision_apply_request(project_root, evidence_root, revision_id),
    )
    results["docx.comments.read"] = _run_optional(
        project_root,
        evidence_root,
        catalog,
        comments_read_request(project_root),
    )
    added_path = evidence_root / "comment-added.docx"
    results["docx.comments.add"] = _run_optional(
        project_root,
        evidence_root,
        catalog,
        comments_add_request(project_root, added_path),
    )
    comment_id = results["docx.comments.add"]["diagnostics"][
        "operation_result"
    ]["comment"]["id"]
    resolved_path = evidence_root / "comment-resolved.docx"
    results["docx.comments.resolve"] = _run_optional(
        project_root,
        evidence_root,
        catalog,
        comments_resolve_request(added_path, resolved_path, comment_id),
    )
    results["docx.validate.schema"] = _run_optional(
        project_root,
        evidence_root,
        catalog,
        schema_request(resolved_path),
    )


def _assert_optional_profile(
    doctor: dict[str, Any],
    capabilities: dict[str, Any],
) -> bool:
    quota = hard_quota_capability()
    if not quota.supported:
        raise AssertionError(f"Mandatory LibreOffice hard quota is unavailable: {quota.reason_category}")
    required = OPTIONAL_PROVIDERS
    for report in (doctor, capabilities):
        providers = {
            item["id"]: item
            for item in report["providers"]
            if item["id"] in OPTIONAL_PROVIDERS
        }
        if set(providers) != OPTIONAL_PROVIDERS:
            raise AssertionError(f"Optional provider set is incomplete: {providers}")
        if any(providers[provider]["available"] is not True for provider in required):
            raise AssertionError(f"Optional provider is unavailable: {providers}")
    operations = {
        item["operation"]: item for item in capabilities["operations"]
    }
    available_optional = {
        operation
        for operation, item in operations.items()
        if operation.startswith("docx.")
        and item["available"] is True
        and OPTIONAL_PROVIDERS.intersection(item["providers"])
    }
    expected_operations = {
        operation for operation, provider in OPERATION_PROVIDERS.items() if provider in required
    }
    if available_optional != expected_operations:
        raise AssertionError(
            f"Unexpected optional DOCX surface: {sorted(available_optional)}"
        )
    for operation, provider in OPERATION_PROVIDERS.items():
        item = operations[operation]
        if provider not in required:
            if item["available"] is not False:
                raise AssertionError(f"Quota-blocked {operation} was reported available: {item}")
            continue
        if item["available"] is not True or item["providers"] != [provider]:
            raise AssertionError(f"Unexpected {operation} capability: {item}")
    return True


def _run_optional(
    project_root: Path,
    evidence_root: Path,
    catalog: SchemaCatalog,
    request: dict[str, Any],
) -> dict[str, Any]:
    operation = request["operation"]
    return _run(
        project_root,
        evidence_root,
        catalog,
        operation.removeprefix("docx.").replace(".", "-"),
        request,
        OPERATION_PROVIDERS[operation],
    )


def _run(
    project_root: Path,
    evidence_root: Path,
    catalog: SchemaCatalog,
    slug: str,
    request: dict[str, Any],
    provider: str,
) -> dict[str, Any]:
    request_path = evidence_root / f"request-{slug}.json"
    result_path = evidence_root / f"result-{slug}.json"
    _write_json(request_path, request)
    result = _command(project_root, "run", "--request", str(request_path))
    catalog.validate("operation-result", result)
    if result["status"] != "success" or result["provider_chain"] != [provider]:
        raise AssertionError(f"Unexpected {request['operation']} result: {result}")
    _write_json(result_path, result)
    return result


def _command(project_root: Path, *arguments: str) -> dict[str, Any]:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is unavailable")
    completed = subprocess.run(
        [
            uv,
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
        check=False,
        shell=False,
        timeout=180,
    )
    if completed.returncode != 0 or completed.stderr:
        raise RuntimeError(
            f"Public DOCX command failed ({completed.returncode}): "
            f"{completed.stderr.decode('utf-8', errors='replace')}"
        )
    value = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    if type(value) is not dict:
        raise TypeError("Public DOCX command returned a non-object result")
    return value


def _write_final_evidence(
    evidence_root: Path,
    results: dict[str, dict[str, Any]],
    *,
    libreoffice_available: bool = True,
) -> None:
    if libreoffice_available is not True:
        raise AssertionError("Optional-provider evidence requires real LibreOffice execution.")
    required = OPTIONAL_PROVIDERS
    expected = {operation for operation, provider in OPERATION_PROVIDERS.items() if provider in required}
    if set(results) != expected:
        raise AssertionError(
            f"Optional operation evidence is incomplete: {sorted(results)}"
        )
    operations = [
        {
            "operation": operation,
            "status": result["status"],
            "provider_chain": result["provider_chain"],
            "request": (
                f"request-{operation.removeprefix('docx.').replace('.', '-')}.json"
            ),
            "result": (
                f"result-{operation.removeprefix('docx.').replace('.', '-')}.json"
            ),
        }
        for operation, result in sorted(results.items())
    ]
    _write_json(
        evidence_root / "evidence-index.json",
        {
            "schema_version": "1.0",
            "provider_profile": "optional-providers-required",
            "operations": operations,
            "quota": hard_quota_capability().evidence(),
        },
    )
    _write_json(
        evidence_root / "executed-profile.json",
        {
            "schema_version": "1.0",
            "evidence_source": "successful-operation-results",
            "platform": os.environ.get("RUNNER_OS", platform.system()),
            "revision": os.environ.get("GITHUB_SHA", "local"),
            "operations": operations,
            "quota": hard_quota_capability().evidence(),
            "junit": "junit.xml",
            "pytest_log": "pytest.log",
        },
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    raise SystemExit(main())
