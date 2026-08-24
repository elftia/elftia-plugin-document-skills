"""Public provider-gated SpreadsheetML schema validation."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_source_preserved,
    file_record,
    merge_source_preservation_failure,
)

from .contracts import parse_xlsx_request
from .format_policy import (
    allowed_inert_categories,
    assert_package_matches_path,
    format_id,
)
from .package import OpcPackage
from .results import success_result


def execute_schema_validation(
    request: dict[str, Any],
    *,
    project_root: Path,
    validator: Callable[[Path, int], dict[str, Any]],
) -> dict[str, Any]:
    """Validate an XLSX/XLSM with an accepted SpreadsheetDocument provider."""

    parsed = parse_xlsx_request(request)
    if parsed.operation != "xlsx.validate.schema":
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Spreadsheet schema provider binding does not match the request operation.",
            status="invalid_request",
        )
    assert parsed.input_path is not None
    source = file_record(parsed.input_path, "input")
    try:
        package = OpcPackage.open(
            parsed.input_path,
            allowed_inert_categories=allowed_inert_categories(
                format_id(parsed.input_path)
            ),
        )
        assert_package_matches_path(parsed.input_path, package.workbook_format)
        schema = validator(
            parsed.input_path,
            parsed.arguments["max_errors"],
        )
        assert_source_preserved(source.path, source.sha256)
    except Exception as error:
        merge_source_preservation_failure(error, source.path, source.sha256)
        raise

    valid = schema["valid"]
    errors = schema["errors"]
    truncated = schema.get("truncated", False)
    field_truncations = schema.get("field_truncations", 0)
    validation = _schema_validation_report(
        valid=valid,
        errors=errors,
        truncated=truncated,
        field_truncations=field_truncations,
        source_sha256=source.sha256,
        package=package,
    )
    operation_result = {
        "schema": {
            "valid": valid,
            "error_count": len(errors),
            "errors": errors,
            "max_errors": parsed.arguments["max_errors"],
            "truncated": truncated,
            "field_truncations": field_truncations,
        }
    }
    result = success_result(
        parsed,
        artifacts=[source.as_dict()],
        operation_result=operation_result,
        warnings=[],
        validation=validation,
        status="success" if valid else "failed",
        achieved_fidelity="enhanced",
    )
    if not valid:
        result["errors"] = [
            DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "The workbook does not conform to the OpenXML schema.",
                details={
                    "error_count": len(errors),
                    "truncated": truncated,
                },
            ).record()
        ]
    SchemaCatalog(project_root).validate("operation-result", result)
    return result


def _schema_validation_report(
    *,
    valid: bool,
    errors: list[dict[str, Any]],
    truncated: bool,
    field_truncations: int,
    source_sha256: str,
    package: OpcPackage,
) -> dict[str, Any]:
    gates = [
        gate_record(
            "xlsx.package-security",
            "pass",
            evidence={
                "workbook_format": package.workbook_format,
                "security": package.security,
            },
        ),
        gate_record(
            "schema.full",
            "pass" if valid else "fail",
            validator="dotnet-openxml",
            evidence={
                "document_type": "SpreadsheetDocument",
                "valid": valid,
                "error_count": len(errors),
                "truncated": truncated,
                "field_truncations": field_truncations,
            },
        ),
        gate_record(
            "source.preservation",
            "pass",
            evidence={"sha256": source_sha256},
        ),
        gate_record(
            "visual.render",
            "unavailable",
            required=False,
            evidence={"reason": "No visual render was requested."},
            warnings=["Visual rendering was not part of schema validation."],
        ),
    ]
    return {
        "schema_version": "1.0",
        "status": "pass" if valid else "fail",
        "gates": gates,
    }
