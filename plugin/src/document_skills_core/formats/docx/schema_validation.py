"""Strict OpenXML schema result projection for the public DOCX operation."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record

_ERROR_FIELDS = frozenset({"part", "path", "description", "error_type"})


def project_schema_result(raw_result: object, *, max_errors: int) -> dict[str, Any]:
    if type(raw_result) is not dict or set(raw_result) != {"valid", "errors"}:
        _provider_failed("Schema provider returned an invalid result shape.")
    valid = raw_result["valid"]
    errors = raw_result["errors"]
    if type(valid) is not bool or type(errors) is not list or len(errors) > max_errors + 1:
        _provider_failed("Schema provider returned invalid bounded data.")
    projected = [_project_error(item, index) for index, item in enumerate(errors)]
    truncated = len(projected) > max_errors
    items = projected[:max_errors]
    if valid and items:
        _provider_failed("Schema provider marked a result valid while returning errors.")
    return {
        "valid": valid,
        "errors": items,
        "returned_errors": len(items),
        "truncated": truncated,
    }


def schema_validation_report(schema: dict[str, Any]) -> dict[str, Any]:
    outcome = "pass" if schema["valid"] else "fail"
    return {
        "schema_version": "1.0",
        "status": outcome,
        "gates": [
            gate_record(
                "docx.package-security",
                "pass",
                evidence={"policy": "reject"},
            ),
            gate_record(
                "schema.full",
                outcome,
                validator="dotnet-openxml",
                evidence={
                    "openxml_validator_ran": True,
                    "valid": schema["valid"],
                    "returned_errors": schema["returned_errors"],
                    "truncated": schema["truncated"],
                },
            ),
            gate_record(
                "visual.render",
                "unavailable",
                required=False,
                evidence={"reason": "Visual validation did not run."},
                warnings=["Optional visual validation is unavailable."],
            ),
        ],
    }


def _project_error(value: object, index: int) -> dict[str, str]:
    if type(value) is not dict or set(value) != _ERROR_FIELDS:
        _provider_failed("Schema provider returned an invalid error record.", index=index)
    return {
        field: _text(value[field], 8_192 if field == "description" else 2_048, index, field)
        for field in ("part", "path", "description", "error_type")
    }


def _text(value: object, ceiling: int, index: int, field: str) -> str:
    if type(value) is not str or len(value.encode("utf-8", errors="strict")) > ceiling:
        _provider_failed(
            "Schema provider returned invalid text.",
            index=index,
            field=field,
        )
    return value


def _provider_failed(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.PROVIDER_FAILED, message, details=details)
