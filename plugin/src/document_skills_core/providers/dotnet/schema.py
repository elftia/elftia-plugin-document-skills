"""OOXML schema validation through the .NET helper.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...core.io.temp_roots import OperationTempRoot
from .runner import DotnetOpenXmlRunner

_ERROR_FIELDS = ("part", "path", "description", "error_type")
_MAX_ERROR_FIELD_BYTES = 256


def validate_schema(
    input_docx: Path,
    runner: DotnetOpenXmlRunner,
) -> dict[str, Any]:
    """Run the OpenXML SDK schema validator. Returns valid + per-part errors."""
    with OperationTempRoot() as private_root:
        staged = private_root / "input.docx"
        staged.write_bytes(Path(input_docx).read_bytes())
        result = runner.run(
            "--schema-validate",
            stdin_payload={"input_path": str(staged)},
        )
    return _schema_response(result, "--schema-validate", max_errors=100)


def validate_spreadsheet_schema(
    input_workbook: Path,
    runner: DotnetOpenXmlRunner,
    *,
    max_errors: int,
) -> dict[str, Any]:
    """Run the OpenXML SDK validator against a SpreadsheetDocument."""

    with OperationTempRoot() as private_root:
        staged = private_root / ("input" + Path(input_workbook).suffix.casefold())
        staged.write_bytes(Path(input_workbook).read_bytes())
        result = runner.run(
            "--xlsx-schema-validate",
            stdin_payload={
                "input_path": str(staged),
                "max_errors": max_errors,
            },
        )
    return _schema_response(
        result,
        "--xlsx-schema-validate",
        max_errors=max_errors,
        expected_file_format="Microsoft365",
    )


def _schema_response(
    result: Any,
    subcommand: str,
    *,
    max_errors: int,
    expected_file_format: str | None = None,
) -> dict[str, Any]:
    if result.returncode != 0:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            f"dotnet helper {subcommand} exited non-zero.",
            details={"returncode": result.returncode},
        )
    data = result.json()
    if not isinstance(data, dict):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper returned non-object schema JSON.",
        )
    valid = data.get("valid")
    if not isinstance(valid, bool):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper schema valid field is not boolean.",
        )
    errors = data.get("errors", [])
    if not isinstance(errors, list):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper schema errors field is not a list.",
        )
    if any(type(item) is not dict for item in errors):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper schema errors contain a non-object entry.",
        )
    truncated = data.get("truncated", False)
    if type(truncated) is not bool:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper schema truncated field is not boolean.",
        )
    file_format = data.get("file_format")
    if expected_file_format is not None and file_format != expected_file_format:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "dotnet helper used an unexpected schema target version.",
            details={
                "expected_file_format": expected_file_format,
                "actual_file_format": file_format,
            },
        )
    normalized_errors = []
    field_truncations = 0
    for item in errors[:max_errors]:
        normalized = {}
        for field in _ERROR_FIELDS:
            raw = item.get(field, "")
            if type(raw) is not str:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_FAILED,
                    "dotnet helper schema error field is not a string.",
                    details={"field": field},
                )
            normalized[field], was_truncated = _bounded_text(raw)
            field_truncations += int(was_truncated)
        normalized_errors.append(normalized)
    return {
        "valid": valid,
        "errors": normalized_errors,
        "truncated": truncated or len(errors) > max_errors,
        "field_truncations": field_truncations,
        "file_format": file_format,
    }


def _bounded_text(value: str) -> tuple[str, bool]:
    encoded = value.encode("utf-8", errors="strict")
    if len(encoded) <= _MAX_ERROR_FIELD_BYTES:
        return value, False
    return encoded[:_MAX_ERROR_FIELD_BYTES].decode("utf-8", errors="ignore"), True
