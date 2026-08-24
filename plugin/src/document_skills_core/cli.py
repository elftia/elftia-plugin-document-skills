"""Shared command parser and dispatcher for all four bundled entrypoints."""

import argparse
from pathlib import Path
import sys
from typing import Any

from document_skills_core import __version__

from .core.capabilities.reports import build_capabilities, build_doctor
from .core.contracts.errors import DocumentSkillsError, ErrorCode
from .core.contracts.models import gate_record, make_error_result
from .core.contracts.schemas import SchemaCatalog
from .core.contracts.serialization import dump_json, load_json_file
from .core.validation import validate_artifact
from .formats.docx.contracts import DOCX_OPERATIONS, parse_docx_request
from .formats.docx.validation import reopen_docx
from .formats.pdf.contracts import PDF_OPERATIONS, parse_pdf_request
from .formats.pdf.validation import reopen_pdf
from .formats.xlsx.contracts import XLSX_OPERATIONS, parse_xlsx_request
from .formats.xlsx.validation import reopen_xlsx
from .formats.pptx.contracts import PPTX_OPERATIONS, parse_pptx_request
from .formats.pptx.deep_validation import validate_deep_package
from .formats.pptx.validation import reopen_pptx
from .providers import build_default_registry


def parse_command(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="document-skill")
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--json", action="store_true", required=True)

    capabilities = commands.add_parser("capabilities")
    capabilities.add_argument("--json", action="store_true", required=True)

    run = commands.add_parser("run")
    run.add_argument("--request", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--input", required=True)
    validate.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def execute_request(
    request: dict[str, Any], project_root: Path, catalog: SchemaCatalog
) -> dict[str, Any]:
    operation = str(request.get("operation", ""))
    requested_fidelity = (
        request.get("options", {}).get("fidelity", "core")
        if isinstance(request.get("options", {}), dict)
        else "unknown"
    )
    try:
        catalog.validate("operation-request", request)
        if operation in DOCX_OPERATIONS:
            parse_docx_request(request)
        elif operation in XLSX_OPERATIONS:
            parse_xlsx_request(request)
        elif operation in PPTX_OPERATIONS:
            parse_pptx_request(request)
        elif operation in PDF_OPERATIONS:
            parse_pdf_request(request)
        result = build_default_registry(project_root).execute(request)
        try:
            catalog.validate("operation-result", result)
            result["validation"]["gates"].append(
                gate_record(
                    "result.schema",
                    "pass",
                    evidence={"fingerprint": catalog.fingerprint("operation-result")},
                )
            )
            catalog.validate("operation-result", result)
        except DocumentSkillsError as error:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Provider returned a result that violates the canonical schema.",
                details=error.details,
            ) from error
        return result
    except DocumentSkillsError as error:
        result = make_error_result(
            operation, error, requested_fidelity=requested_fidelity
        )
        catalog.validate("operation-result", result)
        return result
    except Exception as error:
        result = make_error_result(
            operation,
            DocumentSkillsError(
                ErrorCode.INTERNAL_ERROR,
                "The document operation failed at the facade boundary.",
                details={"phase": "dispatch", "reason": type(error).__name__},
            ),
            requested_fidelity=requested_fidelity,
        )
        catalog.validate("operation-result", result)
        return result


def main(format_id: str, project_root: Path, argv: list[str] | None = None) -> int:
    catalog = SchemaCatalog(project_root)
    args = parse_command(argv)
    try:
        payload = _dispatch(args, format_id, project_root, catalog)
    except Exception as error:
        payload = _contained_command_failure(args.command, format_id, error)
        catalog.validate(_report_schema(args.command), payload)
    dump_json(payload, sys.stdout)
    return (
        0
        if payload.get("status")
        not in {"failed", "fail", "invalid_request", "unavailable"}
        else 2
    )


def _dispatch(
    args: argparse.Namespace,
    format_id: str,
    project_root: Path,
    catalog: SchemaCatalog,
    *,
    invocation_base: Path | None = None,
) -> dict[str, Any]:
    base = (invocation_base or Path.cwd()).resolve(strict=True)
    if not base.is_dir():
        raise ValueError("invocation base is not a directory")
    if args.command == "doctor":
        payload = build_doctor(project_root, format_id)
        catalog.validate("doctor-report", payload)
        return payload
    if args.command == "capabilities":
        payload = build_capabilities(
            project_root, format_id, build_default_registry(project_root)
        )
        catalog.validate("capability-report", payload)
        return payload
    if args.command == "validate":
        reopen = None
        assertions = None
        if format_id == "docx":
            reopen = reopen_docx
        elif format_id == "xlsx":
            reopen = reopen_xlsx
        elif format_id == "pptx":
            reopen = reopen_pptx
            assertions = [("pptx-deep-validation", validate_deep_package)]
        elif format_id == "pdf":
            reopen = reopen_pdf
        payload = validate_artifact(
            _resolve_user_path(args.input, base),
            expected_format=format_id,
            reopen=reopen,
            assertions=assertions,
        )
        catalog.validate("validation-report", payload)
        return payload
    try:
        request = load_json_file(str(_resolve_user_path(args.request, base)))
        if type(request) is not dict:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Operation request must be a JSON object.",
                status="invalid_request",
            )
        request = _resolve_request_artifact_paths(request, base)
    except (OSError, ValueError) as error:
        payload = make_error_result(
            "",
            DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Operation request could not be read as JSON.",
                status="invalid_request",
                details={"reason": type(error).__name__},
            ),
        )
        catalog.validate("operation-result", payload)
        return payload
    return execute_request(request, project_root, catalog)


def _resolve_user_path(value: str, invocation_base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = invocation_base / path
    return path.resolve(strict=False)


def _resolve_request_artifact_paths(
    request: dict[str, Any],
    invocation_base: Path,
) -> dict[str, Any]:
    resolved = dict(request)
    for field in ("input", "output"):
        value = request.get(field)
        if type(value) is str:
            resolved[field] = str(_resolve_user_path(value, invocation_base))
    arguments = request.get("arguments")
    if type(arguments) is not dict:
        return resolved
    report = arguments.get("report")
    if type(report) is not dict:
        return resolved
    image = report.get("image")
    if type(image) is not dict:
        return resolved
    image_path = image.get("path")
    if type(image_path) is not str or _is_nonlocal_path(image_path):
        return resolved
    resolved_image = {
        **image,
        "path": str(_resolve_user_path(image_path, invocation_base)),
    }
    resolved_report = {**report, "image": resolved_image}
    resolved["arguments"] = {**arguments, "report": resolved_report}
    return resolved


def _is_nonlocal_path(value: str) -> bool:
    return "://" in value or value.startswith(("\\\\", "//"))


def _contained_command_failure(
    command: str, format_id: str, error: Exception
) -> dict[str, Any]:
    if command == "doctor":
        return {
            "schema_version": "1.0",
            "status": "unavailable",
            "project_version": __version__,
            "format": format_id,
            "runtime": [],
            "providers": [],
            "errors": [
                {
                    "code": ErrorCode.RUNTIME_UNAVAILABLE.value,
                    "component": "facade",
                    "message": "Doctor report generation failed safely.",
                }
            ],
        }
    if command == "capabilities":
        return {
            "schema_version": "1.0",
            "format": format_id,
            "operations": [],
            "providers": [],
            "validation": {
                "package": "unavailable",
                "schema": "unavailable",
                "visual": "unavailable",
            },
        }
    if command == "validate":
        raise error
    return make_error_result(
        "",
        DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "The provider boundary failed safely.",
            details={"phase": "dispatch", "reason": type(error).__name__[:64]},
        ),
    )


def _report_schema(command: str) -> str:
    return {
        "doctor": "doctor-report",
        "capabilities": "capability-report",
        "run": "operation-result",
        "validate": "validation-report",
    }[command]
