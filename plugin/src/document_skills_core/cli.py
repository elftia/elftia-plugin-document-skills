"""Shared command parser and dispatcher for all four bundled entrypoints."""

import argparse
import os
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
    operation = request.get("operation")
    no_follow = operation in {
        "docx.template.import.inspect",
        "docx.template.import.create",
        "docx.template.pack.instantiate",
    }
    for field in ("input", "output"):
        value = request.get(field)
        if type(value) is str:
            resolved[field] = str(
                _absolute_user_path(value, invocation_base)
                if no_follow
                else _resolve_user_path(value, invocation_base)
            )
    arguments = request.get("arguments")
    if type(arguments) is not dict:
        return resolved
    resolved_arguments = _resolve_pdf_argument_paths(
        request.get("operation"),
        arguments,
        invocation_base,
    )
    pack = resolved_arguments.get("pack")
    if type(pack) is dict and pack.get("kind") == "local" and type(pack.get("path")) is str:
        resolved_arguments["pack"] = {
            **pack,
            "path": str(_absolute_user_path(pack["path"], invocation_base)),
        }
    local_packs = resolved_arguments.get("local_packs")
    if type(local_packs) is list:
        resolved_arguments["local_packs"] = [
            {
                **item,
                "path": str(_absolute_user_path(item["path"], invocation_base)),
            }
            if type(item) is dict and item.get("kind") == "local" and type(item.get("path")) is str
            else item
            for item in local_packs
        ]
    report = resolved_arguments.get("report")
    if type(report) is dict:
        resolved_report = dict(report)
        image = report.get("image")
        if type(image) is dict:
            resolved_report["image"] = _resolve_local_image(image, invocation_base)
        blocks = report.get("blocks")
        if type(blocks) is list:
            resolved_report["blocks"] = [
                _resolve_local_image(block, invocation_base)
                if type(block) is dict and block.get("type") == "image"
                else block
                for block in blocks
            ]
        resolved_arguments["report"] = resolved_report
    edits = resolved_arguments.get("edits")
    if type(edits) is list:
        resolved_edits = []
        for edit in edits:
            if type(edit) is not dict or type(edit.get("image")) is not dict:
                resolved_edits.append(edit)
                continue
            resolved_edits.append(
                {
                    **edit,
                    "image": _resolve_local_image(edit["image"], invocation_base),
                }
            )
        resolved_arguments["edits"] = resolved_edits
    style_overlay = resolved_arguments.get("style_overlay")
    if type(style_overlay) is dict and type(style_overlay.get("source")) is str:
        resolved_arguments["style_overlay"] = {
            **style_overlay,
            "source": str(
                _resolve_user_path(style_overlay["source"], invocation_base)
            ),
        }
    sources = resolved_arguments.get("sources")
    if type(sources) is list:
        resolved_arguments["sources"] = [
            {
                **source,
                "path": str(_resolve_user_path(source["path"], invocation_base)),
            }
            if type(source) is dict and type(source.get("path")) is str
            else source
            for source in sources
        ]
    descriptor = resolved_arguments.get("descriptor")
    if type(descriptor) is dict:
        resolved_descriptor = dict(descriptor)
        contract_root = descriptor.get("contract_root")
        if type(contract_root) is str and not _is_nonlocal_path(contract_root):
            resolved_descriptor["contract_root"] = str(
                _resolve_user_path(contract_root, invocation_base)
            )
        for field in ("deck_ir", "semantic_slots", "template_contract"):
            reference = descriptor.get(field)
            if type(reference) is not dict:
                continue
            reference_path = reference.get("path")
            if type(reference_path) is str and not _is_nonlocal_path(reference_path):
                resolved_descriptor[field] = {
                    **reference,
                    "path": str(_resolve_user_path(reference_path, invocation_base)),
                }
        resolved_arguments["descriptor"] = resolved_descriptor
    pages = resolved_arguments.get("pages")
    if type(pages) is list:
        resolved_arguments["pages"] = [
            _resolve_template_page_paths(page, invocation_base)
            for page in pages
        ]
    resolved["arguments"] = resolved_arguments
    return resolved


def _absolute_user_path(value: str, invocation_base: Path) -> Path:
    """Make a user path absolute without erasing symlink/reparse evidence."""

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = invocation_base / path
    return Path(os.path.abspath(path))


def _resolve_local_image(
    image: dict[str, Any],
    invocation_base: Path,
) -> dict[str, Any]:
    image_path = image.get("path")
    if type(image_path) is not str or _is_nonlocal_path(image_path):
        return image
    return {
        **image,
        "path": str(_resolve_user_path(image_path, invocation_base)),
    }


def _resolve_template_page_paths(page: Any, invocation_base: Path) -> Any:
    if type(page) is not dict or type(page.get("bindings")) is not list:
        return page
    resolved_bindings = []
    for binding in page["bindings"]:
        if type(binding) is not dict or type(binding.get("value")) is not dict:
            resolved_bindings.append(binding)
            continue
        value = binding["value"]
        image_path = value.get("path")
        if (
            value.get("type") == "image-ref"
            and type(image_path) is str
            and not _is_nonlocal_path(image_path)
        ):
            value = {
                **value,
                "path": str(_resolve_user_path(image_path, invocation_base)),
            }
        resolved_bindings.append({**binding, "value": value})
    return {**page, "bindings": resolved_bindings}


def _resolve_pdf_argument_paths(
    operation: Any,
    arguments: dict[str, Any],
    invocation_base: Path,
) -> dict[str, Any]:
    if type(operation) is not str or not operation.startswith("pdf."):
        return arguments
    resolved = dict(arguments)
    document = arguments.get("document")
    if type(document) is dict:
        resolved["document"] = _resolve_pdf_document_paths(document, invocation_base)
    fonts = arguments.get("fonts")
    if type(fonts) is list:
        resolved["fonts"] = [
            _resolve_mapping_path(item, "filename", invocation_base)
            for item in fonts
        ]
    primitives = arguments.get("primitives")
    if type(primitives) is list:
        resolved["primitives"] = [
            _resolve_pdf_primitive_paths(item, invocation_base)
            for item in primitives
        ]
    compare_to = arguments.get("compare_to")
    if type(compare_to) is str and not _is_nonlocal_path(compare_to):
        resolved["compare_to"] = str(_resolve_user_path(compare_to, invocation_base))
    return resolved


def _resolve_pdf_document_paths(
    document: dict[str, Any],
    invocation_base: Path,
) -> dict[str, Any]:
    resolved = dict(document)
    fonts = document.get("fonts")
    if type(fonts) is list:
        resolved["fonts"] = [
            _resolve_mapping_path(item, "filename", invocation_base)
            for item in fonts
        ]
    pages = document.get("pages")
    if type(pages) is list:
        resolved["pages"] = [
            _resolve_pdf_page_paths(page, invocation_base)
            for page in pages
        ]
    return resolved


def _resolve_pdf_page_paths(page: Any, invocation_base: Path) -> Any:
    if type(page) is not dict:
        return page
    blocks = page.get("blocks")
    if type(blocks) is not list:
        return page
    resolved_blocks = []
    for block in blocks:
        if type(block) is not dict or type(block.get("image")) is not dict:
            resolved_blocks.append(block)
            continue
        resolved_blocks.append({
            **block,
            "image": _resolve_mapping_path(
                block["image"],
                "filename",
                invocation_base,
            ),
        })
    return {**page, "blocks": resolved_blocks}


def _resolve_pdf_primitive_paths(primitive: Any, invocation_base: Path) -> Any:
    if type(primitive) is not dict:
        return primitive
    resolved = dict(primitive)
    if primitive.get("type") == "merge" and type(primitive.get("inputs")) is list:
        resolved["inputs"] = [
            _resolve_mapping_path(item, "input", invocation_base)
            for item in primitive["inputs"]
        ]
    elif primitive.get("type") == "page_insert":
        resolved = _resolve_mapping_path(resolved, "input", invocation_base)
    if type(primitive.get("image")) is dict:
        resolved["image"] = _resolve_mapping_path(
            primitive["image"],
            "filename",
            invocation_base,
        )
    return resolved


def _resolve_mapping_path(
    value: Any,
    field: str,
    invocation_base: Path,
) -> Any:
    if type(value) is not dict:
        return value
    path_value = value.get(field)
    if type(path_value) is not str or _is_nonlocal_path(path_value):
        return value
    return {
        **value,
        field: str(_resolve_user_path(path_value, invocation_base)),
    }


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
